from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.clients.sub2api import Sub2ApiError
from app.config import Settings, get_settings
from app.services.dashboard import DashboardService, as_int, utc_now_iso

router = APIRouter(prefix="/api/admin", tags=["admin"])
security = HTTPBearer(auto_error=False)

ADMIN_ENV_KEYS = [
    "SUB2API_GROUP_IDS",
    "SUB2API_INCLUDE_EXCLUSIVE_GROUPS",
    "DASHBOARD_CACHE_TTL_SECONDS",
    "ACCOUNT_SCAN_ENABLED",
    "ACCOUNT_SCAN_TTL_SECONDS",
    "ACCOUNT_SCAN_PAGE_SIZE",
    "ACCOUNT_SCAN_MAX_PAGES",
    "SUB2API_MONITOR_API_KEY",
    "SUB2API_MONITOR_GROUP_API_KEYS",
    "SUB2API_MONITOR_MODELS",
    "SUB2API_MONITOR_MODEL_SOURCES",
    "SUB2API_MONITOR_USAGE_MODEL_LIMIT",
    "SUB2API_MONITOR_TIMEOUT_SECONDS",
    "SUB2API_MONITOR_MAX_TOKENS",
    "SUB2API_MONITOR_TEMPERATURE",
    "SUB2API_MONITOR_PROMPT",
    "SUB2API_MONITOR_CONCURRENCY",
    "SUB2API_MONITOR_PROBE_ENDPOINT",
]


class AdminConfigPayload(BaseModel):
    sub2api_group_ids: list[int] = Field(default_factory=list)
    sub2api_include_exclusive_groups: bool = False
    dashboard_cache_ttl_seconds: int = Field(60, ge=5, le=3600)
    account_scan_enabled: bool = False
    account_scan_ttl_seconds: int = Field(180, ge=30, le=86400)
    account_scan_page_size: int = Field(100, ge=1, le=500)
    account_scan_max_pages: int = Field(0, ge=0, le=10000)
    sub2api_monitor_api_key: str = ""
    sub2api_monitor_group_api_keys: str = ""
    sub2api_monitor_models: list[str] = Field(default_factory=list)
    sub2api_monitor_model_sources: list[Literal["groups", "configured", "usage", "catalog"]] = Field(
        default_factory=lambda: ["groups", "configured"]
    )
    sub2api_monitor_usage_model_limit: int = Field(10, ge=1, le=200)
    sub2api_monitor_timeout_seconds: float = Field(18.0, ge=1, le=180)
    sub2api_monitor_max_tokens: int = Field(8, ge=1, le=4096)
    sub2api_monitor_temperature: float = Field(0.0, ge=0, le=2)
    sub2api_monitor_prompt: str = Field("Reply with OK only.", min_length=1, max_length=2000)
    sub2api_monitor_concurrency: int = Field(3, ge=1, le=50)
    sub2api_monitor_probe_endpoint: Literal["chat_completions", "responses"] = "chat_completions"


class AdminConfigResponse(BaseModel):
    config: AdminConfigPayload
    available_groups: list[dict[str, Any]]
    env_file: str
    generated_at: str


def _admin_token(settings: Settings) -> str:
    return (settings.admin_token or "").strip()


async def require_admin(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> None:
    settings: Settings = request.app.state.settings
    configured_token = _admin_token(settings)
    if not configured_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="未配置 ADMIN_TOKEN，admin 页面已禁用。",
        )

    provided_token = ""
    if credentials and credentials.scheme.lower() == "bearer":
        provided_token = credentials.credentials.strip()
    if not provided_token:
        provided_token = (request.headers.get("x-admin-token") or "").strip()

    if provided_token != configured_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="admin token 无效")


def _env_path() -> Path:
    return Path(os.environ.get("STATUSCHECK_ENV_FILE", ".env"))


def _bool_env(value: bool) -> str:
    return "true" if value else "false"


