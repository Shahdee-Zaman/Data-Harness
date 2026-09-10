# BRD Question Bank

Fixed set of clarifying questions. Categories are listed in priority order: when
selecting questions to ask, exhaust higher categories before drawing from lower ones.
Question IDs are stable and are used to reference open questions in the output.

## 1. Business Context

- **BC1** — What business problem or opportunity does this initiative address?
- **BC2** — What happens today without it: what is the current process or workaround?
- **BC3** — What is the cost of not doing this (revenue, risk, manual effort, churn)?
- **BC4** — Why now? What triggered this initiative?

## 2. Objectives and Success Metrics

- **OS1** — What outcome would define this initiative as successful?
- **OS2** — Which metrics will measure that outcome, and what are the target values?
- **OS3** — What is the current baseline for those metrics?
- **OS4** — Over what period must the targets be met?

## 3. Scope

- **SC1** — What capabilities are explicitly in scope for the first release?
- **SC2** — What is explicitly out of scope?
- **SC3** — Is this a new capability, a replacement for something existing, or an
  extension of it?
- **SC4** — Are further phases planned beyond the first release, and what is in them?

## 4. Stakeholders and Users

- **ST1** — Who is the business owner accountable for this initiative?
- **ST2** — Who are the end users or personas, and roughly how many of each?
- **ST3** — Which teams or departments are affected by the change?
- **ST4** — Who must approve these requirements before build starts?

## 5. Functional Requirements

- **FR1** — What are the primary user journeys or workflows the solution must support?
- **FR2** — What actions must each user role be able to perform?
- **FR3** — What business rules, validations, or approval steps govern those actions?
- **FR4** — What reporting or visibility do stakeholders need from the solution?
- **FR5** — What must happen in exception, error, or rejection cases?

## 6. Data

- **DA1** — What data does the solution create, read, update, or delete?
- **DA2** — Where does that data come from today, and who owns it?
- **DA3** — What data quality, retention, or residency requirements apply?
- **DA4** — Is any of the data sensitive, regulated, or personally identifiable?

## 7. Systems and Integrations

- **SI1** — Which existing systems must this integrate with?
- **SI2** — In which direction does data flow with each, and how fresh must it be?
- **SI3** — Which system is the source of truth for each shared entity?
- **SI4** — Are any systems being migrated or decommissioned as part of this?

## 8. Non-Functional Requirements

- **NF1** — What volume and concurrency must the solution handle at launch and at peak?
- **NF2** — What availability, performance, or latency expectations apply?
- **NF3** — What access control and audit requirements apply?
- **NF4** — What compliance, legal, or regulatory standards must be met?

## 9. Constraints, Assumptions and Dependencies

- **CA1** — What budget, technology, or platform constraints are already fixed?
- **CA2** — What assumptions is this initiative currently resting on?
- **CA3** — What external teams, vendors, or deliverables does it depend on?
- **CA4** — What existing commitments or contracts affect the approach?

## 10. Risks

- **RI1** — What could cause this initiative to fail or be abandoned?
- **RI2** — What adoption or change-management risk exists for the affected users?
- **RI3** — What is the fallback if the solution cannot be delivered as scoped?

## 11. Timeline and Delivery

- **TL1** — What is the target delivery date, and what drives it?
- **TL2** — Are there fixed external dates (regulatory, contractual, seasonal) to hit?
- **TL3** — If the date is at risk, what does the minimum acceptable first release
  look like?
- **TL4** — How will the solution be rolled out to users?
