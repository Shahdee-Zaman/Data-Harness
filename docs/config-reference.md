# Pipeline config reference

A pipeline config is one YAML file in `configs/pipelines/`, named after the pipeline
(`configs/pipelines/orders.yml` for the `orders` pipeline). It says which CSV to read,
what to do to it, which checks every row must pass, and which table to load.

Run `harness validate` after every edit. It reports every problem in every file, not
just the first, and anything not listed on this page is rejected.

## Reading YAML in two minutes

- `key: value` sets a value. Indentation (spaces, never tabs) shows what belongs to what.
- A line starting with `- ` is one item in a list.
- `{a: 1, b: 2}` is a mapping written on one line; `[x, y]` is a list written on one line.
- `null` (or leaving the value empty) means "no value".
- `#` starts a comment; everything after it on that line is ignored.
- Quote text that contains `:` `#` `{` `[` or a leading `'`, e.g. `expr: "status <> 'test'"`.

## A complete example

```yaml
pipeline: orders
status: draft
approved_by: null
source: data/raw/orders.csv
target: silver.orders
columns:
  - name: order_id
    type: integer
    tests: [not_null, unique]
  - name: customer_id
    type: string
    tests:
      - not_null: {severity: warn}
  - name: amount
    type: decimal(12,2)
    tests:
      - accepted_range: {min: 0}
  - name: status
    type: string
    tests:
      - accepted_values: {values: [placed, shipped, delivered, cancelled, returned]}
  - {name: order_date, type: date}
  - {name: updated_at, type: timestamp}
transformations:
  - {type: rename, mapping: {cust_id: customer_id}}
  - {type: parse_date, column: order_date, formats: [YYYY-MM-DD, MM/DD/YYYY]}
  - {type: filter, expr: "status <> 'test'"}
  - {type: dedupe, keys: [order_id], order_by: "updated_at desc"}
quality:
  - {rule: freshness, column: updated_at, max_age: 24h}
  - {rule: row_count_change, max_pct: 30}
on_failure: quarantine
```

## Top-level keys

| Key | Required? | Allowed values | What it means |
|---|---|---|---|
| `pipeline` | Required | Letters, digits and `_`; must equal the filename without `.yml` | The pipeline's name, used in every command (`harness run orders`). |
| `status` | Required | `draft` or `approved` | Only an approved pipeline can be compiled or run; only a person sets `approved`. |
| `approved_by` | Required when `status` is `approved` | Any text, or `null` | Who reviewed the draft and approved it. |
| `source` | Required | A path to a CSV file, relative to the project root | The file the pipeline reads. |
| `target` | Required | `<schema>.<table>`, each part letters, digits and `_` | The table that receives the clean rows. |
| `columns` | Required, at least one | A list of column entries (below) | Exactly the columns the target table will have, in this order. |
| `transformations` | Optional | A list of transformation entries (below) | Steps applied to the rows, in order, before any test runs. |
| `quality` | Optional | A list of quality rule entries (below) | Checks on the whole table after it is built. |
| `on_failure` | Required | `quarantine` | Rows that fail a test go to a quarantine table instead of the target. |

## Column entries

| Key | Required? | Allowed values | What it means |
|---|---|---|---|
| `name` | Required | Letters, digits and `_`; unique within `columns` | The column's name in the final table, after any `rename`. |
| `type` | Required | `integer`, `decimal(p,s)`, `string`, `date`, `timestamp`, `boolean` | The column's type in the final table; `decimal(12,2)` means 12 digits, 2 after the point. |
| `tests` | Optional | A list of the four tests below | Checks every row must pass. |

## Column tests

Write a test either bare (`- not_null`) or with settings (`- not_null: {severity: warn}`).

| Test | Settings | What it checks |
|---|---|---|
| `not_null` | `severity` | The value is present. |
| `unique` | `severity` | No other row has the same value (empty values are ignored). |
| `accepted_values` | `values` (required list), `severity` | The value is one of `values` (empty values pass; use `not_null` to catch them). |
| `accepted_range` | `min`, `max` (at least one), `severity` | The value is at least `min` and at most `max` (empty values pass). |

| Setting | Required? | Allowed values | What it means |
|---|---|---|---|
| `severity` | Optional, default `error` | `error` or `warn` | `error`: a failing row is quarantined. `warn`: the row is loaded and the failure is reported. |

## Transformations

They run in the order written; each one works on the output of the one before.

| `type` | Other keys | What it does |
|---|---|---|
| `rename` | `mapping`: `{old_name: new_name, ...}` | Renames columns; later steps and `columns` use the new names. |
| `parse_date` | `column`; `formats`: list of `YYYY-MM-DD`, `YYYY/MM/DD`, `MM/DD/YYYY`, `DD/MM/YYYY` | Turns text into a date, trying each format in order; a value no format fits becomes empty. |
| `filter` | `expr`: a SQL condition | Keeps only rows where `expr` is true, e.g. `"status <> 'test'"`. |
| `dedupe` | `keys`: list of columns; `order_by`: SQL order, e.g. `"updated_at desc"` | Keeps the first row of each group of rows sharing `keys`, after sorting by `order_by`. |

Every column a transformation names must exist at that step: before a `rename`, use the
old name; after it, the new one.

## Quality rules

| `rule` | Other keys | What it checks |
|---|---|---|
| `freshness` | `column`; `max_age`: a number then `h` or `d` (`24h`, `2d`); `severity` | The newest value in `column` is no older than `max_age`. |
| `row_count_change` | `max_pct`: a number, 0 or more; `severity` | The loaded row count is within `max_pct` percent of the previous successful run. |

`severity` works as for tests: an `error` rule that fails stops the load (the target
table is not written); a `warn` rule that fails is reported and the load goes ahead.
