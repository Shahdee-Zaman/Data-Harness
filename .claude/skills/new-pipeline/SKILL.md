---
name: new-pipeline
description: Draft a pipeline config (configs/pipelines/<name>.yml) for a CSV file from the facts in its profile. Use when the user wants a new pipeline, wants to load a CSV, or asks for a pipeline config to be drafted. Profiles the CSV, drafts the YAML from fixed drafting rules, validates it, and lists the REVIEW questions the user must answer before approving it.
---

# New pipeline

Draft a pipeline config for one CSV file from the facts in its profile, following fixed
drafting rules. The draft is always left as `status: draft`. Only the user approves it.

## Input

The path to a CSV file, supplied after `/new-pipeline` or in the message that triggered
the skill, e.g. `data/raw/orders.csv`. The pipeline name is the file name without its
extension (`orders`).

If no path is supplied, ask for one and wait for the answer.

## Steps

### 1. Profile the CSV

Run `harness profile <csv>` from the project root. If `harness` is not found, run it from
the project's virtual environment: `.venv/Scripts/harness` on Windows, `.venv/bin/harness`
elsewhere. It writes `profiles/<name>.profile.json`.

If the command fails, show its output to the user and stop.

### 2. Read the profile

Read `profiles/<name>.profile.json` in full. Its numbers are the only evidence you may use.
Do not open the CSV, and do not use knowledge of what this kind of data usually looks like.

### 3. Load the drafting rules

Read `references/drafting-rules.md`. Do not read this file before you reach this step.

### 4. Write the draft

If `configs/pipelines/<name>.yml` already exists, do not overwrite it: tell the user and
stop.

Otherwise write `configs/pipelines/<name>.yml` by applying the drafting rules to every
column in the profile.

- Apply only the rules in the drafting rules. Do not invent a rule, and do not use any
  test, transformation type or quality rule that is not in `docs/config-reference.md`.
- Every test and transformation carries a `#` comment naming the profile number that
  justified it.
- Every guess carries a `# REVIEW:` comment phrased as a question, citing the profile
  number it rests on.
- Do not infer an answer because it is plausible, conventional, or typical of similar
  data. If the profile does not settle a question, it stays a REVIEW question.
- Leave `status: draft` and `approved_by: null`.

### 5. Validate

Run `harness validate`. Fix every problem listed under `configs/pipelines/<name>.yml`, then
run it again, until that file shows `OK`.

Fix only your own file. Problems in other files, such as the warehouse config's `type`
being `null`, are the user's decisions: report them in step 6 and do not edit those files.
Never set `status: approved` to make validation pass.

### 6. List the REVIEW questions

Print every `# REVIEW:` question in the draft as a numbered list, in file order, each
prefixed with the column or step it concerns. Then tell the user:

- the path of the draft;
- any problems `harness validate` reported in other files;
- that after answering the questions and editing the file, they approve it themselves by
  setting `status: approved` and `approved_by: <their name>`.
