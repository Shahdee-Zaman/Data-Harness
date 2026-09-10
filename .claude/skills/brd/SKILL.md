---
name: brd
description: Gather business requirements for an initiative and produce a completed Business Requirements Document (BRD). Use when the user asks for a BRD, wants to capture or write up the requirements for a project, feature, or initiative, or describes a new initiative whose requirements need documenting. Asks clarifying questions from a fixed question bank, then fills a standard BRD template and writes it to disk.
---

# BRD

Gather business requirements for an initiative, ask clarifying questions drawn from a
fixed question bank, and produce a completed BRD document.

## Input

The initiative description is free text the user supplies when this skill starts —
after `/brd`, or in the message that triggered the skill. It may be a single sentence
or several paragraphs.

If no description is supplied, do not stop and do not ask for one up front. Begin at
Round 1 (step 4) with every question treated as unanswered; the initiative name and
description then come out of the user's answers.

## Steps

### 1. Read the initiative description

Read whatever the user supplied in full and extract the initiative name. If no name is
stated, derive a short one from the description and note in the output that the name was
derived. If nothing was supplied, leave the name open until the Round 1 answers arrive.

### 2. Load the question bank

Read `references/question-bank.md`. It holds the fixed set of questions, grouped into
categories. The order categories appear in that file is the priority order used in
step 4. Do not read this file before you reach this step.

### 3. Assess every question in the bank

For every question in the bank, mark it as exactly one of:

- **answered** — the user has stated something that directly and completely answers the
  question.
- **partially answered** — the user has stated something that addresses the question but
  leaves a material part of it open.
- **unanswered** — the user has stated nothing that addresses the question.

Base this assessment **only on what the user has actually stated**. Do not infer an
answer because it is plausible, conventional, typical of similar initiatives, or obvious
from the domain. An answer you supplied yourself is not an answer. If you are weighing
whether something counts, it does not count: mark it unanswered or partial.

### 4. Round 1 — ask clarifying questions

Choose between **3 and 7** questions to ask. Rules:

- Choose only from questions marked unanswered or partially answered.
- Prioritise by the question bank's category order: exhaust higher categories before
  drawing from lower ones.
- Within a category, prefer unanswered over partially answered.
- Never ask a question marked answered.
- If fewer than 3 questions are unanswered or partial, ask all of them.

Present the chosen questions to the user as a numbered list, using the bank's wording
(you may append a short clarifying phrase to a partially answered question to name the
part that is still open). Ask nothing else. Then wait for the user's answers before
continuing.

**A second round, only if needed.** If the Round 1 answers leave a question in one of
the top three categories (Business Context, Objectives and Success Metrics, Scope) still
unanswered, run one more round on the same rules. Never run more than two rounds; carry
anything still open into Open Questions.

### 5. Fill the output template

Read `references/output-template.md` and fill every placeholder using the user's
original description plus their answers from the question rounds. Do not read this file
before you reach this step.

- Do not invent content. Where a template field has no stated answer, write
  `Not specified` in that field and record the corresponding bank question under
  **Open Questions**.
- Carry every question still marked unanswered or partially answered into the
  **Open Questions** section, with its question ID.
- Keep the template's section order and headings unchanged.

### 6. Write the document

Write the filled template to:

```
output/brd/<slug>-brd.md
```

`<slug>` is the initiative name lowercased, with spaces and punctuation replaced by
single hyphens, and leading/trailing hyphens removed. Create the `output/brd/`
directory if it does not exist.

### 7. Report the path

State the written file path back to the user.
