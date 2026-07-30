# Running Locally — Step-by-Step

A verified walkthrough for getting the Admissions & Finance AI Agent running on a local
machine. Everything except the conversational answers works without credentials: auth,
ingestion, metrics, tables, charts and every endpoint run on synthetic data out of the box.

- **Backend** → FastAPI on `http://localhost:8500`
- **Frontend** → Vite dev server on `http://localhost:5173` (proxies `/api` → `:8500`)
- **LLM** → any OpenAI-compatible endpoint; GitHub Models by default, Ollama locally

Verified with: Python 3.12, Node 20, npm 10 on macOS.

---

## 0. Prerequisites

| Tool | Version | Check |
|------|---------|-------|
| Python | 3.11+ | `python3 --version` |
| Node | 18+ | `node -v` |
| npm | 9+ | `npm -v` |

A model endpoint is needed for chat answers — either a GitHub token (§2a) or Ollama (§2b).

---

## Checklist — everything working, in order

Each step is verifiable on its own, so a failure tells you exactly which one broke.

| # | Step | You are done when |
|---|------|-------------------|
| 1 | Create the venv and install (§1) | `pytest -q` passes |
| 2 | `cp .env.example .env`, set `JWT_SECRET` and `BOOTSTRAP_ADMIN_PASSWORD` (§1c) | startup logs no longer warn about defaults |
| 3 | Choose `DATA_SOURCE` (§5) | startup logs `Loaded <n> rows into rd26` |
| 4 | Start the backend (§1) | `curl /health` returns `{"status":"ok"}` |
| 5 | Log in and check `/meta` (§1) | `stale` is `false` and `rowCounts` is non-empty |
| 6 | Configure a model endpoint (§2) | `POST /chat` returns an answer, not "the language model is not configured" |
| 7 | Start the frontend (§3) | a question returns prose plus a table or chart |
| 8 | Confirm the schedule (§6) | `/meta` shows `refreshAt` and `refreshDue: false` after a successful load |

---

## 1. Backend

```bash
cd backend

# 1a. Create + activate a virtualenv
python3 -m venv .venv
source .venv/bin/activate

# 1b. Install dependencies
pip install -r requirements.txt

# 1c. Create your local config from the template
cp .env.example .env
# then edit .env: set a long random JWT_SECRET, and change the admin password.
```

Generate a strong `JWT_SECRET`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Start the server:

```bash
python run.py
# serves on http://localhost:8500 (auto-reload enabled)
```

On first startup it:

- creates the SQLite app database at `./data/app.sqlite3` and bootstraps an admin
  (`admin` / `admin123` by default — change it in `.env`),
- migrates users and chat history out of a pre-split `./data/app.duckdb` if one exists,
- creates the analytics DuckDB at `./data/analytics.duckdb` and loads the data source
  named by `DATA_SOURCE` (`sample` by default),
- starts the daily refresh scheduler for 08:30 Asia/Kolkata.

### Verify the backend

```bash
# health (no auth)
curl -s http://localhost:8500/health
# -> {"status":"ok"}

# log in and capture a token
TOKEN=$(curl -s -X POST http://localhost:8500/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# freshness, row counts, which tables are usable, skills and tool count
curl -s http://localhost:8500/meta -H "Authorization: Bearer $TOKEN"

# refresh now, and read the audit trail
curl -s -X POST http://localhost:8500/refresh -H "Authorization: Bearer $TOKEN"
curl -s http://localhost:8500/refresh/history -H "Authorization: Bearer $TOKEN"
```

> Interactive API docs: `http://localhost:8500/docs`.

---

## 2. A model endpoint — required for chat answers

Without one the app still boots and serves data; `/chat` replies that the model is not
configured. Routing, metrics and rendering all keep working.

### 2a. GitHub Models (default, no local GPU)

Create a token with the **models** permission, then in `backend/.env`:

```
LLM_BASE_URL=https://models.github.ai/inference
LLM_MODEL=openai/gpt-4.1
GITHUB_TOKEN=<your token>
```

### 2b. Ollama (fully local)

```bash
brew install ollama          # or download from https://ollama.com
ollama serve                 # leave running in its own terminal
ollama pull qwen2.5:14b-instruct     # ~10GB RAM/VRAM; use :7b-instruct if tighter
```

Then in `backend/.env`:

```
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=qwen2.5:14b-instruct
LLM_API_KEY=ollama
```

Restart the backend, then confirm chat works end to end:

```bash
curl -s -X POST http://localhost:8500/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"message":"how many fresh registrations this month?"}'
```

---

## 3. Frontend

```bash
cd frontend
npm install
npm run dev
# serves on http://localhost:5173 and proxies /api -> http://localhost:8500
```

Open **http://localhost:5173**, sign in with the admin credentials, and ask questions in
English or Hinglish.

