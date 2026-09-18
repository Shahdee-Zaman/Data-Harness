"""Load and check the warehouse connection config.

The connection config lives in configs/connections/warehouse.yml and names the
warehouse the harness writes to. Today it holds one block, `target`. A `source`
block can be added later as a second field on `Connections` that reuses the same
per-warehouse models below; it is deliberately not implemented yet.

Rules checked here:
- `type` must be duckdb, snowflake, bigquery or postgres. Null means "not chosen
  yet" and is an error, so nothing can compile or run against the placeholder.
- duckdb: `database` is a file path, `schema` defaults to main, no credentials.
- snowflake and postgres: `database`, `schema` and `credentials` are all required.
- bigquery: `database` is the GCP project and `schema` is the dataset; both are
  required, plus `credentials`.
- A value written as `env:NAME` is read from environment variable NAME at load
  time. Credentials are held as SecretStr, so printing them shows only asterisks.

Every problem in the file is reported together, not just the first one found.
Error messages name the key and the rule, and never echo the value.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal, Union

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    model_validator,
)
from pydantic_core import PydanticCustomError

from harness.config import ConfigError, read_yaml

DEFAULT_PATH = Path("configs/connections/warehouse.yml")
WAREHOUSE_TYPES = ("duckdb", "snowflake", "bigquery", "postgres")
NO_TARGET = "No target warehouse chosen. Set `type` in configs/connections/warehouse.yml."


def _resolve_env(value):
    """Replace `env:NAME` with the value of environment variable NAME."""
    if isinstance(value, str) and value.startswith("env:"):
        name = value.removeprefix("env:")
        if name not in os.environ:
            raise PydanticCustomError(
                "env_missing", "environment variable {name} is not set", {"name": name}
            )
        return os.environ[name]
    return value


EnvStr = Annotated[str, BeforeValidator(_resolve_env)]
EnvSecret = Annotated[SecretStr, BeforeValidator(_resolve_env)]


class _Connection(BaseModel):
    """Shared by every warehouse: unknown keys are errors, and null means "not set"."""

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _null_means_unset(cls, data):
        if isinstance(data, dict):
            return {key: value for key, value in data.items() if value is not None}
        return data


class DuckDBConnection(_Connection):
    type: Literal["duckdb"]
    database: EnvStr  # path to the .duckdb file
    schema_name: EnvStr = Field("main", alias="schema")


class SnowflakeConnection(_Connection):
    type: Literal["snowflake"]
    database: EnvStr
    schema_name: EnvStr = Field(alias="schema")
    credentials: EnvSecret


class BigQueryConnection(_Connection):
    type: Literal["bigquery"]
    database: EnvStr  # GCP project
    schema_name: EnvStr = Field(alias="schema")  # BigQuery dataset
    credentials: EnvSecret


class PostgresConnection(_Connection):
    type: Literal["postgres"]
    database: EnvStr
    schema_name: EnvStr = Field(alias="schema")
    credentials: EnvSecret


Connection = Annotated[
    Union[DuckDBConnection, SnowflakeConnection, BigQueryConnection, PostgresConnection],
    Field(discriminator="type"),
]


def _require_type(value):
    """Reject a missing, null, or unknown `type` before the per-warehouse checks run."""
    if isinstance(value, dict):
        kind = value.get("type")
        if kind is None:
            raise PydanticCustomError("no_target", NO_TARGET)
        if kind not in WAREHOUSE_TYPES:
            raise PydanticCustomError(
                "unknown_type",
                "type must be one of {allowed}; got '{kind}'",
                {"allowed": ", ".join(WAREHOUSE_TYPES), "kind": str(kind)},
            )
    return value


class Connections(BaseModel):
    """Every connection the harness knows about. Only `target` exists today."""

    model_config = ConfigDict(extra="forbid")
    target: Annotated[Connection, BeforeValidator(_require_type)]


class _WarehouseFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connections: Connections


def _describe(error: dict) -> str:
    """Turn one pydantic error into `path.to.key: message` without echoing the value."""
    tag = next((part for part in error["loc"] if part in WAREHOUSE_TYPES), None)
    where = ".".join(str(part) for part in error["loc"] if part != tag)
    if error["type"] == "missing":
        message = f"required when type is {tag}" if tag else "required"
    elif error["type"] == "extra_forbidden":
        known = tag and error["loc"][-1] in ("database", "schema", "credentials")
        message = f"not used when type is {tag}" if known else "unknown key"
    else:
        message = error["msg"]
    return f"{where}: {message}"


def load_connections(path: Path = DEFAULT_PATH) -> Connections:
    """Read the connection config, resolve env: values, and check every rule.

    Raises ConfigError listing every problem found in the file.
    """
    raw = read_yaml(path, "a top-level `connections:` block")
    try:
        return _WarehouseFile.model_validate(raw).connections
    except ValidationError as err:
        raise ConfigError(path, [_describe(e) for e in err.errors()]) from None
