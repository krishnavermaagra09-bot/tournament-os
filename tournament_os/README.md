# 🏆 Tournament OS 2.0

A production-grade **Tournament Operating System** — Discord bot + web dashboard for running esports tournaments. Multi-org, AI-assisted, and Railway-ready.

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/template/tournament-os)

---

## ✨ Features

| Surface | What it does |
|---------|-------------|
| `/setup tournament` | 7-step wizard — creates roles, categories, and 20 channels automatically |
| `#register` (Player Hub) | Persistent button — players click to register; no commands needed |
| `#verification-queue` | Auto-posted Approve / Reject / Hold / Flag / Send Back cards |
| `#create-tournament` | Persistent button — 6-step tournament creation wizard |
| **Control Panel** | 9 action buttons per tournament: Status, Registration, Players, Matches, Brackets, Check-in, Announcements, Rules, Danger |
| **Support Tickets** | `#support` button → private thread per user |
| `/ask` | AI assistant (Groq `llama-3.3-70b-versatile`) scoped per org/guild/tournament |
| **Web Dashboard** | Tournament management, registration review, match oversight, standings, disputes, analytics |

---

## 🚀 Deploy to Railway (Recommended)

Tournament OS runs as **two Railway services** from the same repo — the bot and the web server.

### Step 1 — Create a Railway project

1. Go to [railway.app](https://railway.app) → **New Project**
2. Choose **Deploy from GitHub repo** → select `tournament-os`
3. Add a **PostgreSQL** plugin from the Railway dashboard

### Step 2 — Web service

- **Root Directory:** `/` (repo root)
- **Config file:** `railway.web.toml`
- Railway auto-runs `alembic upgrade head && python web_main.py` on deploy

### Step 3 — Bot service

- In the same project, click **+ New Service → GitHub Repo** (same repo)
- **Config file:** `railway.bot.toml`
- Railway runs `python bot_main.py`

### Step 4 — Environment Variables

Set these on **both** services (Railway dashboard → Variables):

| Variable | Description |
|----------|-------------|
| `DISCORD_TOKEN` | Your Discord bot token |
| `DISCORD_CLIENT_ID` | Your Discord application client ID |
| `DATABASE_URL` | Auto-filled by Railway PostgreSQL plugin |
| `GROQ_API_KEY` | Groq API key — [console.groq.com](https://console.groq.com) (free) |
| `ADMIN_DASHBOARD_TOKEN` | Random secret for dashboard auth — `openssl rand -hex 32` |
| `SECRET_KEY` | Random secret for sessions — `openssl rand -hex 32` |
| `ENVIRONMENT` | `production` |

> `PORT` is injected automatically by Railway — do NOT set it manually.

---

## 🖥️ Local Development

```bash
# 1. Clone
git clone https://github.com/officialtomein-pixel/tournament-os.git
cd tournament-os

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy and fill in env vars
cp .env.example .env

# 4. Run DB migrations
alembic upgrade head

# 5. Start the bot (terminal 1)
python bot_main.py

# 6. Start the web server (terminal 2)
python web_main.py
```

Or use Docker Compose:

```bash
docker compose up -d
```

Dashboard: `http://localhost:8000/dashboard`  
API docs: `http://localhost:8000/api/docs`

---

## 🎮 Admin Workflow

### Phase 1 — First-Time Setup (once per server)
Run `/setup tournament` → 7-step wizard creates all roles and channels automatically.

### Phase 2 — Create a Tournament
Click the **Create Tournament** button in `#create-tournament` → 6-step wizard.

### Phase 3 — Manage via Control Panel
Every tournament gets a **Control Panel** with 9 buttons — no commands needed.

### Phase 4 — Review Registrations
Cards appear in `#verification-queue` with Approve / Reject / Hold / Flag / Send Back buttons.

### Phase 5 — Run Matches
```
/tournament_generate_bracket [tournament_id]   ← generates bracket
/submit_score [match_id]                       ← players submit scores
/score_override [match_id]                     ← staff override (Referee+)
```

---

## 📋 All Slash Commands

### Admin / Staff
| Command | Permission | Description |
|---------|-----------|-------------|
| `/setup tournament` | Owner | One-time server setup wizard |
| `/tournament_generate_bracket` | Admin | Generate bracket |
| `/analytics` | Admin | View tournament stats |
| `/score_override` | Referee+ | Override a match score |
| `/dispute_list` | Moderator+ | List open disputes |
| `/dispute_assign` | Moderator+ | Assign a dispute to staff |
| `/dispute_resolve` | Moderator+ | Close a dispute |

### Players
| Command | Description |
|---------|-------------|
| `/my_registration` | Check your registration status |
| `/submit_score` | Submit match result |
| `/standings` | View standings/leaderboard |
| `/ask` | Ask the AI assistant |

---

## 🏗️ Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11 |
| Discord | discord.py 2.x |
| Web | FastAPI + Uvicorn |
| Database | PostgreSQL 16 + SQLAlchemy 2.0 async (asyncpg) |
| Migrations | Alembic |
| AI | Groq API — `llama-3.3-70b-versatile` |
| Deployment | Railway (2 services) / Docker Compose |

---

## 📁 Project Structure

```
tournament-os/
├── bot_main.py                   Discord bot entrypoint
├── web_main.py                   FastAPI web server entrypoint
├── requirements.txt
├── alembic.ini
├── Dockerfile.bot                Railway/Docker — bot service
├── Dockerfile.web                Railway/Docker — web service
├── railway.bot.toml              Railway bot service config
├── railway.web.toml              Railway web service config
├── docker-compose.yml            Local dev
└── app/
    ├── bot/
    │   ├── cogs/                 Slash commands (admin, match, registration, dispute, AI)
    │   ├── views/                All Discord UI (buttons, modals, wizards, control panel)
    │   └── helpers/              Formatters, permissions
    ├── services/                 Business logic (bracket, scoring, registration, disputes)
    ├── database/
    │   ├── models/               17 SQLAlchemy ORM models
    │   ├── repositories/         Typed repos with org isolation
    │   └── migrations/           Alembic DDL migrations
    ├── web/routes/               FastAPI routes (dashboard, public, health, AI chat)
    └── config/settings.py        All env-var config (pydantic-settings)
```

---

## 🔐 Environment Variables Reference

See [`.env.example`](.env.example) for a full list with descriptions.

---

## 📄 License

MIT
