# Backend — Architecture Guide

FastAPI service that answers admissions and finance questions by **routing** each
question to one **skill**, which calls **tools** that delegate to a sealed **analytics**
layer over DuckDB, and streams tables and charts back to the browser.

## The one-minute mental model

```
  user question
       │
       ▼
  GUARDRAILS ── injection screening on the way in, PII masking on the way out
       │
       ▼
  MEMORY ────── loads the center/region/metric under discussion
       │
       ▼
  ROUTER ────── picks exactly ONE skill; never answers the question itself
       │
       ▼
  SKILL ─────── a SKILL.md file: prompt text plus the list of tools it may call
       │
       ▼
  TOOL ──────── validates arguments against a pydantic model, then delegates
       │
       ▼
  ANALYTICS ─── sealed business logic: parameterised SQL, exact numbers
       │
       ▼
  ToolResult ── values + optional table/chart + provenance
       │
       ▼
  RUNTIME ───── native table and chart blocks, staleness note, provenance line
```

Three contracts hold it together:

- **A skill is data.** A directory containing `SKILL.md`: YAML frontmatter declaring
  which tools it may call, plus a markdown body used verbatim as prompt text. Adding a
  skill means adding a file, not writing code.
- **A tool is a validated wrapper.** `@tool(name, description, ParamsModel)` derives the
  OpenAI function schema from a pydantic model and validates arguments before any SQL
  runs. A hallucinated argument becomes a corrective message, not a wrong number.
- **`ToolResult` is the universal envelope.** Either `ok` with `values`, an optional
  table and `ChartSpec`, and a `Provenance`; or not-ok with `unavailable_reason` (the
  source is missing) or `clarification` (the center was ambiguous).

## Why business logic is not inside the tools

`app/analytics/` holds the logic; `app/agent/tools/` holds one-line wrappers:

```python
@tool("get_arpu", "Average revenue per user for a center or region.", ScopeParams)
def get_arpu(center: str | None = None, region: str | None = None) -> ToolResult:
    return revenue.arpu(center=center, region=region)
```

Roughly eight of the 28 tools are composites — `get_finance_summary`,
`get_region_rollup`, `get_target_scoreboard`, `get_arpu_by_center` — that fan out over
the other twenty, so the logic has to be callable from Python and not only from the
model. More importantly, thresholds must be declared once: the workbook deliberately
uses `fees_paid > 3498` for some metrics and `>= 3498` for others, and a second copy of
that literal in a wrapper is a second source of truth that will drift.
`tests/test_tools.py` fails the build if any threshold from `analytics/filters.py`
appears under `agent/tools/`.

## Storage split

| Store | File | Holds | Lifetime |
|---|---|---|---|
| DuckDB | `data/analytics.duckdb` | `rd26`, `rd25`, `finance_dump`, `targets` | replaced wholesale each morning |
| SQLite | `data/app.sqlite3` | `users`, `conversations`, `messages`, `conversation_memory`, `meta`, `refresh_runs` | survives every refresh |

The split exists because the analytics file is dropped and rebuilt daily; logins and
chat history cannot live somewhere that gets replaced. `core/migrate.py` moves state out
of the pre-split `app.duckdb` once, on first startup.

## Directory layout (top → bottom by dependency)

