# Running Locally — Step-by-Step

A verified walkthrough for getting the Admissions & Finance AI Agent running on a
local machine. The app runs on **synthetic sample data** out of the box, so you can
try everything without Google Sheets credentials. Only the conversational answers
need a local LLM (Ollama) — everything else (auth, data, endpoints, UI) works without it.

- **Backend** → FastAPI on `http://localhost:8500`
- **Frontend** → Vite dev server on `http://localhost:5173` (proxies `/api` → `:8500`)
- **LLM** → Ollama + Qwen2.5 on `http://localhost:11434` (optional but required for chat answers)

Verified with: Python 3.12, Node 20, npm 10 on macOS.

---

## 0. Prerequisites

| Tool | Version | Check |
|------|---------|-------|
| Python | 3.11+ | `python3 --version` |
| Node | 18+ | `node -v` |
| npm | 9+ | `npm -v` |
| Ollama | latest | `ollama --version` (optional, for chat) |

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
- creates a bootstrap admin (`admin` / `admin123` by default — change in `.env`),
- creates the DuckDB file at `./data/app.duckdb`,
- loads synthetic sample data (RD26, RD25, Finance Dump, Targets),
- schedules a daily ~06:00 refresh.

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

# data status
curl -s http://localhost:8500/meta -H "Authorization: Bearer $TOKEN"
# -> {"last_refresh":"...","source":"sample"}
```

> **Note:** Interactive API docs are available at `http://localhost:8500/docs`.

---

## 2. LLM (Ollama) — required for chat answers

The router and skills call a local Qwen2.5 model through Ollama. Without it, the app
still boots and serves data, but `/chat` returns a clean `503 The model service is
unavailable`.

```bash
# install (macOS)
brew install ollama          # or download from https://ollama.com

# start the Ollama service (leave running in its own terminal)
ollama serve

# pull a model (in another terminal)
ollama pull qwen2.5:14b-instruct     # needs ~10GB RAM/VRAM
# or, for smaller machines:
ollama pull qwen2.5:7b-instruct
```

If you use a different tag, update `OLLAMA_MODEL` in `backend/.env` to match, then
restart the backend.

Confirm chat works end-to-end:

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

Open **http://localhost:5173**, sign in with the admin credentials, and ask
questions in English or Hinglish.

### Verify the frontend

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5173/     # -> 200
curl -s http://localhost:5173/api/health                            # -> {"status":"ok"}
```

---

## 4. Run the tests (golden-parity harness)

```bash
cd backend
source .venv/bin/activate
pytest -q
# -> 16 passed
```

---

## 5. Switching to the real Google Sheet

By default `USE_SAMPLE_DATA=true`. To use the real workbook:

1. Create a Google service account, share the workbook with it, download the JSON key
   into `backend/secrets/service-account.json`.
2. In `backend/.env`:
   ```
   USE_SAMPLE_DATA=false
   GSHEET_ID=<the real sheet id>
   GOOGLE_APPLICATION_CREDENTIALS=./secrets/service-account.json
   TAB_TARGETS=Targets   # confirm the real targets tab name + layout
   ```
3. Restart the backend, then trigger a pull:
   ```bash
   curl -X POST http://localhost:8500/refresh -H "Authorization: Bearer $TOKEN"
   ```

---

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `/chat` → `503 The model service is unavailable` | Ollama not running / model not pulled | Start `ollama serve` and `ollama pull qwen2.5:...`; match `OLLAMA_MODEL` in `.env` |
| `ModuleNotFoundError: fastapi` | venv not activated / deps not installed | `source .venv/bin/activate && pip install -r requirements.txt` |
| `[Errno 48] Address already in use` on `:8500` | a previous backend is still running | find and stop it: `lsof -ti:8500 \| xargs kill -9` |
| Login fails | wrong credentials, or admin created earlier with a different password | use the values in `.env`; the admin is only bootstrapped when the users table is empty (delete `backend/data/app.duckdb` to re-bootstrap) |
| Frontend loads but calls fail | backend not running / wrong port | ensure backend is on `:8500`; the Vite proxy targets that port |
| `Fontconfig error: No writable cache directories` (backend log) | matplotlib font cache | harmless; to silence, set `export MPLCONFIGDIR=/tmp/mpl` before starting |

---

## 7. Quick start (all together)

```bash
# terminal 1 — Ollama
ollama serve

# terminal 2 — backend
cd backend && source .venv/bin/activate && python run.py

# terminal 3 — frontend
cd frontend && npm run dev
```

Then open **http://localhost:5173**.
