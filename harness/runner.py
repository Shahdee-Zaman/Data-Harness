"""Run a pipeline end to end and record what happened.

`harness run orders` does, in order:
1. validate   the warehouse config and configs/pipelines/orders.yml (it must be approved)
2. compile    write dbt_project/models/generated/orders*.sql and orders.yml
3. dbt build  build orders and orders_quarantine into the staging schema, then run the
              dbt tests on orders
4. checks     freshness and row_count_change as SQL against the built table; if no
              error-severity check failed, copy the built table to the pipeline's target
5. record     write runs/<YYYY-MM-DD>_orders/ with report.md, quarantine.csv and run.json

Exit 0 when the run passed, with or without warnings; exit 1 when an error-severity check
failed, in which case the target table is not written. No LLM runs at any step.

Severity decides what a failed check does. For a column test: `error` quarantines the row,
reported as WARN with the number of rows quarantined; `warn` loads the row and reports it.
For a quality rule: `error` stops the load (FAIL), `warn` reports it (WARN).
"""

from __future__ import annotations

import csv
import json
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from pathlib import Path

import duckdb
import yaml

from harness.compiler.dbt import CompileError, load_approved, publish_sql, step_counts_sql, write_generated
from harness.config.connection import load_connections
from harness.config.pipeline import Freshness, PipelineConfig

RUNS_DIR = Path("runs")
DBT_PROJECT = Path("dbt_project")
DBT_FLAGS = ["--quiet", "--no-send-anonymous-usage-stats"]


@dataclass
class Check:
    result: str          # PASS | WARN | FAIL
    check: str           # e.g. "not_null on customer_id"
    severity: str
    rows_affected: int | None
    detail: str


# ---------------------------------------------------------------- dbt

def _dbt_profile(target) -> dict:
    """The dbt profile for the target. Only duckdb has a dialect, so only duckdb gets here."""
    database = Path(target.database).resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    output = {"type": "duckdb", "path": database.as_posix(), "schema": target.schema_name, "threads": 1}
    return {"harness": {"target": "harness", "outputs": {"harness": output}}}


def _dbt_build(name: str, target) -> tuple[dict, dict, list[str]]:
    """Run dbt build. Returns (models, tests, errors); models map name -> relation."""
    from dbt.cli.main import dbtRunner  # imported here: dbt is slow to import

    models, tests, errors = {}, {}, []
    with tempfile.TemporaryDirectory() as profiles_dir:
        Path(profiles_dir, "profiles.yml").write_text(yaml.safe_dump(_dbt_profile(target)))
        common = ["--project-dir", str(DBT_PROJECT), "--profiles-dir", profiles_dir, *DBT_FLAGS]
        if not (DBT_PROJECT / "dbt_packages" / "dbt_utils").exists():
            result = dbtRunner().invoke(["deps", *common])
            if not result.success:
                return models, tests, [f"dbt deps failed: {result.exception}"]
        result = dbtRunner().invoke(["build", "--select", name, f"{name}_quarantine", *common])

    if result.result is None:
        return models, tests, [f"dbt build failed: {result.exception}"]
    for outcome in result.result.results:
        node, status = outcome.node, str(outcome.status)
        if node.resource_type == "model":
            models[node.name] = node.relation_name
            if status != "success":
                errors.append(f"model {node.name}: {status}: {outcome.message}")
        elif node.resource_type == "test":
            tests[(node.column_name, node.test_metadata.name)] = (status, outcome.failures, outcome.message)
    for model in (name, f"{name}_quarantine"):
        if model not in models and not errors:
            errors.append(f"dbt did not build {model}")
    return models, tests, errors


# ---------------------------------------------------------------- checks

