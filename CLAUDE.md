# Data Harness

Pipeline configs in `configs/` are compiled to dbt SQL by `harness compile` and run by
`harness run`. See `docs/config-reference.md` for the config vocabulary.

## Rules

- Only edit files under `configs/`.
- Never edit files in `dbt_project/models/generated/`. `harness compile` writes them.
- Always run `harness validate` after editing any YAML file, and fix what it reports in the
  files you edited.
- Never change a pipeline's `status` from `draft` to `approved`. Only the user approves.