def _join_ints(values: list[int]) -> str:
    return ",".join(str(value) for value in values)


def _join_strings(values: list[str]) -> str:
    return ",".join(value.strip() for value in values if value.strip())


def _group_keys_to_env(value: dict[int, str]) -> str:
    return ",".join(f"{group_id}={api_key}" for group_id, api_key in sorted(value.items()))


def _normalize_group_key_text(value: str) -> str:
    parts: list[str] = []
    for raw_item in value.replace("\n", ",").split(","):
        item = raw_item.split("#", 1)[0].strip()
        if item:
            parts.append(item)
    return ",".join(parts)


def _config_from_settings(settings: Settings) -> AdminConfigPayload:
    return AdminConfigPayload(
        sub2api_group_ids=list(settings.sub2api_group_ids),
        sub2api_include_exclusive_groups=settings.sub2api_include_exclusive_groups,
        dashboard_cache_ttl_seconds=settings.dashboard_cache_ttl_seconds,
        account_scan_enabled=settings.account_scan_enabled,
        account_scan_ttl_seconds=settings.account_scan_ttl_seconds,
        account_scan_page_size=settings.account_scan_page_size,
        account_scan_max_pages=settings.account_scan_max_pages,
        sub2api_monitor_api_key=settings.sub2api_monitor_api_key or "",
        sub2api_monitor_group_api_keys=_group_keys_to_env(settings.sub2api_monitor_group_api_keys),
        sub2api_monitor_models=list(settings.sub2api_monitor_models),
        sub2api_monitor_model_sources=list(settings.sub2api_monitor_model_sources),
        sub2api_monitor_usage_model_limit=settings.sub2api_monitor_usage_model_limit,
        sub2api_monitor_timeout_seconds=settings.sub2api_monitor_timeout_seconds,
        sub2api_monitor_max_tokens=settings.sub2api_monitor_max_tokens,
        sub2api_monitor_temperature=settings.sub2api_monitor_temperature,
        sub2api_monitor_prompt=settings.sub2api_monitor_prompt,
        sub2api_monitor_concurrency=settings.sub2api_monitor_concurrency,
        sub2api_monitor_probe_endpoint=settings.sub2api_monitor_probe_endpoint,
    )


def _env_updates_from_payload(payload: AdminConfigPayload) -> dict[str, str]:
    return {
        "SUB2API_GROUP_IDS": _join_ints(payload.sub2api_group_ids),
        "SUB2API_INCLUDE_EXCLUSIVE_GROUPS": _bool_env(payload.sub2api_include_exclusive_groups),
        "DASHBOARD_CACHE_TTL_SECONDS": str(payload.dashboard_cache_ttl_seconds),
        "ACCOUNT_SCAN_ENABLED": _bool_env(payload.account_scan_enabled),
        "ACCOUNT_SCAN_TTL_SECONDS": str(payload.account_scan_ttl_seconds),
        "ACCOUNT_SCAN_PAGE_SIZE": str(payload.account_scan_page_size),
        "ACCOUNT_SCAN_MAX_PAGES": str(payload.account_scan_max_pages),
        "SUB2API_MONITOR_API_KEY": payload.sub2api_monitor_api_key.strip(),
        "SUB2API_MONITOR_GROUP_API_KEYS": _normalize_group_key_text(payload.sub2api_monitor_group_api_keys),
        "SUB2API_MONITOR_MODELS": _join_strings(payload.sub2api_monitor_models),
        "SUB2API_MONITOR_MODEL_SOURCES": _join_strings(list(payload.sub2api_monitor_model_sources)),
        "SUB2API_MONITOR_USAGE_MODEL_LIMIT": str(payload.sub2api_monitor_usage_model_limit),
        "SUB2API_MONITOR_TIMEOUT_SECONDS": str(payload.sub2api_monitor_timeout_seconds),
        "SUB2API_MONITOR_MAX_TOKENS": str(payload.sub2api_monitor_max_tokens),
        "SUB2API_MONITOR_TEMPERATURE": str(payload.sub2api_monitor_temperature),
        "SUB2API_MONITOR_PROMPT": payload.sub2api_monitor_prompt.replace("\n", " ").strip(),
        "SUB2API_MONITOR_CONCURRENCY": str(payload.sub2api_monitor_concurrency),
        "SUB2API_MONITOR_PROBE_ENDPOINT": payload.sub2api_monitor_probe_endpoint,
    }


