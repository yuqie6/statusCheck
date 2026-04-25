from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.clients.sub2api import Sub2ApiClient
from app.config import Settings, get_settings
from app.services.dashboard import DashboardService, utc_now_iso

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    client = Sub2ApiClient(settings)
    service = DashboardService(settings, client)
    stop_event = asyncio.Event()
    app.state.settings = settings
    app.state.sub2api_client = client
    app.state.dashboard_service = service
    app.state.dashboard_refresh_stop_event = stop_event
    refresh_task: asyncio.Task | None = None
    try:
        try:
            await service.refresh_dashboard()
        except Exception:
            logger.exception("initial dashboard refresh failed")
        refresh_task = asyncio.create_task(service.run_refresh_loop(stop_event))
        app.state.dashboard_refresh_task = refresh_task
        yield
    finally:
        stop_event.set()
        if refresh_task:
            refresh_task.cancel()
            try:
                await refresh_task
            except asyncio.CancelledError:
                pass
        await client.aclose()


app = FastAPI(title="Sub2API Status Check", version="0.1.0", lifespan=lifespan)
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/healthz")
async def healthz(request: Request) -> dict[str, str | bool]:
    settings: Settings = request.app.state.settings
    return {
        "status": "ok",
        "app": settings.app_name,
        "env": settings.app_env,
        "generated_at": utc_now_iso(),
        "monitor_probe_enabled": bool(
            (settings.sub2api_monitor_api_key or "").strip()
            or settings.sub2api_monitor_group_api_keys
        ),
        "account_scan_enabled": settings.account_scan_enabled,
    }


@app.get("/api/dashboard")
async def dashboard(request: Request) -> dict:
    service: DashboardService = request.app.state.dashboard_service
    try:
        return await service.get_dashboard()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


frontend_dist = Path("frontend/dist")
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="frontend-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str) -> FileResponse:  # pragma: no cover - thin file responder
        index_file = frontend_dist / "index.html"
        if full_path.startswith("api/"):
            return FileResponse(index_file)
        return FileResponse(index_file)
