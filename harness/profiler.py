"""Profile a CSV: compute facts about every column and write them as JSON.

`harness profile data/raw/orders.csv` writes profiles/orders.profile.json.

DuckDB reads the CSV directly, so no warehouse needs to be configured. The profiler
records facts only. It suggests no rules and calls no LLM.

For the file: row_count, source (the path given), profiled_at (local time).

For each column, and how it is computed:
- inferred_type    The type DuckDB's CSV reader picks after scanning every row, mapped to
                   integer | decimal | string | date | timestamp | boolean.
- null_count       Rows where the value is empty.
- null_pct         null_count / row_count * 100, rounded to 2 decimals.
- distinct_count   Number of different non-empty values.
- min, max         Smallest and largest value. Numeric, date and timestamp columns only.
- negative_count   Rows with a value below zero. Numeric columns only.
- sample_values    The first 5 different non-empty values, in file order.
- distinct_values  Every different non-empty value, sorted. Only when distinct_count <= 20.
- date_formats     String columns only. When every non-empty value parses as a date in one
                   of the formats in DATE_FORMATS, how many values match each format.
                   Each value counts once, under the first format (in DATE_FORMATS order)
                   that parses it, so an ambiguous 03/04/2026 counts as MM/DD/YYYY.
                   Empty ({}) when some value parses in none of them.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb

from harness.config.pipeline import DATE_FORMATS

PROFILES_DIR = Path("profiles")
_INTEGER_TYPES = {"TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT",
                  "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT", "UHUGEINT"}


def _inferred_type(duckdb_type: str) -> str:
    kind = duckdb_type.upper()
    if kind in _INTEGER_TYPES:
        return "integer"
    if kind in ("FLOAT", "DOUBLE", "REAL") or kind.startswith("DECIMAL"):
        return "decimal"
    if kind == "DATE":
        return "date"
    if kind.startswith("TIMESTAMP"):
        return "timestamp"
    if kind == "BOOLEAN":
        return "boolean"
    return "string"


def _plain(value):
    """Make a DuckDB value JSON-friendly."""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _date_formats(con, column: str) -> dict[str, int]:
    cases = " ".join(
        f"when try_strptime({column}, '{pattern}') is not null then '{name}'"
        for name, pattern in DATE_FORMATS.items()
    )
    rows = con.execute(
        f"select case {cases} end as fmt, count(*) from data where {column} is not null group by fmt"
    ).fetchall()
    counts = dict(rows)
    if not counts or None in counts:
        return {}
    return {name: counts[name] for name in DATE_FORMATS if name in counts}


def profile_csv(csv_path: Path) -> dict:
    """Compute the profile for one CSV file and return it as a dict."""
    csv_path = Path(csv_path)
    if not csv_path.is_file():
        raise FileNotFoundError(f"{csv_path.as_posix()}: file not found")
    con = duckdb.connect()
    literal = csv_path.as_posix().replace("'", "''")
    con.execute(f"create table data as select * from read_csv('{literal}', header = true, sample_size = -1)")
    row_count = con.execute("select count(*) from data").fetchone()[0]

    columns = []
    for name, duckdb_type, *_ in con.execute("describe data").fetchall():
        col = '"' + name.replace('"', '""') + '"'
        kind = _inferred_type(duckdb_type)
        null_count, distinct_count = con.execute(
            f"select count(*) - count({col}), count(distinct {col}) from data"
        ).fetchone()
        facts = {
            "name": name,
            "inferred_type": kind,
            "null_count": null_count,
            "null_pct": round(null_count / row_count * 100, 2) if row_count else 0.0,
            "distinct_count": distinct_count,
        }
        if kind in ("integer", "decimal", "date", "timestamp"):
            low, high = con.execute(f"select min({col}), max({col}) from data").fetchone()
            facts["min"], facts["max"] = _plain(low), _plain(high)
        if kind in ("integer", "decimal"):
            facts["negative_count"] = con.execute(f"select count(*) from data where {col} < 0").fetchone()[0]
        facts["sample_values"] = [
            _plain(v) for (v,) in con.execute(
                f"select {col} from data where {col} is not null group by {col} order by min(rowid) limit 5"
            ).fetchall()
        ]
        if distinct_count <= 20:
            facts["distinct_values"] = [
                _plain(v) for (v,) in con.execute(
                    f"select distinct {col} from data where {col} is not null order by {col}"
                ).fetchall()
            ]
        if kind == "string":
            facts["date_formats"] = _date_formats(con, col)
        columns.append(facts)

    return {
        "source": csv_path.as_posix(),
        "row_count": row_count,
        "profiled_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "columns": columns,
    }


def write_profile(csv_path: Path) -> Path:
    """Profile a CSV and write profiles/<name>.profile.json. Returns the path written."""
    profile = profile_csv(csv_path)
    out = PROFILES_DIR / f"{Path(csv_path).stem}.profile.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    return out
