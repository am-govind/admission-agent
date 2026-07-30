---
name: Retention
description: >
  Senior retention — how many students from last academic year have continued, and how
  that compares to the retention target.
metadata:
  required_tool_names:
    - get_senior_retention
  optional_tool_names:
    - get_senior_retention_pct
    - get_region_rollup
    - get_center_rollup
    - list_centers
  intents:
    - How many senior students were retained from last year
    - What is the retention rate against target
    - Which centers retain seniors best or worst
  triggers:
    - retention
    - retained
    - retain
    - senior
    - seniors
    - continuing
    - continued
    - came back
    - returning
    - re-enrolled
    - reenrolled
    - last year
    - ay25
    - ay2025
---

You report senior retention.

## Choosing a tool

- One center or region — `get_senior_retention`, which returns the retained count, the
  split by payment stage, the target and the achievement percentage.
- Only the percentage against target — `get_senior_retention_pct`.
- "Which centers retain best" — `get_center_rollup` with `metric="senior_retention"`.

## What the numbers mean

Retention reads LAST academic year's dump, not this year's. A retained senior is a
student who was enrolled for more than one year, was not a free admission, is still
active, whose admission was not cancelled, and who had paid either their full fees or
through their 4th EMI. The tool returns those last two groups separately; mention the
split when it is informative.

Because the source is last year's data, retention is unavailable whenever that dump has
not been loaded. The tool will say so. Do not substitute this year's figures or infer
retention from registration counts — they measure different populations.

Retention is a count of students, so it sums across centers and regions normally.
