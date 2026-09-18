"""End-to-end test: the sample CSV through profile, compile and run, with a DuckDB target.

The test builds a throwaway project in a temporary folder: the sample CSV, the dbt
project, a duckdb warehouse config, and a pipeline config the test itself writes and
approves. The repo's own configs are never touched, and its orders.yml stays a draft.

Every expectation is recomputed from the CSV in plain Python, independently of DuckDB
and dbt, so the harness is checked against the data rather than against itself.
Freshness is set to `warn` so the test keeps passing as the sample data ages.
"""

import csv
import json
import shutil
from datetime import datetime
from pathlib import Path

import duckdb
import pytest

from harness.cli import main
from harness.compiler.dbt import CompileError, compile_pipeline

REPO = Path(__file__).resolve().parents[1]
ACCEPTED_STATUSES = ["placed", "shipped", "delivered", "cancelled", "returned"]

PIPELINE = f"""\
pipeline: orders
status: draft
approved_by: null
source: data/raw/orders.csv
target: silver.orders
columns:
  - {{name: order_id, type: integer, tests: [not_null, unique]}}
  - {{name: customer_id, type: string, tests: [not_null]}}
  - {{name: amount, type: "decimal(18,2)", tests: [{{accepted_range: {{min: 0}}}}]}}
  - {{name: status, type: string, tests: [{{accepted_values: {{values: {ACCEPTED_STATUSES}}}}}]}}
  - {{name: order_date, type: date, tests: [not_null]}}
  - {{name: updated_at, type: timestamp}}
transformations:
  - {{type: rename, mapping: {{cust_id: customer_id}}}}
  - {{type: parse_date, column: order_date, formats: [YYYY-MM-DD, MM/DD/YYYY]}}
  - {{type: filter, expr: "status <> 'test'"}}
  - {{type: dedupe, keys: [order_id], order_by: "updated_at desc"}}
quality:
  - {{rule: freshness, column: updated_at, max_age: 24h, severity: warn}}
  - {{rule: row_count_change, max_pct: 30}}
on_failure: quarantine
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / "data/raw").mkdir(parents=True)
    shutil.copy(REPO / "data/raw/orders.csv", tmp_path / "data/raw/orders.csv")
    shutil.copytree(REPO / "dbt_project", tmp_path / "dbt_project",
                    ignore=shutil.ignore_patterns("target", "logs", "generated"))
    (tmp_path / "configs/connections").mkdir(parents=True)
    (tmp_path / "configs/connections/warehouse.yml").write_text(
        "connections:\n  target:\n    type: duckdb\n    database: warehouse.duckdb\n"
    )
    (tmp_path / "configs/pipelines").mkdir(parents=True)
    (tmp_path / "configs/pipelines/orders.yml").write_text(PIPELINE)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _parse_date(text):
    for pattern in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            pass
    return None


def _expected_quarantine(rows):
    """{order_id: failed rules} recomputed in Python: rename, parse, filter, dedupe, then tests."""
    kept = [r for r in rows if r["status"] not in ("test", "")]  # filter: status <> 'test' (NULL drops too)
    latest = {}
    for row in kept:  # dedupe: keep the latest updated_at per order_id
        if row["order_id"] not in latest or row["updated_at"] > latest[row["order_id"]]["updated_at"]:
            latest[row["order_id"]] = row
    expected = {}
    for order_id, row in latest.items():
        failed = set()
        if row["cust_id"] == "":
            failed.add("customer_id:not_null")
        if float(row["amount"]) < 0:
            failed.add("amount:accepted_range")
        if row["status"] not in ACCEPTED_STATUSES:
            failed.add("status:accepted_values")
        if _parse_date(row["order_date"]) is None:
            failed.add("order_date:not_null")
        if failed:
            expected[int(order_id)] = failed
    return expected


def test_sample_csv_end_to_end(project):
    with open("data/raw/orders.csv", newline="") as handle:
        rows = list(csv.DictReader(handle))

    # The profile finds the planted duplicates, empty values and negatives.
    assert main(["profile", "data/raw/orders.csv"]) == 0
    profile = json.loads(Path("profiles/orders.profile.json").read_text())
    columns = {c["name"]: c for c in profile["columns"]}
    duplicates = len(rows) - len({r["order_id"] for r in rows})
    empty_customers = sum(r["cust_id"] == "" for r in rows)
    negatives = sum(float(r["amount"]) < 0 for r in rows)
    assert duplicates > 0 and empty_customers > 0 and negatives > 0
    assert profile["row_count"] == len(rows)
    assert columns["order_id"]["distinct_count"] == len(rows) - duplicates
    assert columns["cust_id"]["null_count"] == empty_customers
    assert columns["amount"]["negative_count"] == negatives

    # A draft does not compile.
    with pytest.raises(CompileError, match=r"orders\.yml is still a draft\. Review the REVIEW comments, "
                                           r"then set status: approved\."):
        compile_pipeline("orders")

    # Approve it (in this temporary project only) and run it.
    config = Path("configs/pipelines/orders.yml")
    config.write_text(PIPELINE.replace("status: draft", "status: approved")
                              .replace("approved_by: null", "approved_by: end-to-end test"))
    assert main(["run", "orders"]) == 0

    run_dir = next(Path("runs").glob("*_orders"))
    record = json.loads((run_dir / "run.json").read_text())
    counts = record["rows"]
    removed = sum(step["removed"] for step in counts["transformations"])
    assert record["target_written"] is True
    assert counts["read"] == len(rows)
    assert counts["loaded"] == counts["read"] - removed - counts["quarantined"]
    # Default settings: dbt ran in this process and still holds the file open with them.
    with duckdb.connect("warehouse.duckdb") as con:
        assert con.execute("select count(*) from silver.orders").fetchone()[0] == counts["loaded"]

    # Quarantine holds exactly the rows that broke a rule, with exactly the rules they broke.
    with open(run_dir / "quarantine.csv", newline="") as handle:
        quarantined = {int(r["order_id"]): set(r["_failed_rules"].split(", ")) for r in csv.DictReader(handle)}
    assert quarantined == _expected_quarantine(rows)
    assert counts["quarantined"] == len(quarantined)
