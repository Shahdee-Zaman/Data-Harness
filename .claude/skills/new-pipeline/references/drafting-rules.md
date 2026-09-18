# Drafting rules

Fixed rules for turning a profile into a draft pipeline config. Apply them to every
column, in the order the columns appear in the profile. Nothing outside these rules may
be added.

## 1. Rules table

| Profile finding | Action |
|---|---|
| `null_count` is 0 | add `not_null` |
| `null_count` > 0 and `null_pct` < 5 | add `not_null` + REVIEW: should rows with no value be rejected (quarantined) or allowed? |
| `null_pct` >= 5 | no `not_null`; add REVIEW on the column: is an empty value allowed here? |
| `distinct_count` = `row_count` | add `unique` |
| `distinct_count` < `row_count` and `row_count` − `distinct_count` <= 1% of `row_count` | add `unique` + a `dedupe` transformation on that column; the comment gives both counts |
| `inferred_type` string and `distinct_count` <= 20 | add `accepted_values` with the `distinct_values`, excluding values that look like test data (section 4) |
| `inferred_type` integer or decimal, `negative_count` is 0 | add `accepted_range: {min: 0}` |
| `inferred_type` integer or decimal, `negative_count` > 0 | add `accepted_range: {min: 0}` + REVIEW: are negative values legitimate? |
| `date_formats` has more than one entry | add `parse_date` with those formats, in the order listed in the profile |
| column name contains an abbreviation from section 5 | add `rename` to the clearer name |
| a column has `inferred_type` timestamp and a name containing `updated` or `modified` | add `freshness` on it with `max_age: 24h` |
| always | add `row_count_change: {max_pct: 30}`, `on_failure: quarantine`, `status: draft` |

Rows that add nothing (for example a string column with 300 distinct values) add nothing:
do not substitute another test.

## 2. File skeleton

```yaml
pipeline: <name>              # the CSV file name without extension
status: draft
approved_by: null
source: <csv path as given>
target: silver.<name>         # convention: every draft targets silver.<name>
columns: [...]
transformations: [...]        # omit the key if no rule added one
quality: [...]
on_failure: quarantine
```

`columns` lists every profile column, in profile order, under its final name (after any
`rename`). Tests on a column appear in this order: `not_null`, `unique`, `accepted_values`,
`accepted_range`. Transformations appear in this order: `rename`, `parse_date`, `dedupe`.
Later steps and `columns` use renamed names.

## 3. Column types

| `inferred_type` | `type` in the draft |
|---|---|
| integer | `integer` |
| decimal | `decimal(18,s)`, where s is the most digits after the decimal point among `min`, `max` and `sample_values`; add REVIEW citing `min` and `max`: is this precision right? |
| string with a `parse_date` | `date` |
| string | `string` |
| date | `date` |
| timestamp | `timestamp` |
| boolean | `boolean` |

## 4. Values that look like test data

A value looks like test data when, ignoring case, it equals one of `test`, `testing`,
`dummy`, `fake`, `sample`, `placeholder`, or starts with `test_` or `test-`. When one is
left out of `accepted_values`, add REVIEW naming it: rows with this value will be
quarantined; is that right, or should they be filtered out or accepted?

## 5. Abbreviations

Rename a column when its name, split on `_`, contains one of these parts; replace that
part and keep the rest.

| Part | Becomes |
|---|---|
| `cust` | `customer` |
| `amt` | `amount` |
| `qty` | `quantity` |
| `acct` | `account` |
| `addr` | `address` |
| `prod` | `product` |
| `desc` | `description` |
| `dt` | `date` |
| `num` | `number` |

## 6. `dedupe` settings

`keys` is the column the uniqueness rule fired on. `order_by` is `"<column> desc"` using the
column the freshness rule fired on, with REVIEW: should the row with the latest value be
kept? If no column qualifies for freshness, use `order_by: "<key>"` with REVIEW: which of
the duplicate rows should be kept?

## 7. Comments

Every test and transformation ends with a `#` comment naming the profile number that
justified it, e.g. `# null_count 0`, `# negative_count 5 (min -342.47)`.

A REVIEW goes on its own line directly above the entry it concerns, as a question that
cites the numbers it rests on:

```yaml
      # REVIEW: null_count 4 (1.98%). Should rows with no customer_id be quarantined, or allowed?
      - not_null                  # null_count 4, null_pct 1.98
```
