"""Command-line entry point: `harness <command>`.

Commands:
  validate   Load every config file, print every problem found, and exit 1 if
             there were any (0 if everything is valid).
"""

from __future__ import annotations

import argparse
import sys

from harness.config.connection import DEFAULT_PATH, ConfigError, load_connections


def validate(args: argparse.Namespace) -> int:
    """Check every config and report all problems, not just the first."""
    checks = [(DEFAULT_PATH, load_connections)]
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harness", description="Data Harness command line.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate", help="check every config file and report all errors").set_defaults(
        handler=validate
    )
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
