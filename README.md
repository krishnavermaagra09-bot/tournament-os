# Tournament OS 2.0

A production-grade **Tournament Operating System** — Discord bot + web dashboard for running esports tournaments. Multi-org, AI-assisted, and fully deployed on Replit.

## Run & Operate

- **Discord Bot** workflow — runs `bot_main.py` (persistent background process)
- **Web Dashboard** workflow — runs `web_main.py` on port 8000
- `pnpm --filter @workspace/api-server run dev` — run the Node.js API server (port 5000)
- `pnpm run typecheck` — full typecheck across all Node.js packages
- `pnpm --filter @workspace/db run push` — push DB schema changes (dev only)
- Required env: `DATABASE_URL` — Postgres connection string (auto-provisioned by Replit)

## Stack

### Python Bot + Web Dashboard (`tournament_os/`)
- Discord bot: `discord.py 2.4.0`
- Web dashboard: `FastAPI 0.115.5` + `Jinja2` + Tailwind CSS (CDN)
- Database: PostgreSQL + `SQLAlchemy (asyncio)` + `asyncpg` + `Alembic` migrations
- AI assistant: `Groq` (`llama-3.3-70b-versatile`) via `/ask` slash command
- Config: `pydantic-settings`

### Node.js Monorepo (existing)
- pnpm workspaces, Node.js 24, TypeScript 5.9
- API: Express 5 | DB: Drizzle ORM | Validation: Zod

## Where things live

- `tournament_os/bot_main.py` — Discord bot entrypoint
- `tournament_os/web_main.py` — FastAPI web dashboard entrypoint
- `tournament_os/app/bot/cogs/` — Discord slash command handlers (10 cogs)
- `tournament_os/app/bot/views/` — Discord UI components (buttons, modals, wizards)
- `tournament_os/app/database/models/` — SQLAlchemy ORM models
- `tournament_os/app/database/migrations/` — Alembic migration scripts (4 applied)
- `tournament_os/app/services/` — Business logic (tournaments, brackets, matches, disputes)
- `tournament_os/app/web/routes/` — FastAPI route handlers (dashboard, public, health, ai_chat)

## Architecture decisions

- Bot and web dashboard run as **separate processes** (two workflows) synced via PostgreSQL LISTEN/NOTIFY
- No HTML template files in zip — web dashboard uses inline fallback HTML served by `web_main.py`
- IPv4-only event loop policy in `bot_main.py` to avoid Railway/Replit IPv6 routing issues
- All secrets managed via Replit Secrets (DISCORD_TOKEN, DISCORD_CLIENT_ID, GROQ_API_KEY, ADMIN_DASHBOARD_TOKEN, SECRET_KEY)
- `ADMIN_DASHBOARD_TOKEN` is used as a bearer token for all `/api/dashboard/*` routes

## Product

- `/setup tournament` slash command — 7-step wizard that creates roles, categories, and 20 Discord channels automatically
- `#register` Player Hub — persistent button for player registration (no commands needed)
- `#verification-queue` — auto-posted Approve/Reject/Hold/Flag cards for staff
- `#create-tournament` — persistent 6-step tournament creation wizard
- Control Panel — 9 action buttons per tournament (Status, Registration, Players, Matches, Brackets, Check-in, Announcements, Rules, Danger)
- Support Tickets — `#support` button → private thread per user
- `/ask` — AI assistant scoped per org/guild/tournament
- Web Dashboard — tournament management, registration review, match oversight, analytics

## User preferences

_Populate as you build — explicit user instructions worth remembering across sessions._

## Gotchas

- Run `python -m alembic upgrade head` from `tournament_os/` whenever new migrations are added
- Web dashboard requires `ADMIN_DASHBOARD_TOKEN` as Bearer token for all `/api/dashboard/*` API calls
- Bot and web server must both be running for full functionality
- The web dashboard has no HTML template files — it serves inline HTML fallbacks (no `app/web/templates/` directory)

## Pointers

- See the `pnpm-workspace` skill for Node.js workspace structure
- Discord bot logs: check the **Discord Bot** workflow console
- Web dashboard API docs: `/api/docs` (disabled in production mode)
