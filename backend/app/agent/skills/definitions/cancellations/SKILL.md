---
name: Cancellations
description: >
  Cancelled admissions and churn — how many admissions were cancelled, the churn rate,
  and which centers churn most.
metadata:
  required_tool_names:
    - get_cancellations
  optional_tool_names:
    - get_cancellations_by_center
    - get_fresh_registrations
    - get_region_rollup
    - list_centers
  intents:
    - How many admissions were cancelled
    - What is the churn or cancellation rate
    - Which centers have the worst cancellation problem
  triggers:
    - cancel
    - cancelled
    - canceled
    - cancellation
    - cancellations
    - churn
    - churned
    - dropped
    - dropout
    - drop out
    - withdrew
    - withdrawal
    - refund
    - lost
---

You report cancellations and churn.

## Choosing a tool

- One center or region — `get_cancellations`, which returns the cancelled count, the
  registration base and the churn rate.
- "Which centers are worst" — `get_cancellations_by_center`, already sorted by churn
  rate descending.

## What the numbers mean

The cancellation count is a deliberately simple filter: every student at the center
whose form status is "Admission Cancelled", with no fee, free-admission or active-status
condition applied. The registration denominator does apply all three. So the churn rate
mixes two slightly different populations.

That is exactly what the tracker publishes, and matching the tracker is the
requirement. Do not try to correct it, and do not compute a churn rate yourself from
two other tools. If a user questions the figure, explain how the numerator and
denominator differ — that transparency is the point.

Churn above roughly 5% is worth flagging as needing attention; note it, but do not
invent a cause.
