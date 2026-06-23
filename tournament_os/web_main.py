"""
Web server entrypoint — FastAPI + Jinja2 + Tailwind CSS.
Runs as a separate process from bot_main.py.
Cross-process sync via PostgreSQL LISTEN/NOTIFY.
"""
import asyncio
import logging
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.events.subscribers import notification_handler, analytics_handler
from app.web.routes import public, dashboard, health, ai_chat

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    logger.info("Web server starting up...")
    notification_handler.register_all()
    analytics_handler.register_all()
    asyncio.create_task(_pg_listen())
    logger.info("Web server ready")
    yield
    logger.info("Web server shutting down...")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Tournament OS — Dashboard API",
        version="1.0.0",
        description="Tournament Operating System — Organizer Dashboard and Public API",
        docs_url="/api/docs" if not settings.is_production else None,
        redoc_url="/api/redoc" if not settings.is_production else None,
        lifespan=_lifespan,
    )

    # CORS — allows Discord bot and dashboard clients
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # tighten in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Static files and templates
    try:
        app.mount("/static", StaticFiles(directory="app/web/static"), name="static")
    except RuntimeError:
        logger.warning("No static directory found — skipping static file mount")

    # API routes
    app.include_router(health.router)
    app.include_router(public.router)
    app.include_router(dashboard.router)
    app.include_router(ai_chat.router)

    # Templates
    import os
    try:
        if os.path.isdir("app/web/templates"):
            templates = Jinja2Templates(directory="app/web/templates")
        else:
            templates = None
    except Exception:
        templates = None

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def root(request: Request):
        if templates:
            return templates.TemplateResponse("index.html", {"request": request})
        return HTMLResponse(content="""
<!DOCTYPE html>
<html>
<head><title>Tournament OS</title>
<script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-900 text-white min-h-screen flex items-center justify-center">
  <div class="text-center">
    <h1 class="text-4xl font-bold mb-4">🏆 Tournament OS</h1>
    <p class="text-gray-400 mb-8">Production-grade Tournament Operating System</p>
    <div class="space-x-4">
      <a href="/dashboard" class="bg-indigo-600 px-6 py-3 rounded-lg hover:bg-indigo-700">Dashboard</a>
      <a href="/api/docs" class="bg-gray-700 px-6 py-3 rounded-lg hover:bg-gray-600">API Docs</a>
    </div>
  </div>
</body>
</html>
""")

    @app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard_page(request: Request):
        if templates:
            return templates.TemplateResponse("dashboard.html", {"request": request})
        return HTMLResponse(content=dashboard_html())

    @app.exception_handler(404)
    async def not_found(request: Request, exc):
        return JSONResponse({"detail": "Not found"}, status_code=404)

    @app.exception_handler(500)
    async def server_error(request: Request, exc):
        logger.error("Unhandled 500: %s", exc, exc_info=True)
        return JSONResponse({"detail": "Internal server error"}, status_code=500)

    return app


async def _pg_listen() -> None:
    from app.services.notify_listener import PGNotifyListener
    from app.events.bus import event_bus

    async def handle_event(event: dict) -> None:
        event_type = event.get("type", "")
        await event_bus.publish(event_type, event)

    listener = PGNotifyListener(settings.database_url, handle_event)
    try:
        await listener.start()
    except Exception as e:
        logger.error("PGNotifyListener error: %s", e)