```
app/
├── main.py              app factory, lifespan, catch-up refresh scheduler
├── models.py            wire schemas (request/response, renderState, content blocks)
│
├── api/                 HTTP layer (thin)
│   ├── auth.py            POST /auth/login
│   ├── chat.py            POST /chat, POST /chat/stream
│   └── admin.py           GET /health, GET /meta, GET /refresh/history, POST /refresh
│
├── agent/               THE AI ENGINE
│   ├── router.py          skill selection: LLM choice, deterministic keyword fallback
│   ├── loop.py            capped tool-calling loop, scoped to the chosen skill's tools
│   ├── runtime.py         orchestration; ToolResult → table/chart blocks + provenance
│   ├── memory.py          conversation slots, context injection, scope inheritance
│   ├── prompts.py         shared rules, data dictionary, prompt composition
│   ├── skills/
│   │   ├── loader.py        SKILL.md frontmatter parser and validation
│   │   ├── __init__.py      registry; verifies every declared tool exists at import
│   │   └── definitions/     admissions, finance, revenue, retention,
│   │                        cancellations, data-explorer, knowledge
│   └── tools/
│       ├── registry.py      @tool decorator, schema derivation, parameter models
│       ├── admissions_tools.py  finance_tools.py  explorer_tools.py
│
├── guardrails/          CROSS-CUTTING SAFETY
│   ├── input_scanners.py  block prompt injection and jailbreak attempts
│   └── output_scanners.py mask residual PII
│
├── analytics/           SEALED BUSINESS LOGIC (pure functions over DuckDB)
│   ├── result.py          ToolResult, Provenance, ChartSpec
│   ├── filters.py         the shared SQL predicates and every threshold literal
│   ├── query.py           count/avg/sum/select helpers, provenance, target lookup
│   ├── admissions.py  finance.py  revenue.py  retention.py  cancellations.py
│   ├── rollups.py         region/center roll-ups, target scoreboard
│   └── explorer.py        guarded ad-hoc SELECT
│
├── data/                DATA LAYER
│   ├── schema.py          tables, typed columns, required columns, PII columns
│   ├── sources/           base.py, google_sheets.py, excel.py, sample.py
│   ├── tabular.py         typed staging load and atomic swap
│   ├── ingestion.py       refresh() and audited run_refresh()
│   ├── availability.py    what is loaded, how fresh, what is missing
│   ├── reference_date.py  data-anchored "today" (MAX(joining_date))
│   ├── registry.py        center/region resolver with clarification
│   └── conversation.py    chat history
│
├── core/                FOUNDATIONS
│   ├── config.py          settings from .env
│   ├── database.py        DuckDB: read-write plus a read-only snapshot for the explorer
│   ├── appdb.py           SQLite app state
│   ├── migrate.py         one-time move out of the pre-split DuckDB file
│   └── security.py        bcrypt + JWT
│
└── streaming/           SELF-CONTAINED SSE
    ├── events.py          frame builders (run-*, text-message-*, state-delta)
    └── sse.py             turn → event stream
```

## Ingestion

`DATA_SOURCE` selects exactly one of `gsheets`, `excel` or `sample`. There is no fallback
chain: if the chosen source fails, the refresh is recorded as failed and the last good
data stays in place. Silently synthesising numbers when the sheet is unreachable is
indistinguishable from success, which is worse than an outage.

Each table is read in 5000-row windows, loaded all-`VARCHAR` into `<table>__raw`, cast
into `<table>__staging` per the types in `data/schema.py`, then atomically swapped into
place — so the write lock is held only for a rename, and a mid-load failure leaves the
previous data intact. Missing tabs are recorded by `availability.py`, and the tools that
depend on them decline with a reason.

The scheduler is catch-up driven rather than sleep-until: it compares a persisted
`last_success` against the most recent elapsed 08:30 Asia/Kolkata cutoff, so a process
that was down at 08:30 refreshes as soon as it is back, and one that was up refreshes
exactly once.

## Adding a skill

1. Add the metric functions to `app/analytics/<domain>.py`, returning `ToolResult`. Put
   any new threshold in `analytics/filters.py`.
2. Add one-line wrappers in `app/agent/tools/<domain>_tools.py` using `@tool`.
3. Create `app/agent/skills/definitions/<skill-id>/SKILL.md` with frontmatter naming the
   tools, plus `intents` and `triggers` for the fallback router, and a markdown body
   telling the model how to use them.

Nothing else needs editing. The registry discovers the directory, validates the tool
names at import, and both routers start considering the skill immediately.

## Invariants

- Every number in a reply comes from a `ToolResult`. The model writes no SQL for a known
  metric.
- The router selects a skill and never answers.
- The explorer is `SELECT`-only, single-statement, row-capped, PII-denied, and runs on a
  read-only `ATTACH` with external file access disabled.
- Missing data produces an explicit decline, never a synthesised figure.
- Every answer carries the reference date, and a staleness warning when the refresh is
  overdue.

## Tests

```bash
pytest tests/
```

No model or network access is needed: `tests/conftest.py` redirects every path into a
temp directory and loads the synthetic dataset, and the router tests exercise the
deterministic fallback — which is also what runs in production whenever the model is
unreachable.

| File | Covers |
|---|---|
| `test_skills.py` | frontmatter validity, every declared tool exists, every tool is reachable |
| `test_tools.py` | schema shape, argument validation, no thresholds or SQL in wrappers |
| `test_router.py` | keyword routing, and that every trigger selects its own skill |
| `test_memory.py` | slot persistence, scope inheritance, global-scope override |
| `test_explorer.py` | writes, escapes, multi-statement and PII attempts all refused |
| `test_parity.py` | analytics invariants, plus a golden-value harness for the workbook |
| `test_render.py` | table/chart block shapes, dedupe, refresh catch-up logic |
