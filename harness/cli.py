"""Command-line entry point: `harness <command>`.

Commands:
  profile <csv>        Compute facts about a CSV and write profiles/<name>.profile.json.
  validate             Load every config file, print every problem found, and exit 1 if
                       there were any (0 if everything is valid).
  compile <pipeline>   Turn an approved pipeline config into dbt SQL. Offline: no warehouse,
                       no data.
  run <pipeline>       Validate, compile, build with dbt, check, and write runs/<date>_<pipeline>/.

Run every command from the project root; all paths are relative to it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from harness.config import ConfigError
from harness.config.connection import DEFAULT_PATH, load_connections
from harness.config.pipeline import PIPELINES_DIR, load_pipeline


def profile(args: argparse.Namespace) -> int:
    from harness.profiler import write_profile

    try:
        out = write_profile(Path(args.csv))
    except FileNotFoundError as err:
        print(err)
        return 1
    print(f"Wrote {out.as_posix()}")
    return 0


def validate(args: argparse.Namespace) -> int:
    """Check every config and report all problems, not just the first."""
    checks = [(DEFAULT_PATH, load_connections)]
    checks += [(path, load_pipeline) for path in sorted(PIPELINES_DIR.glob("*.yml"))]
    problem_count = 0
    for path, load in checks:
        try:
            load(path)
        except ConfigError as err:
            problem_count += len(err.problems)
            print(f"{path.as_posix()}: FAILED")
            for problem in err.problems:
                print(f"  - {problem}")
        else:
            print(f"{path.as_posix()}: OK")

    if problem_count:
        print(f"\n{problem_count} error(s) found.")
        return 1
    print("\nAll configs valid.")
    return 0


def compile_(args: argparse.Namespace) -> int:
    from harness.compiler.dbt import CompileError, compile_pipeline

    try:
        written = compile_pipeline(args.pipeline)
    except CompileError as err:
        for problem in err.problems:
            print(problem)
        return 1
    for path in written:
        print(f"Wrote {path.as_posix()}")
    return 0


def run(args: argparse.Namespace) -> int:
    from harness.runner import run_pipeline

    return run_pipeline(args.pipeline)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harness", description="Data Harness command line.")
    commands = parser.add_subparsers(dest="command", required=True)

    command = commands.add_parser("profile", help="compute facts about a CSV file")
    command.add_argument("csv", help="path to the CSV, e.g. data/raw/orders.csv")
    command.set_defaults(handler=profile)

    commands.add_parser("validate", help="check every config file and report all errors").set_defaults(
        handler=validate
    )

    command = commands.add_parser("compile", help="write dbt SQL for an approved pipeline")
    command.add_argument("pipeline", help="pipeline name, e.g. orders")
    command.set_defaults(handler=compile_)

    command = commands.add_parser("run", help="build, check and load a pipeline")
    command.add_argument("pipeline", help="pipeline name, e.g. orders")
    command.set_defaults(handler=run)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