def _format_env_line(key: str, value: str) -> str:
    cleaned = value.replace("\r", "").replace("\n", " ")
    if cleaned == "":
        return f"{key}="
    if cleaned != cleaned.strip() or "#" in cleaned or "\"" in cleaned:
        escaped = cleaned.replace("\\", "\\\\").replace('"', '\\"')
        return f'{key}="{escaped}"'
    return f"{key}={cleaned}"


def _write_env_file(path: Path, updates: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    next_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            next_lines.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in updates:
            next_lines.append(_format_env_line(key, updates[key]))
            seen.add(key)
        else:
            next_lines.append(line)

    missing = [key for key in ADMIN_ENV_KEYS if key in updates and key not in seen]
    if missing:
        if next_lines and next_lines[-1].strip():
            next_lines.append("")
        next_lines.append("# Admin-managed runtime monitor config")
        for key in missing:
            next_lines.append(_format_env_line(key, updates[key]))

    path.write_text("\n".join(next_lines).rstrip() + "\n", encoding="utf-8")


def _apply_process_env(updates: dict[str, str]) -> None:
    for key, value in updates.items():
        os.environ[key] = value


async def _available_groups(request: Request) -> list[dict[str, Any]]:
    client = request.app.state.sub2api_client
    try:
        payload = await client.get_groups(page_size=500)
    except Sub2ApiError:
        return []
    groups = []
    for group in payload.get("items", []):
        group_id = as_int(group.get("id"))
        if group_id is None:
            continue
        groups.append(
            {
                "id": group_id,
                "name": group.get("name") or str(group_id),
                "platform": group.get("platform") or "-",
                "status": group.get("status") or "-",
                "is_exclusive": bool(group.get("is_exclusive")),
                "account_count": as_int(group.get("account_count")) or 0,
                "default_model": group.get("default_mapped_model") or "-",
            }
        )
    return sorted(groups, key=lambda item: (item["id"], item["name"]))


@router.get("/config", response_model=AdminConfigResponse)
async def get_admin_config(request: Request, _: Annotated[None, Depends(require_admin)]) -> AdminConfigResponse:
    settings: Settings = request.app.state.settings
    return AdminConfigResponse(
        config=_config_from_settings(settings),
        available_groups=await _available_groups(request),
        env_file=str(_env_path()),
        generated_at=utc_now_iso(),
    )


@router.put("/config", response_model=AdminConfigResponse)
async def update_admin_config(
    payload: AdminConfigPayload,
    request: Request,
    _: Annotated[None, Depends(require_admin)],
) -> AdminConfigResponse:
    updates = _env_updates_from_payload(payload)
    _write_env_file(_env_path(), updates)
    _apply_process_env(updates)

    get_settings.cache_clear()
    new_settings = get_settings()
    request.app.state.settings = new_settings
    request.app.state.sub2api_client.settings = new_settings

    service: DashboardService = request.app.state.dashboard_service
    service.settings = new_settings
    service.cache = type(service.cache)()
    try:
        await service.refresh_dashboard()
    except Exception:
        # 保存配置本身已经成功；下一轮自动刷新会继续重试。
        pass

    return AdminConfigResponse(
        config=_config_from_settings(new_settings),
        available_groups=await _available_groups(request),
        env_file=str(_env_path()),
        generated_at=utc_now_iso(),
    )