def dashboard_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Tournament OS — Dashboard</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-900 text-white min-h-screen">
  <nav class="bg-gray-800 border-b border-gray-700 px-6 py-4 flex items-center justify-between">
    <div class="flex items-center space-x-3">
      <span class="text-2xl">🏆</span>
      <span class="text-xl font-bold">Tournament OS</span>
    </div>
    <div class="flex items-center space-x-4">
      <span class="text-gray-400 text-sm">Organizer Dashboard</span>
      <button onclick="setToken()" class="bg-indigo-600 px-4 py-2 rounded-lg text-sm hover:bg-indigo-700">
        Set API Token
      </button>
    </div>
  </nav>

  <div class="max-w-7xl mx-auto px-6 py-8">
    <div class="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8" id="stats-cards">
      <div class="bg-gray-800 rounded-xl p-6">
        <div class="text-gray-400 text-sm">Total Registrations</div>
        <div class="text-3xl font-bold mt-2" id="stat-registrations">—</div>
      </div>
      <div class="bg-gray-800 rounded-xl p-6">
        <div class="text-gray-400 text-sm">Teams</div>
        <div class="text-3xl font-bold mt-2" id="stat-teams">—</div>
      </div>
      <div class="bg-gray-800 rounded-xl p-6">
        <div class="text-gray-400 text-sm">Matches</div>
        <div class="text-3xl font-bold mt-2" id="stat-matches">—</div>
      </div>
      <div class="bg-gray-800 rounded-xl p-6">
        <div class="text-gray-400 text-sm">Open Disputes</div>
        <div class="text-3xl font-bold mt-2" id="stat-disputes">—</div>
      </div>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <div class="bg-gray-800 rounded-xl p-6">
        <h2 class="text-lg font-semibold mb-4">Tournaments</h2>
        <div id="tournaments-list" class="space-y-3">
          <div class="text-gray-500 text-sm">Enter your API token and tournament details to load data.</div>
        </div>
      </div>
      <div class="bg-gray-800 rounded-xl p-6">
        <h2 class="text-lg font-semibold mb-4">Quick Actions</h2>
        <div class="space-y-3">
          <div>
            <label class="text-sm text-gray-400">Organization ID</label>
            <input id="org-id" type="text" placeholder="org-uuid" class="w-full mt-1 bg-gray-700 rounded px-3 py-2 text-sm">
          </div>
          <div>
            <label class="text-sm text-gray-400">Tournament ID</label>
            <input id="tournament-id" type="text" placeholder="tournament-uuid" class="w-full mt-1 bg-gray-700 rounded px-3 py-2 text-sm">
          </div>
          <button onclick="loadAnalytics()" class="w-full bg-indigo-600 py-2 rounded-lg hover:bg-indigo-700 text-sm font-medium">
            Load Analytics
          </button>
          <button onclick="loadTournaments()" class="w-full bg-gray-700 py-2 rounded-lg hover:bg-gray-600 text-sm font-medium">
            List Tournaments
          </button>
        </div>
      </div>
    </div>

    <div class="mt-6 bg-gray-800 rounded-xl p-6">
      <h2 class="text-lg font-semibold mb-4">Pending Registrations</h2>
      <div id="registrations-list" class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead class="text-gray-400 border-b border-gray-700">
            <tr>
              <th class="text-left py-2">ID</th>
              <th class="text-left py-2">Status</th>
              <th class="text-left py-2">Flags</th>
              <th class="text-left py-2">Submitted</th>
              <th class="text-left py-2">Actions</th>
            </tr>
          </thead>
          <tbody id="reg-tbody">
            <tr><td colspan="5" class="text-gray-500 py-4">No data loaded.</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <script>
    let API_TOKEN = localStorage.getItem('tos_token') || '';

    function setToken() {
      const t = prompt('Enter your Admin API Token:', API_TOKEN);
      if (t !== null) { API_TOKEN = t; localStorage.setItem('tos_token', t); }
    }

    function headers() {
      return { 'Authorization': 'Bearer ' + API_TOKEN, 'Content-Type': 'application/json' };
    }

    async function loadAnalytics() {
      const orgId = document.getElementById('org-id').value;
      const tId = document.getElementById('tournament-id').value;
      if (!orgId || !tId) { alert('Enter Organization ID and Tournament ID'); return; }
      try {
        const r = await fetch(`/api/dashboard/tournaments/${tId}/analytics?organization_id=${orgId}`, { headers: headers() });
        const d = await r.json();
        document.getElementById('stat-registrations').textContent = d.registrations?.total ?? '—';
        document.getElementById('stat-teams').textContent = d.teams?.total ?? '—';
        document.getElementById('stat-matches').textContent = d.matches?.total ?? '—';
        document.getElementById('stat-disputes').textContent = d.disputes?.total ?? '—';
        loadRegistrations(orgId, tId, 'pending');
      } catch(e) { alert('Error: ' + e.message); }
    }

    async function loadTournaments() {
      const orgId = document.getElementById('org-id').value;
      if (!orgId) { alert('Enter Organization ID'); return; }
      try {
        const r = await fetch(`/api/dashboard/tournaments?organization_id=${orgId}`, { headers: headers() });
        const d = await r.json();
        const list = document.getElementById('tournaments-list');
        if (!d.tournaments?.length) { list.innerHTML = '<div class="text-gray-500 text-sm">No tournaments found.</div>'; return; }
        list.innerHTML = d.tournaments.map(t => `
          <div class="flex items-center justify-between bg-gray-700 rounded-lg px-4 py-3">
            <div>
              <div class="font-medium">${t.name}</div>
              <div class="text-xs text-gray-400">${t.game} · ${t.format} · ${t.status}</div>
            </div>
            <span class="text-xs bg-indigo-600 px-2 py-1 rounded">${t.status}</span>
          </div>
        `).join('');
      } catch(e) { alert('Error: ' + e.message); }
    }

    async function loadRegistrations(orgId, tId, status) {
      try {
        const r = await fetch(`/api/dashboard/tournaments/${tId}/registrations?organization_id=${orgId}&status=${status}&limit=20`, { headers: headers() });
        const d = await r.json();
        const tbody = document.getElementById('reg-tbody');
        if (!d.registrations?.length) { tbody.innerHTML = '<tr><td colspan="5" class="text-gray-500 py-4">No pending registrations.</td></tr>'; return; }
        tbody.innerHTML = d.registrations.map(reg => `
          <tr class="border-b border-gray-700">
            <td class="py-2 font-mono text-xs">${reg.id.substring(0,8)}</td>
            <td class="py-2"><span class="bg-yellow-600 px-2 py-0.5 rounded text-xs">${reg.status}</span></td>
            <td class="py-2">${reg.flags}</td>
            <td class="py-2 text-gray-400 text-xs">${new Date(reg.created_at).toLocaleDateString()}</td>
            <td class="py-2 space-x-2">
              <button onclick="reviewReg('${reg.id}','${orgId}','${tId}','approve')" class="text-xs bg-green-700 px-2 py-1 rounded hover:bg-green-600">Approve</button>
              <button onclick="reviewReg('${reg.id}','${orgId}','${tId}','reject')" class="text-xs bg-red-700 px-2 py-1 rounded hover:bg-red-600">Reject</button>
            </td>
          </tr>
        `).join('');
      } catch(e) { console.error(e); }
    }

    async function reviewReg(regId, orgId, tId, action) {
      let reason = '';
      if (action === 'reject') { reason = prompt('Rejection reason:'); if (!reason) return; }
      try {
        const r = await fetch(`/api/dashboard/tournaments/${tId}/registrations/${regId}/action?organization_id=${orgId}`, {
          method: 'POST', headers: headers(),
          body: JSON.stringify({ action, reviewer_id: 'dashboard', reason })
        });
        const d = await r.json();
        if (d.success) { alert(action + ' successful'); loadRegistrations(orgId, tId, 'pending'); }
      } catch(e) { alert('Error: ' + e.message); }
    }
  </script>
</body>
</html>"""


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "web_main:app",
        host=settings.web_host,
        port=settings.effective_port,
        reload=not settings.is_production,
        log_level=settings.log_level.lower(),
    )
