# Data Harness

Turns a CSV into a checked, loaded warehouse table. The harness profiles the data,
drafts a pipeline config from the facts it found, waits for a person to approve that
config, compiles it to dbt SQL, and runs it.

## Setup

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[test]"
```

On macOS or Linux, use `.venv/bin/` in place of `.venv/Scripts/`. Activate the
environment, or call `.venv/Scripts/harness` directly.

Then choose a warehouse in `configs/connections/warehouse.yml`. Nothing compiles or runs
until you do. For a local DuckDB file:

```yaml
connections:
  target:
    type: duckdb
    database: warehouse.duckdb
```

## The five commands

Run them from the project root.

| Command | What it does |
|---|---|
| `harness profile data/raw/orders.csv` | Reads the CSV with DuckDB and writes facts about every column to `profiles/orders.profile.json`. |
| `/new-pipeline data/raw/orders.csv` | In Claude Code: profiles the CSV, drafts `configs/pipelines/orders.yml` from the profile using fixed rules, validates it, and lists the `# REVIEW:` questions for you to answer. The draft stays `status: draft`. |
| `harness validate` | Checks every config file and prints every error, not just the first; exits 1 if there are any. |
| `harness compile orders` | Turns an approved config into dbt SQL in `dbt_project/models/generated/`. Offline: it never connects to a warehouse or reads data. Refuses a draft. |
| `harness run orders` | Validates, compiles, builds with dbt, runs the checks, loads the target table if no error-severity check failed, and writes `runs/<date>_orders/` (`report.md`, `quarantine.csv`, `run.json`). |

The config vocabulary is documented in [docs/config-reference.md](docs/config-reference.md).

## How it fits together

`harness profile` produces facts: counts, ranges, samples and date formats, with no
opinions attached. The `/new-pipeline` skill drafts a config from those facts by fixed
rules, citing the profile number behind every test and turning every guess into a
`# REVIEW:` question. You answer the questions, edit the file, and approve it by setting
`status: approved` and `approved_by`; nothing approves a config for you. `harness compile`
turns the approved config into SQL: one CTE per transformation, a tagging step that marks
each row with the tests it failed, a clean model and a quarantine model. `harness run`
executes that SQL with dbt, checks the result, and loads it. **No LLM runs during
`harness run`**: the only model involved is the one drafting the config, before you
approve it, and everything after approval is deterministic SQL.

The `/brd` command, which writes business requirements documents, is separate from the
pipeline: pipeline configs come from profiling real data, never from a BRD.

## Tests

```bash
.venv/Scripts/python -m pytest
```

One end-to-end test runs the sample CSV through profile, compile and run in a temporary
folder against a DuckDB target. The first run downloads the `dbt_utils` package.