### Verify the frontend

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5173/     # -> 200
curl -s http://localhost:5173/api/health                            # -> {"status":"ok"}
```

---

## 4. Run the tests

```bash
cd backend
source .venv/bin/activate
pytest -q
```

No model, network or credentials needed. The suite redirects every path into a temp
directory, so it never touches your local `data/`.

---

## 5. Using the real Google Sheet

1. Create a Google service account and download its JSON key to
   `backend/secrets/service-account.json`.
2. Share the workbook with the `client_email` from that file (Viewer is enough).
   Skipping this step makes reads fail with a 404 that looks like a wrong sheet ID.
3. In `backend/.env`:
   ```
   DATA_SOURCE=gsheets
   GSHEET_ID=<the real sheet id>
   GOOGLE_APPLICATION_CREDENTIALS=./secrets/service-account.json
   TAB_RD26=RD26_DUMP
   TAB_RD25=RD25_DUMP
   TAB_FINANCE=Finance Dump
   TAB_TARGETS=Targets
   ```
4. Restart the backend and trigger a pull:
   ```bash
   curl -X POST http://localhost:8500/refresh -H "Authorization: Bearer $TOKEN"
   ```
   The response reports rows loaded per table, plus any tab that was absent. Tabs that
   are missing are reported, not invented, and the metrics that need them say so.

To work from a local export instead, set `DATA_SOURCE=excel` and
`EXCEL_FILE_PATH=../TRY.xlsx`.

---

## 6. Logs — reading what the agent did

Everything goes to the console by default, one line per event, each tagged with a request
id that ties a whole turn together:

```
INFO app.agent.runtime [72570db92f32] Turn starting: how many registrations this month?
INFO app.agent.runtime [72570db92f32] Routed to admissions via keyword (matched registrations, this month)
INFO app.agent.loop    [72570db92f32] Tool get_monthly_admissions() -> ok in 34ms
INFO app.agent.runtime [72570db92f32] Turn done in 812ms: skill=admissions tools=[get_monthly_admissions] blocks=2 chars=412
INFO app.main          [72570db92f32] POST /chat -> 200 in 818ms
```

The same id is returned as the `X-Request-Id` response header, so a specific bad answer
can be found in the log rather than searched for by timestamp.

Useful settings in `backend/.env`:

```
LOG_LEVEL=DEBUG              # adds model round-trip timings and the memory slots in scope
LOG_FILE=./data/agent.log    # rotating file alongside the console (10MB x 5)
LOG_FORMAT=json              # one JSON object per line, for deployment
```

Then, to follow just one turn:

```bash
tail -f backend/data/agent.log | grep 72570db92f32
```

At startup the log states which databases and data source are in use, and warns if
`JWT_SECRET` or the admin password are still at their defaults. Login attempts, blocked
inputs, every ad-hoc SQL query and each refusal are recorded, which is what makes the
per-user audit trail real rather than aspirational.

---

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| No log output at all beyond uvicorn's own lines | an older `run.py`, or the app started some other way | start with `python run.py`, or call `setup_logging()` before your own `uvicorn.run` |
| Chat replies "the language model is not configured" | no `GITHUB_TOKEN` / `LLM_API_KEY` | set one per §2, then restart |
| `/chat` → `503` | the configured endpoint is unreachable | check `LLM_BASE_URL`; for Ollama make sure `ollama serve` is running |
| `ModuleNotFoundError: fastapi` | venv not activated / deps not installed | `source .venv/bin/activate && pip install -r requirements.txt` |
| `[Errno 48] Address already in use` on `:8500` | a previous backend is still running | `lsof -ti:8500 \| xargs kill -9` |
| Login fails | admin was bootstrapped earlier with a different password | the admin is only created when the users table is empty; delete `backend/data/app.sqlite3` to re-bootstrap |
| A metric replies that data is unavailable | its source tab was not loaded | check `GET /meta` for the table's `reason`, then fix the tab name in `.env` and refresh |
| Answers start with a staleness warning | no successful refresh in over a day | `GET /refresh/history` shows the failure, and `lastError` in `/meta` explains it |
| Refresh fails with a 404 from Google | workbook not shared with the service account | share it with the key's `client_email` |
| `JSONDecodeError` reading the service-account key | the key file is malformed | re-download it; the `private_key` newlines must be intact |
| Frontend loads but calls fail | backend not running / wrong port | ensure the backend is on `:8500`; the Vite proxy targets that port |
| An answer looks wrong and you need to know why | — | find the turn by its `X-Request-Id`; the log lists the skill chosen and every tool call with its arguments |

---

## 8. Quick start (all together)

```bash
# terminal 1 — backend
cd backend && source .venv/bin/activate && python run.py

# terminal 2 — frontend
cd frontend && npm run dev
```

Then open **http://localhost:5173**.
