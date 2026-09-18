"""Compile an approved pipeline config into dbt files. Text in, text out.

`harness compile orders` reads configs/pipelines/orders.yml and writes three files to
dbt_project/models/generated/:

  orders.sql             The transformation chain, one CTE per transformation. A final
                         `tagged` CTE runs every error-severity column test and lists the
                         ones each row failed in `_failed_rules`; this model keeps the rows
                         where that list is empty and selects exactly the configured columns.
  orders_quarantine.sql  The same chain, keeping the rows that failed, with `_failed_rules`.
  orders.yml             dbt schema tests for orders.sql, run after it is built as a safety
                         net. Severity carries through, so a `warn` test reports its rows
                         instead of quarantining them.

It never connects to a warehouse and never reads data. The warehouse config is read only
to refuse a missing target and to pick the SQL dialect. It refuses a draft pipeline.

All warehouse-specific SQL lives in templates/<dialect>.sql.j2. Only duckdb exists.
"""

from __future__ import annotations

from pathlib import Path

import jinja2
import yaml

from harness.config import ConfigError
from harness.config.connection import load_connections
from harness.config.pipeline import DATE_FORMATS, PipelineConfig, load_pipeline, pipeline_path

TEMPLATES_DIR = Path(__file__).parent / "templates"
GENERATED_DIR = Path("dbt_project/models/generated")

# Warehouse type -> dialect template. A second dialect is registered here.
DIALECTS = {"duckdb": "duckdb.sql.j2"}


class CompileError(Exception):
    """Every reason a pipeline cannot be compiled."""

    def __init__(self, problems: list[str]):
        super().__init__("\n".join(problems))
        self.problems = problems


def sql_literal(value) -> str:
    """A value written as a SQL literal: 'text' (quotes doubled), true/false, or a number."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _environment() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATES_DIR),
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["sql_literal"] = sql_literal
    env.globals["date_formats"] = DATE_FORMATS
    return env


def load_approved(name: str) -> tuple[PipelineConfig, str]:
    """Load a pipeline that is valid, approved, and has a supported target. Returns (config, dialect file)."""
    problems, config, target = [], None, None
    for load in (lambda: load_connections().target, lambda: load_pipeline(pipeline_path(name))):
        try:
            result = load()
        except ConfigError as err:
            problems += [f"{err.path.as_posix()}: {problem}" for problem in err.problems]
            continue
        if isinstance(result, PipelineConfig):
            config = result
        else:
            target = result
    if target is not None and target.type not in DIALECTS:
        problems.append(f"No SQL dialect for {target.type} yet; supported: {', '.join(DIALECTS)}.")
    if config is not None and config.status == "draft":
        problems.append(f"{name}.yml is still a draft. Review the REVIEW comments, then set status: approved.")
    if problems:
        raise CompileError(problems)
    return config, DIALECTS[target.type]


def _condition(column: str, test) -> str:
    """SQL that is true when a row fails the test. Plain SQL, the same in every dialect."""
    if test.test == "not_null":
        return f"{column} is null"
    if test.test == "unique":
        return f"{column} is not null and count(*) over (partition by {column}) > 1"
    if test.test == "accepted_values":
        return f"{column} not in ({', '.join(sql_literal(v) for v in test.values)})"
    bounds = []
    if test.min is not None:
        bounds.append(f"{column} < {sql_literal(test.min)}")
    if test.max is not None:
        bounds.append(f"{column} > {sql_literal(test.max)}")
    return " or ".join(bounds)


def _context(config: PipelineConfig, dialect_file: str) -> dict:
    """Everything the templates need, in plain dicts and lists."""
    steps, previous, used = [], "source", {}
    for index, step in enumerate(config.transformations):
        used[step.type] = used.get(step.type, 0) + 1
        cte = step.type if used[step.type] == 1 else f"{step.type}_{used[step.type]}"
        steps.append({"cte": cte, "index": index, "input": previous, **step.model_dump()})
        previous = cte
    checks = [
        {"label": f"{column.name}:{test.test}", "condition": _condition(column.name, test)}
        for column in config.columns
        for test in column.tests
        if test.severity == "error"
    ]
    return {
        "name": config.pipeline,
        "config_path": pipeline_path(config.pipeline).as_posix(),
        "dialect_file": dialect_file,
        "source": config.source,
        "steps": steps,
        "last_cte": previous,
        "checks": checks,
        "columns": [c.model_dump() for c in config.columns],
    }


def _dbt_test(test):
    """One test in dbt's vocabulary. dbt >= 1.10 expects test arguments under `arguments:`."""
    arguments, settings = {}, {}
    if test.test == "accepted_values":
        name = "accepted_values"
        arguments["values"] = list(test.values)
        if not all(isinstance(v, str) for v in test.values):
            arguments["quote"] = False
    elif test.test == "accepted_range":
        name = "dbt_utils.accepted_range"
        if test.min is not None:
            arguments["min_value"] = test.min
        if test.max is not None:
            arguments["max_value"] = test.max
    else:
        name = test.test
    if arguments:
        settings["arguments"] = arguments
    if test.severity == "warn":
        settings["config"] = {"severity": "warn"}
    return {name: settings} if settings else name


def _schema_yml(config: PipelineConfig) -> str:
    name = config.pipeline
    columns = []
    for column in config.columns:
        entry = {"name": column.name}
        if column.tests:
            entry["data_tests"] = [_dbt_test(t) for t in column.tests]
        columns.append(entry)
    document = {
        "version": 2,
        "models": [
            {"name": name, "description": f"Clean rows of the {name} pipeline.", "columns": columns},
            {"name": f"{name}_quarantine", "description": f"Rows of the {name} pipeline that failed a test."},
        ],
    }
    header = f"# GENERATED from {pipeline_path(name).as_posix()}. Do not edit.\n"
    return header + yaml.safe_dump(document, sort_keys=False, width=120)


def render(config: PipelineConfig, dialect_file: str) -> dict[str, str]:
    """The three generated files, as {filename: text}."""
    env, context = _environment(), _context(config, dialect_file)
    model = env.get_template("model.sql.j2")
    return {
        f"{config.pipeline}.sql": model.render(context, quarantine=False),
        f"{config.pipeline}_quarantine.sql": model.render(context, quarantine=True),
        f"{config.pipeline}.yml": _schema_yml(config),
    }


def step_counts_sql(config: PipelineConfig, dialect_file: str) -> str:
    """A query returning (step, row_count) for the source and each transformation."""
    return _environment().get_template("step_counts.sql.j2").render(_context(config, dialect_file))


def publish_sql(dialect_file: str, relation: str, schema: str, table: str) -> str:
    """SQL that copies a built table to the pipeline's target."""
    module = _environment().get_template(dialect_file).module
    return str(module.publish(relation, schema, table))


def write_generated(config: PipelineConfig, dialect_file: str) -> list[Path]:
    """Write the three generated files for an already-loaded config. Returns their paths."""
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for filename, text in render(config, dialect_file).items():
        path = GENERATED_DIR / filename
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written


def compile_pipeline(name: str) -> list[Path]:
    """Compile configs/pipelines/<name>.yml and write the generated files. Returns their paths."""
    return write_generated(*load_approved(name))
