# Backend — Architecture Guide

FastAPI service that answers admissions/finance questions by **routing** each
question to a **skill**, which calls sealed **analytics** tools over DuckDB and
streams the result back.

## The one-minute mental model

```
                       ┌─────────────────────────────────────────┐
  user question  ─────▶│  ROUTER  (master prompt)                │
                       │  "which skill should handle this?"       │
                       └───────────────┬──────────────────────────┘
                                       │ picks ONE skill
                                       ▼
                       ┌─────────────────────────────────────────┐
                       │  SKILL  (focused prompt + scoped tools)  │
                       │  e.g. Admissions, Finance, Revenue…      │
                       └───────────────┬──────────────────────────┘
                                       │ calls its tools
                                       ▼
                       ┌─────────────────────────────────────────┐
                       │  ANALYTICS  (sealed blackbox logic)      │
                       │  pure DuckDB functions — exact numbers   │
                       └──────────────────────────────────────────┘
```

- **Router** (`agent/router.py`) — an LLM call (with a keyword fallback) that reads the
  question and returns the best `skill_id`. It never answers the question itself.
- **Skills** (`agent/skills/*.py`) — each is a domain capability with its own prompt and a
  *scoped* set of LLM tools. The router hands off to exactly one skill per turn.
- **Tools** — thin wrappers (inside each skill) over the analytics layer. The LLM only
  chooses a tool and extracts params; it never writes SQL.
- **Analytics** (`analytics/*.py`) — the sealed "blackbox" business logic. Pure functions,
  no LLM awareness, faithful to the spreadsheet formulas.

## Directory layout (top → bottom by dependency)

```
app/
├── main.py              App factory + lifespan (bootstrap admin, initial load, daily refresh)
├── models.py            Pydantic wire schemas (request/response + renderState)
│
├── api/                 HTTP layer (thin routers)
│   ├── auth.py            POST /auth/login
│   ├── chat.py            POST /chat, POST /chat/stream
│   └── admin.py           GET /health, GET /meta, POST /refresh
│
├── agent/               THE AI ENGINE
│   ├── router.py          master router (LLM + keyword fallback)
│   ├── runtime.py         orchestrates: route → run skill → collect output
│   ├── prompts.py         router prompt, data dictionary, skill-prompt composer
│   └── skills/
│       ├── base.py          Skill dataclass, agent builder, shared tool helpers
│       ├── admissions.py    registrations, monthly, DOD, class-wise
│       ├── finance.py       1st/2nd EMI, auto-pay, loan eligibility
│       ├── revenue.py       ARPU
│       ├── retention.py     senior retention (AY25)
│       ├── cancellations.py cancellations + churn
│       ├── data_explorer.py masked previews
│       └── knowledge.py     definitions / greetings / out-of-scope (no tools)
│
├── guardrails/          CROSS-CUTTING SAFETY
│   ├── errors.py          GuardrailError
│   ├── input_scanners.py  block prompt-injection / jailbreak
│   └── output_scanners.py mask residual PII (reg numbers)
│
├── analytics/           SEALED BLACKBOX LOGIC (pure DuckDB functions)
│   ├── base.py            predicates, query helpers, MetricResult, ₹ formatting
│   ├── admissions.py  finance.py  revenue.py  retention.py  cancellations.py
│   ├── preview.py         masked sample rows
│   └── charts.py          matplotlib → base64 PNG
│
├── data/                DATA LAYER
│   ├── schema.py          table names, column defs, PII columns (single source of truth)
│   ├── sample_data.py     synthetic generator (runs with no credentials)
│   ├── google_sheets.py   real Google Sheets pull
│   ├── ingestion.py       refresh() dispatcher (sheet or sample)
│   ├── reference_date.py  data-anchored "today" (MAX(joining_date))
│   ├── registry.py        center/region resolver (fuzzy + clarification)
│   └── conversation.py    backend-canonical chat history
│
├── core/                FOUNDATIONS
│   ├── config.py          settings from .env
│   ├── database.py        DuckDB connection + helpers
│   └── security.py        bcrypt + JWT auth
│
└── streaming/           SELF-CONTAINED SSE
    ├── events.py          SSE frame builders (run-*, text-message-*, state-delta)
    └── sse.py             turn → event stream (surfaces the routing decision)
```

## How to add a new skill

1. Create `analytics/<domain>.py` with pure functions returning `MetricResult`.
2. Create `agent/skills/<domain>.py`:
   - register tools with `@agent.tool` wrappers that call your analytics functions via `emit(...)`,
   - export a `Skill(...)` with `id`, `name`, `description`, `examples`, `instructions`, `register`.
3. Add it to the list in `agent/skills/__init__.py`.
4. (Optional) add keyword hints in `agent/router.py` for the fallback path.

That's it — the router will start considering the new skill automatically, and the UI
shows "Routing to the <skill> skill…" while it runs.

## Request lifecycle (streaming)

`run-started → thinking-start → processing-status ("Routing to …") → run skill →
thinking-end → text-message-* (answer deltas) → state-delta (tables/charts) →
text-message-* (provenance) → run-finished`

## Tests

```bash
pytest tests/            # test_parity.py (analytics) + test_router.py (routing)
```

Neither test needs Ollama — the router tests exercise the deterministic keyword
fallback, which also guarantees graceful degradation when the model is offline.