def _column_checks(config: PipelineConfig, quarantined: Counter, dbt_tests: dict) -> list[Check]:
    checks = []
    for column in config.columns:
        for test in column.tests:
            name = f"{test.test} on {column.name}"
            status, failures, message = dbt_tests.get((column.name, test.test), (None, None, None))
            if test.severity == "error":
                rows = quarantined[f"{column.name}:{test.test}"]
                if status in ("fail", "error"):
                    checks.append(Check("FAIL", name, "error", rows, f"dbt test on the clean table: {message}"))
                elif rows:
                    checks.append(Check("WARN", name, "error", rows, f"{rows} row(s) quarantined"))
                else:
                    checks.append(Check("PASS", name, "error", 0, ""))
            elif status == "warn":
                checks.append(Check("WARN", name, "warn", failures, "loaded; failures counted by dbt"))
            elif status == "pass":
                checks.append(Check("PASS", name, "warn", 0, ""))
            else:
                checks.append(Check("FAIL", name, "warn", None, f"dbt test did not complete: {status} {message or ''}"))
    return checks


def _freshness(con, relation: str, rule: Freshness) -> Check:
    newest = con.execute(f"select max({rule.column}) from {relation}").fetchone()[0]
    failed = "FAIL" if rule.severity == "error" else "WARN"
    name = f"freshness on {rule.column}"
    if newest is None:
        return Check(failed, name, rule.severity, None, "no rows to check")
    if not isinstance(newest, date):
        return Check(failed, name, rule.severity, None, "column is not a date or timestamp")
    if not isinstance(newest, datetime):
        newest = datetime.combine(newest, time())
    age_hours = (datetime.now(newest.tzinfo) - newest).total_seconds() / 3600
    detail = f"newest {newest:%Y-%m-%d %H:%M}, {age_hours:.1f}h old (max {rule.max_age})"
    return Check("PASS" if age_hours <= rule.max_age_hours else failed, name, rule.severity, None, detail)


def _row_count_change(rule, loaded: int, previous: dict | None) -> Check:
    if previous is None:
        return Check("PASS", "row_count_change", rule.severity, None, "no previous successful run to compare")
    before = previous["loaded"]
    change = (loaded - before) / before * 100 if before else (0.0 if loaded == 0 else float("inf"))
    detail = f"{loaded} rows vs {before} on {previous['started_at'][:10]} ({change:+.1f}%, max {rule.max_pct:g}%)"
    ok = abs(change) <= rule.max_pct
    return Check("PASS" if ok else ("FAIL" if rule.severity == "error" else "WARN"),
                 "row_count_change", rule.severity, abs(loaded - before), detail)


