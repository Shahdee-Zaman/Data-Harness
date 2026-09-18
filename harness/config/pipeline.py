"""The pipeline config schema: the harness's entire vocabulary.

A pipeline config lives at configs/pipelines/<name>.yml and describes how one CSV
becomes one table. `harness validate` rejects anything not described here; the
plain-English reference is docs/config-reference.md.

Beyond the shape of each key, these rules are checked:
- `pipeline` matches the filename.
- column names are unique.
- every column a transformation or quality rule refers to exists at the point it is
  used, after accounting for `rename` steps.
- `status: approved` requires `approved_by`.
- `max_age` looks like <number>h or <number>d.

Every problem in a file is reported together.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated, Literal, Union

import duckdb
from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, ValidationError, model_validator
from pydantic_core import PydanticCustomError

from harness.config import ConfigError, read_yaml

PIPELINES_DIR = Path("configs/pipelines")

# Date formats `parse_date` understands, in the order the profiler tries them, with the
# strptime pattern DuckDB uses for each.
DATE_FORMATS = {
    "YYYY-MM-DD": "%Y-%m-%d",
    "YYYY/MM/DD": "%Y/%m/%d",
    "MM/DD/YYYY": "%m/%d/%Y",
    "DD/MM/YYYY": "%d/%m/%Y",
}
TEST_NAMES = ("not_null", "unique", "accepted_values", "accepted_range")
TRANSFORM_TYPES = ("rename", "parse_date", "filter", "dedupe")
RULE_NAMES = ("freshness", "row_count_change")

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_COLUMN_TYPE = re.compile(r"^(integer|string|date|timestamp|boolean|decimal\((\d+),\s*(\d+)\))$")
_MAX_AGE = re.compile(r"^(\d+)(h|d)$")


def pipeline_path(name: str) -> Path:
    return PIPELINES_DIR / f"{name}.yml"


# ---------------------------------------------------------------- field checks

def _identifier(value: str) -> str:
    if not _IDENTIFIER.match(value):
        raise PydanticCustomError(
            "identifier",
            "'{value}' must use only letters, digits and underscores, and not start with a digit",
            {"value": value},
        )
    return value


def _column_type(value: str) -> str:
    match = _COLUMN_TYPE.match(value)
    if not match:
        raise PydanticCustomError(
            "column_type",
            "'{value}' is not a type; use integer, decimal(p,s), string, date, timestamp or boolean",
            {"value": value},
        )
    if match.group(2):
        precision, scale = int(match.group(2)), int(match.group(3))
        if not (1 <= precision <= 38 and scale <= precision):
            raise PydanticCustomError("column_type", "decimal(p,s) needs 1 <= p <= 38 and s <= p")
    return value


def _target(value: str) -> str:
    parts = value.split(".")
    if len(parts) != 2 or not all(_IDENTIFIER.match(p) for p in parts):
        raise PydanticCustomError("target", "must look like <schema>.<table>, e.g. silver.orders")
    return value


def _max_age(value: str) -> str:
    if not _MAX_AGE.match(value):
        raise PydanticCustomError("max_age", "must be a number followed by h or d, e.g. 24h or 2d")
    return value


def _none_is_empty(value):
    return [] if value is None else value


Identifier = Annotated[str, AfterValidator(_identifier)]
Severity = Literal["error", "warn"]
DateFormat = Literal[tuple(DATE_FORMATS)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- column tests

class NotNull(_Strict):
    test: Literal["not_null"]
    severity: Severity = "error"


class Unique(_Strict):
    test: Literal["unique"]
    severity: Severity = "error"


class AcceptedValues(_Strict):
    test: Literal["accepted_values"]
    values: list[Union[str, int, float, bool]] = Field(min_length=1)
    severity: Severity = "error"


class AcceptedRange(_Strict):
    test: Literal["accepted_range"]
    min: Union[int, float, None] = None
    max: Union[int, float, None] = None
    severity: Severity = "error"

    @model_validator(mode="after")
    def _bounds(self):
        if self.min is None and self.max is None:
            raise PydanticCustomError("range", "accepted_range needs min, max, or both")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise PydanticCustomError("range", "accepted_range min is greater than max")
        return self


def _test_entry(entry):
    """Turn `not_null` or `not_null: {severity: warn}` into {"test": "not_null", ...}."""
    if isinstance(entry, str):
        name, settings = entry, {}
    elif isinstance(entry, dict) and len(entry) == 1:
        name, settings = next(iter(entry.items()))
        settings = settings if settings is not None else {}
        if not isinstance(settings, dict):
            raise PydanticCustomError("test_shape", "settings for {name} must be a mapping", {"name": str(name)})
    else:
        raise PydanticCustomError(
            "test_shape",
            "write a test as a name, like not_null, or as one name with settings, like accepted_values: {values: [a, b]}",
        )
    if name not in TEST_NAMES:
        raise PydanticCustomError(
            "unknown_test",
            "unknown test '{name}'; allowed: {allowed}",
            {"name": str(name), "allowed": ", ".join(TEST_NAMES)},
        )
    return {**settings, "test": name}


ColumnTest = Annotated[
    Annotated[Union[NotNull, Unique, AcceptedValues, AcceptedRange], Field(discriminator="test")],
    BeforeValidator(_test_entry),
]


class Column(_Strict):
    name: Identifier
    type: Annotated[str, AfterValidator(_column_type)]
    tests: Annotated[list[ColumnTest], BeforeValidator(_none_is_empty)] = []


# ---------------------------------------------------------------- transformations

class Rename(_Strict):
    type: Literal["rename"]
    mapping: dict[Identifier, Identifier] = Field(min_length=1)


class ParseDate(_Strict):
    type: Literal["parse_date"]
    column: Identifier
    formats: list[DateFormat] = Field(min_length=1)


class Filter(_Strict):
    type: Literal["filter"]
    expr: str = Field(min_length=1)


class Dedupe(_Strict):
    type: Literal["dedupe"]
    keys: list[Identifier] = Field(min_length=1)
    order_by: str = Field(min_length=1)


def _known(field: str, allowed: tuple[str, ...], what: str) -> BeforeValidator:
    """Reject an unknown `type` or `rule` with a message that lists the allowed ones."""

    def check(entry):
        if isinstance(entry, dict) and entry.get(field) not in allowed:
            raise PydanticCustomError(
                "unknown_kind",
                "unknown {what} {field} '{kind}'; allowed: {allowed}",
                {"what": what, "field": field, "kind": str(entry.get(field)), "allowed": ", ".join(allowed)},
            )
        return entry

    return BeforeValidator(check)


Transformation = Annotated[
    Annotated[Union[Rename, ParseDate, Filter, Dedupe], Field(discriminator="type")],
    _known("type", TRANSFORM_TYPES, "transformation"),
]


# ---------------------------------------------------------------- quality rules

class Freshness(_Strict):
    rule: Literal["freshness"]
    column: Identifier
    max_age: Annotated[str, AfterValidator(_max_age)]
    severity: Severity = "error"

    @property
    def max_age_hours(self) -> int:
        number, unit = _MAX_AGE.match(self.max_age).groups()
        return int(number) * (24 if unit == "d" else 1)


class RowCountChange(_Strict):
    rule: Literal["row_count_change"]
    max_pct: float = Field(ge=0)
    severity: Severity = "error"


QualityRule = Annotated[
    Annotated[Union[Freshness, RowCountChange], Field(discriminator="rule")],
    _known("rule", RULE_NAMES, "quality"),
]


# ---------------------------------------------------------------- the whole file

class PipelineConfig(_Strict):
    pipeline: Identifier
    status: Literal["draft", "approved"]
    approved_by: Union[str, None] = None
    source: str = Field(min_length=1)
    target: Annotated[str, AfterValidator(_target)]
    columns: list[Column] = Field(min_length=1)
    transformations: Annotated[list[Transformation], BeforeValidator(_none_is_empty)] = []
    quality: Annotated[list[QualityRule], BeforeValidator(_none_is_empty)] = []
    on_failure: Literal["quarantine"]

    @property
    def target_schema(self) -> str:
        return self.target.split(".")[0]

    @property
    def target_table(self) -> str:
        return self.target.split(".")[1]


# ---------------------------------------------------------------- cross-key checks

def sql_columns(select_sql: str) -> tuple[list[str], str | None]:
    """Column names referenced in one SELECT statement, read with DuckDB's parser.

    Returns (names, None), or ([], reason) when the text is not exactly one valid SELECT.
    """
    parsed = json.loads(duckdb.execute("select json_serialize_sql(?)", [select_sql]).fetchone()[0])
    if parsed.get("error"):
        if parsed.get("error_type") != "parser":
            return [], "write a single expression, not several statements"
        return [], parsed.get("error_message", "could not parse")
    names: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("class") == "COLUMN_REF":
                names.append(node["column_names"][-1])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(parsed["statements"])
    return names, None


def _step_references(step) -> tuple[list[str], str | None]:
    """Columns a parse_date, filter or dedupe step reads, plus a problem if its SQL is bad."""
    if isinstance(step, ParseDate):
        return [step.column], None
    if isinstance(step, Filter):
        names, error = sql_columns(f"select 1 where {step.expr}")
        return names, error and f"expr is not a valid SQL condition ({error})"
    names, error = sql_columns(f"select 1 order by {step.order_by}")
    return step.keys + names, error and f"order_by is not valid SQL ({error})"


def _reference_problems(config: PipelineConfig) -> list[str]:
    """Check every column reference against the names that exist at that step."""
    # The source must supply the final names with every rename undone, last rename first.
    names = {c.name.lower() for c in config.columns}
    dead_renames = set()
    for index in reversed(range(len(config.transformations))):
        step = config.transformations[index]
        if isinstance(step, Rename):
            for old, new in step.mapping.items():
                if new.lower() in names:
                    names.discard(new.lower())
                    names.add(old.lower())
                else:
                    dead_renames.add((index, old))

    # Walk forward, checking each step against the names that exist when it runs.
    problems = []
    renamed = {}  # old name -> "new_name (transformations[i])", to explain a stale reference

    def missing(where: str, name: str) -> str:
        hint = f"; it was renamed to {renamed[name.lower()]}" if name.lower() in renamed else ""
        return f"{where}: column '{name}' does not exist at this step{hint}"

    for index, step in enumerate(config.transformations):
        where = f"transformations[{index}] ({step.type})"
        if isinstance(step, Rename):
            for old, new in step.mapping.items():
                if (index, old) in dead_renames:
                    problems.append(f"{where}: renames '{old}' to '{new}', but '{new}' is not in columns")
                    continue
                if old.lower() not in names:
                    problems.append(missing(where, old))
                elif new.lower() in names and new.lower() != old.lower():
                    problems.append(f"{where}: renaming '{old}' to '{new}' would duplicate '{new}'")
                names.discard(old.lower())
                names.add(new.lower())
                renamed[old.lower()] = f"'{new}' in transformations[{index}]"
            continue
        referenced, error = _step_references(step)
        if error:
            problems.append(f"{where}: {error}")
        for name in dict.fromkeys(referenced):
            if name.lower() not in names:
                problems.append(missing(where, name))

    final = {c.name.lower() for c in config.columns}
    for index, rule in enumerate(config.quality):
        if isinstance(rule, Freshness) and rule.column.lower() not in final:
            problems.append(f"quality[{index}] (freshness): column '{rule.column}' is not in columns")
    return problems


def _raw_problems(raw: dict, path: Path) -> list[str]:
    """Checks that need only the raw file, so they are reported even when its shape is wrong."""
    problems = []
    name = raw.get("pipeline")
    if isinstance(name, str) and name != path.stem:
        problems.append(f"pipeline: '{name}' must match the filename ({path.stem}.yml)")
    if raw.get("status") == "approved" and not raw.get("approved_by"):
        problems.append("approved_by: required when status is approved")
    seen: dict[str, list[str]] = {}
    for column in raw.get("columns") or []:
        if isinstance(column, dict) and isinstance(column.get("name"), str):
            seen.setdefault(column["name"].lower(), []).append(column["name"])
    for names in seen.values():
        if len(names) > 1:
            problems.append(f"columns: '{names[0]}' appears {len(names)} times; column names must be unique")
    return problems


# ---------------------------------------------------------------- loading

def _where(loc: tuple, raw: dict) -> str:
    """Render an error location like columns[amount].tests[0].values, skipping union tags."""
    tags = set(TEST_NAMES) | set(TRANSFORM_TYPES) | set(RULE_NAMES)
    parts: list[str] = []
    node = raw
    for part in loc:
        if isinstance(part, int):
            item = node[part] if isinstance(node, list) and part < len(node) else None
            label = part
            if parts and parts[-1] == "columns" and isinstance(item, dict) and isinstance(item.get("name"), str):
                label = item["name"]
            parts[-1] += f"[{label}]"
            node = item
        elif part not in tags:
            parts.append(str(part))
            node = node.get(part) if isinstance(node, dict) else None
    return ".".join(parts) or "(top level)"


def _describe(error: dict, raw: dict) -> str:
    message = {"missing": "required", "extra_forbidden": "unknown key"}.get(error["type"], error["msg"])
    return f"{_where(error['loc'], raw)}: {message}"


def load_pipeline(path: Path) -> PipelineConfig:
    """Read one pipeline config and check every rule. Raises ConfigError listing all problems."""
    path = Path(path)
    raw = read_yaml(path, "a mapping with keys like `pipeline:` and `columns:`")
    problems = _raw_problems(raw, path)
    try:
        config = PipelineConfig.model_validate(raw)
    except ValidationError as err:
        problems = [_describe(e, raw) for e in err.errors()] + problems
    else:
        problems += _reference_problems(config)
    if problems:
        raise ConfigError(path, list(dict.fromkeys(problems)))
    return config