def _previous_run(name: str) -> dict | None:
    """{started_at, loaded} of the latest run that wrote the target table.

    A failed run records the baseline it compared against, so a failure that overwrites
    today's folder does not lose the last successful count.
    """
    for path in sorted(RUNS_DIR.glob(f"????-??-??_{name}/run.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("target_written"):
            return {"started_at": data["started_at"], "loaded": data["rows"]["loaded"]}
        if data.get("previous_success"):
            return data["previous_success"]
    return None


# ---------------------------------------------------------------- report

def _overall(checks: list[Check], errors: list[str]) -> str:
    if errors or any(c.result == "FAIL" for c in checks):
        return "FAILED"
    return "PASSED WITH WARNINGS" if any(c.result == "WARN" for c in checks) else "PASSED"


def _report(record: dict, errors: list[str]) -> str:
    rows = record["rows"]
    lines = [
        f"# Run report: {record['pipeline']}",
        "",
        "| | |",
        "|---|---|",
        f"| Pipeline | {record['pipeline']} |",
        f"| Started | {record['started_at']} |",
        f"| Result | **{record['status']}** |",
        f"| Target | {record['target']} ({'written' if record['target_written'] else 'not written'}) |",
        "",
    ]
    if errors:
        lines += ["## Errors", "", *[f"- {e}" for e in errors], ""]
    if rows:
        lines += ["## Row counts", "", "| Step | Rows after | Removed |", "|---|---:|---:|",
                  f"| read {record['source']} | {rows['read']} | |"]
        lines += [f"| {s['step']} | {s['rows_after']} | {s['removed']} |" for s in rows["transformations"]]
        lines.append(f"| quarantined (failed an error test) | {rows['clean']} | {rows['quarantined']} |")
        if record["target_written"]:
            lines.append(f"| **loaded into {record['target']}** | **{rows['loaded']}** | |")
        else:
            lines.append(f"| **not loaded**: an error-severity check failed | {rows['clean']} held back | |")
        removed = " ".join(f"- {s['removed']} {s['step']}" for s in rows["transformations"])
        lines += ["", f"{rows['read']} read {removed} - {rows['quarantined']} quarantined = {rows['clean']} clean rows", ""]
    if record["checks"]:
        lines += ["## Checks", "", "| Result | Check | Severity | Rows affected | Detail |", "|---|---|---|---:|---|"]
        for c in record["checks"]:
            affected = "-" if c["rows_affected"] is None else c["rows_affected"]
            lines.append(f"| {c['result']} | {c['check']} | {c['severity']} | {affected} | {c['detail']} |")
        lines.append("")
    if rows:
        lines.append(f"Quarantined rows, with `_failed_rules`: quarantine.csv ({rows['quarantined']} rows).")
    return "\n".join(lines) + "\n"


def _write_record(run_dir: Path, record: dict, errors: list[str]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    (run_dir / "report.md").write_text(_report(record, errors), encoding="utf-8")


# ---------------------------------------------------------------- the run

def run_pipeline(name: str) -> int:
    started = datetime.now().astimezone()
    run_dir = RUNS_DIR / f"{started:%Y-%m-%d}_{name}"
    previous = _previous_run(name)  # read before today's folder is overwritten

    # 1-2. validate and compile
    try:
        config, dialect_file = load_approved(name)
    except CompileError as err:
        for problem in err.problems:
            print(problem)
        return 1
    write_generated(config, dialect_file)
    target = load_connections().target
    record = {"pipeline": name, "started_at": started.isoformat(timespec="seconds"), "status": "FAILED",
              "source": config.source, "target": config.target, "target_written": False,
              "previous_success": previous, "rows": None, "checks": []}

    # 3. dbt build
    print(f"Building {name} with dbt ...")
    models, dbt_tests, errors = _dbt_build(name, target)
    if errors:
        _write_record(run_dir, record, errors)
        print("\n".join(errors))
        print(f"FAILED. Report: {(run_dir / 'report.md').as_posix()}")
        return 1

    # 4. checks against the built tables
    counts = duckdb.connect().execute(step_counts_sql(config, dialect_file)).fetchall()
    con = duckdb.connect(str(Path(target.database).resolve()))
    try:
        cursor = con.execute(f"select * from {models[f'{name}_quarantine']}")
        header = [d[0] for d in cursor.description]
        quarantine_rows = cursor.fetchall()
        clean = con.execute(f"select count(*) from {models[name]}").fetchone()[0]
        failed_rules = Counter(
            label for row in quarantine_rows for label in row[header.index("_failed_rules")].split(", ")
        )

        checks = _column_checks(config, failed_rules, dbt_tests)
        for rule in config.quality:
            if isinstance(rule, Freshness):
                checks.append(_freshness(con, models[name], rule))
            else:
                checks.append(_row_count_change(rule, clean, previous))

        record["status"] = _overall(checks, [])
        if record["status"] != "FAILED":
            con.execute(publish_sql(dialect_file, models[name], config.target_schema, config.target_table))
            record["target_written"] = True
    finally:
        con.close()

    # 5. record
    steps = [{"step": step, "rows_after": rows, "removed": before - rows}
             for (_, before), (step, rows) in zip(counts, counts[1:])]
    record["rows"] = {"read": counts[0][1], "transformations": steps, "quarantined": len(quarantine_rows),
                      "clean": clean, "loaded": clean if record["target_written"] else 0}
    record["checks"] = [asdict(c) for c in checks]
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / "quarantine.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(quarantine_rows)
    _write_record(run_dir, record, [])

    rows = record["rows"]
    print(f"{record['status']}: read {rows['read']}, quarantined {rows['quarantined']}, "
          f"{'loaded' if record['target_written'] else 'NOT loaded'} {rows['clean']} into {config.target}")
    print(f"Report: {(run_dir / 'report.md').as_posix()}")
    return 1 if record["status"] == "FAILED" else 0
