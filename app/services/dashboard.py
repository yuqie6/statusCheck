from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from app.clients.sub2api import Sub2ApiClient, Sub2ApiError
from app.config import Settings

logger = logging.getLogger(__name__)


class TTLCache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def get_or_set(
        self,
        key: str,
        ttl_seconds: int,
        factory: Callable[[], Any],
        *,
        force_refresh: bool = False,
    ) -> Any:
        now = time.monotonic()
        if not force_refresh:
            cached = self._store.get(key)
            if cached and cached[0] > now:
                return cached[1]

        async with self._locks[key]:
            now = time.monotonic()
            if not force_refresh:
                cached = self._store.get(key)
                if cached and cached[0] > now:
                    return cached[1]
            value = await factory()
            self._store[key] = (now + ttl_seconds, value)
            return value


def utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


def as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class DashboardService:
    def __init__(self, settings: Settings, client: Sub2ApiClient) -> None:
        self.settings = settings
        self.client = client
        self.cache = TTLCache()
        self._dashboard_snapshot: dict[str, Any] | None = None
        self._dashboard_lock = asyncio.Lock()
        self._dashboard_ready = asyncio.Event()
        self._last_refresh_started_at: str | None = None
        self._last_refresh_finished_at: str | None = None
        self._last_refresh_error: str | None = None

    async def get_dashboard(self) -> dict[str, Any]:
        if self._dashboard_snapshot is None:
            raise RuntimeError(self._last_refresh_error or "dashboard snapshot not ready")
        return self._dashboard_snapshot

    async def refresh_dashboard(self) -> dict[str, Any]:
        async with self._dashboard_lock:
            self._last_refresh_started_at = utc_now_iso()
            try:
                snapshot = await self._build_dashboard()
            except Exception as exc:
                self._last_refresh_error = str(exc)
                logger.exception("dashboard refresh failed")
                raise

            self._dashboard_snapshot = snapshot
            self._dashboard_ready.set()
            self._last_refresh_error = None
            self._last_refresh_finished_at = utc_now_iso()
            return snapshot

    async def run_refresh_loop(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            interval = max(self.settings.dashboard_cache_ttl_seconds, 5)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
                break
            except TimeoutError:
                pass

            try:
                await self.refresh_dashboard()
            except Exception:
                logger.exception("background dashboard refresh failed")

    async def _build_dashboard(self) -> dict[str, Any]:
        groups_payload = await self.client.get_groups()
        scoped_groups, group_scope = self._scope_groups(groups_payload)
        scoped_group_ids = [int(group["id"]) for group in scoped_groups.get("items", [])]

        admin_started = time.perf_counter()
        snapshot, stats, group_capacity, group_usage = await asyncio.gather(
            self.client.get_dashboard_snapshot(),
            self.client.get_dashboard_stats(),
            self.client.get_group_capacity(),
            self.client.get_group_usage_summary(),
        )
        admin_latency_ms = round((time.perf_counter() - admin_started) * 1000)

        availability_started = time.perf_counter()
        availability, realtime, ops_overview = await asyncio.gather(
            self._get_scoped_availability(group_ids=scoped_group_ids, scoped=group_scope["enabled"]),
            self._get_scoped_realtime(group_ids=scoped_group_ids, scoped=group_scope["enabled"]),
            self._get_scoped_ops_overview(group_ids=scoped_group_ids, scoped=group_scope["enabled"]),
        )
        availability_latency_ms = round((time.perf_counter() - availability_started) * 1000)

        quota_estimate = await self._get_quota_estimate()
        model_groups, probe_meta = await self._get_model_probe_data(
            snapshot=snapshot,
            groups=scoped_groups.get("items", []),
        )

        data = self._compose_dashboard(
            snapshot=snapshot,
            stats=stats,
            realtime=realtime,
            ops_overview=ops_overview,
            groups=scoped_groups,
            group_capacity=self._filter_group_rows(group_capacity, scoped_group_ids, group_scope["enabled"]),
            group_usage=self._filter_group_rows(group_usage, scoped_group_ids, group_scope["enabled"]),
            availability=availability,
            quota_estimate=quota_estimate,
            model_groups=model_groups,
            probe_meta=probe_meta,
            admin_latency_ms=admin_latency_ms,
            availability_latency_ms=availability_latency_ms,
            group_scope=group_scope,
        )
        return data

    def _scope_groups(self, groups_payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        all_groups = list(groups_payload.get("items", []))
        active_groups = [group for group in all_groups if group.get("status") == "active"]
        explicit_group_ids = set(self.settings.sub2api_group_ids)

        if explicit_group_ids:
            selected_groups = [
                group for group in active_groups if as_int(group.get("id")) in explicit_group_ids
            ]
        elif self.settings.sub2api_include_exclusive_groups:
            selected_groups = active_groups
        else:
            selected_groups = [group for group in active_groups if not bool(group.get("is_exclusive"))]

        scoped_payload = dict(groups_payload)
        scoped_payload["items"] = selected_groups
        scoped_payload["total"] = len(selected_groups)
        scoped_payload["page"] = 1
        scoped_payload["page_size"] = len(selected_groups) or groups_payload.get("page_size", 0)
        scoped_payload["pages"] = 1 if selected_groups else 0

        scope_enabled = bool(explicit_group_ids) or len(selected_groups) != len(active_groups)
        return scoped_payload, {
            "enabled": scope_enabled,
            "group_ids": [int(group["id"]) for group in selected_groups if group.get("id") is not None],
            "group_names": [group.get("name") or str(group.get("id")) for group in selected_groups],
            "explicit_ids": sorted(explicit_group_ids),
            "include_exclusive_groups": self.settings.sub2api_include_exclusive_groups,
        }

    def _filter_group_rows(
        self,
        rows: list[dict[str, Any]],
        group_ids: list[int],
        enabled: bool,
    ) -> list[dict[str, Any]]:
        if not enabled:
            return rows
        selected = set(group_ids)
        return [row for row in rows if as_int(row.get("group_id")) in selected]

    async def _get_scoped_availability(
        self, *, group_ids: list[int], scoped: bool
    ) -> dict[str, Any]:
        if not scoped:
            return await self.client.get_account_availability()
        if not group_ids:
            return {
                "enabled": True,
                "timestamp": utc_now_iso(),
                "group": {},
                "platform": {},
                "account_summary": {
                    "total_accounts": 0,
                    "available_count": 0,
                    "rate_limit_count": 0,
                    "error_count": 0,
                    "overload_count": 0,
                },
            }

        payloads = await asyncio.gather(
            *(self.client.get_account_availability(group_id=group_id) for group_id in group_ids)
        )
        return self._merge_availability_payloads(payloads)

    async def _get_scoped_realtime(
        self, *, group_ids: list[int], scoped: bool
    ) -> dict[str, Any]:
        if not scoped:
            return await self.client.get_dashboard_realtime()
        if not group_ids:
            return {
                "active_requests": 0,
                "requests_per_minute": 0,
                "average_response_time": 0,
                "error_rate": 0,
            }

        payloads = await asyncio.gather(
            *(self.client.get_dashboard_realtime(group_id=group_id) for group_id in group_ids)
        )
        total_weight = 0
        avg_response_time_weighted = 0.0
        for payload in payloads:
            weight = (as_int(payload.get("requests_per_minute")) or 0) + (
                as_int(payload.get("active_requests")) or 0
            )
            if weight <= 0:
                continue
            total_weight += weight
            avg_response_time_weighted += (as_float(payload.get("average_response_time")) or 0.0) * weight

        return {
            "active_requests": sum(as_int(payload.get("active_requests")) or 0 for payload in payloads),
            "requests_per_minute": sum(
                as_int(payload.get("requests_per_minute")) or 0 for payload in payloads
            ),
            "average_response_time": round(
                avg_response_time_weighted / total_weight, 2
            )
            if total_weight
            else 0.0,
            "error_rate": round(
                max((as_float(payload.get("error_rate")) or 0.0) for payload in payloads),
                4,
            )
            if payloads
            else 0.0,
        }

    async def _get_scoped_ops_overview(
        self, *, group_ids: list[int], scoped: bool
    ) -> dict[str, Any]:
        if not scoped:
            return await self.client.get_ops_overview()
        if not group_ids:
            return {
                "health_score": 0,
                "sla": 0.0,
                "error_rate": 0.0,
                "success_count": 0,
                "error_count_total": 0,
                "request_count_total": 0,
                "upstream_error_rate": 0.0,
                "upstream_error_count_excl_429_529": 0,
                "duration": {},
                "qps": {"current": 0.0, "avg": 0.0, "peak": 0.0},
                "tps": {"current": 0.0, "avg": 0.0, "peak": 0.0},
            }

        payloads = await asyncio.gather(
            *(self.client.get_ops_overview(group_id=group_id) for group_id in group_ids)
        )
        return self._merge_ops_overviews(payloads, group_ids=group_ids)

    async def _get_quota_estimate(self) -> dict[str, Any]:
        if not self.settings.account_scan_enabled:
            return {
                "enabled": False,
                "coverage_accounts": 0,
                "coverage_ratio": 0,
                "limit_usd": None,
                "used_usd": None,
                "remaining_usd": None,
                "note": "未启用慢速账号扫描，显式额度估算关闭。",
            }

        async def factory() -> dict[str, Any]:
            total_accounts = 0
            covered_accounts = 0
            total_limit = 0.0
            total_used = 0.0
            async for account in self.client.iter_accounts(
                page_size=self.settings.account_scan_page_size,
                max_pages=self.settings.account_scan_max_pages,
            ):
                total_accounts += 1
                limit, used = self._extract_explicit_quota(account)
                if limit is None or used is None:
                    continue
                covered_accounts += 1
                total_limit += limit
                total_used += used

            remaining = max(total_limit - total_used, 0.0)
            coverage_ratio = covered_accounts / total_accounts if total_accounts else 0.0
            return {
                "enabled": True,
                "coverage_accounts": covered_accounts,
                "coverage_ratio": coverage_ratio,
                "limit_usd": round(total_limit, 4),
                "used_usd": round(total_used, 4),
                "remaining_usd": round(remaining, 4),
                "note": "仅统计带显式额度字段的账号（如 quota_limit、window_cost_limit）。",
            }

        return await self.cache.get_or_set(
            "quota_estimate",
            self.settings.account_scan_ttl_seconds,
            factory,
        )

    async def _get_model_probe_data(
        self,
        *,
        snapshot: dict[str, Any],
        groups: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        probe_targets = self._resolve_probe_targets(groups)
        configured_target_ids = {target["group_id"] for target in probe_targets}
        probe_meta = {
            "configured": bool(probe_targets),
            "configured_groups": [
                {"id": target["group_id"], "name": target["group_name"]}
                for target in probe_targets
            ],
            "missing_groups": [
                {"id": group["id"], "name": group["name"]}
                for group in groups
                if int(group["id"]) not in configured_target_ids
            ],
        }

        group_sections = []
        probe_key_by_group = {target["group_id"]: target["api_key"] for target in probe_targets}
        for group in groups:
            group_id = int(group["id"])
            group_sections.append(
                {
                    "group_id": group_id,
                    "group_name": group.get("name") or str(group_id),
                    "group": group,
                    "api_key": probe_key_by_group.get(group_id),
                    "monitored_models": set(),
                    "catalog": None,
                    "probes": {},
                }
            )
        sections_by_group_id = {section["group_id"]: section for section in group_sections}

        if not group_sections:
            return [], probe_meta

        semaphore = asyncio.Semaphore(self.settings.sub2api_monitor_concurrency)

        async def fetch_catalog_for_section(section: dict[str, Any]) -> list[dict[str, Any]]:
            if not section.get("api_key"):
                return []
            try:
                return await self.client.get_public_model_catalog(api_key=section["api_key"])
            except Sub2ApiError:
                return []

        catalog_payloads = await asyncio.gather(
            *(fetch_catalog_for_section(section) for section in group_sections)
        )

        for section, catalog_items in zip(group_sections, catalog_payloads, strict=False):
            section["catalog"] = {item.get("id"): True for item in catalog_items if item.get("id")} or None
            section["monitored_models"] = self._resolve_monitored_models(
                snapshot=snapshot,
                groups=[section["group"]],
                catalog_items=catalog_items,
            )

        async def run_probe(section: dict[str, Any], model_name: str) -> tuple[int, str, dict[str, Any]]:
            async with semaphore:
                result = await self.client.probe_model(model_name, api_key=section["api_key"])
                return section["group_id"], model_name, result

        probe_tasks = []
        for section in group_sections:
            if not section.get("api_key"):
                continue
            for model_name in sorted(section["monitored_models"]):
                probe_tasks.append(run_probe(section, model_name))

        if probe_tasks:
            for group_id, model_name, result in await asyncio.gather(*probe_tasks):
                section = sections_by_group_id[group_id]
                section["probes"][model_name] = result
        return group_sections, probe_meta

    def _resolve_probe_targets(self, groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
        group_key_map = self.settings.sub2api_monitor_group_api_keys
        targets: list[dict[str, Any]] = []

        use_fallback_key = (
            bool(self.settings.sub2api_monitor_api_key)
            and not group_key_map
            and len(groups) == 1
        )

        for group in groups:
            group_id = int(group["id"])
            api_key = group_key_map.get(group_id)
            if not api_key and use_fallback_key:
                api_key = self.settings.sub2api_monitor_api_key
            if not api_key:
                continue
            targets.append(
                {
                    "group_id": group_id,
                    "group_name": group.get("name") or str(group_id),
                    "group": group,
                    "api_key": api_key,
                }
            )
        return targets

    def _compose_dashboard(
        self,
        *,
        snapshot: dict[str, Any],
        stats: dict[str, Any],
        realtime: dict[str, Any],
        ops_overview: dict[str, Any],
        groups: dict[str, Any],
        group_capacity: list[dict[str, Any]],
        group_usage: list[dict[str, Any]],
        availability: dict[str, Any],
        quota_estimate: dict[str, Any],
        model_groups: list[dict[str, Any]],
        probe_meta: dict[str, Any],
        admin_latency_ms: int,
        availability_latency_ms: int,
        group_scope: dict[str, Any],
    ) -> dict[str, Any]:
        snapshot_stats = snapshot.get("stats", {})
        trend = snapshot.get("trend", [])
        model_usage = snapshot.get("models", [])

        availability_groups = {
            int(group_id): payload for group_id, payload in (availability.get("group") or {}).items()
        }
        availability_platforms = list((availability.get("platform") or {}).values())
        availability_account_summary = availability.get("account_summary") or {}
        capacity_by_group = {int(item["group_id"]): item for item in group_capacity}
        usage_by_group = {int(item["group_id"]): item for item in group_usage}

        total_accounts = (
            as_int(availability_account_summary.get("total_accounts"))
            if group_scope["enabled"]
            else None
        )
        if total_accounts is None:
            total_accounts = (
                as_int(snapshot_stats.get("total_accounts")) or as_int(stats.get("total_accounts")) or 0
            )

        available_accounts = (
            as_int(availability_account_summary.get("available_count"))
            if group_scope["enabled"]
            else None
        )
        if available_accounts is None:
            available_accounts = sum(item.get("available_count", 0) for item in availability_groups.values())

        rate_limited_accounts = (
            as_int(availability_account_summary.get("rate_limit_count"))
            if group_scope["enabled"]
            else None
        )
        if rate_limited_accounts is None:
            rate_limited_accounts = as_int(snapshot_stats.get("ratelimit_accounts")) or 0

        error_accounts = (
            as_int(availability_account_summary.get("error_count"))
            if group_scope["enabled"]
            else None
        )
        if error_accounts is None:
            error_accounts = as_int(snapshot_stats.get("error_accounts")) or 0

        overload_accounts = (
            as_int(availability_account_summary.get("overload_count"))
            if group_scope["enabled"]
            else None
        )
        if overload_accounts is None:
            overload_accounts = as_int(snapshot_stats.get("overload_accounts")) or 0

        capacity_used = sum(as_int(item.get("concurrency_used")) or 0 for item in group_capacity)
        capacity_max = sum(as_int(item.get("concurrency_max")) or 0 for item in group_capacity)
        capacity_utilization = capacity_used / capacity_max if capacity_max else 0.0
        scoped_today_cost = round(
            sum(as_float(item.get("today_cost")) or 0.0 for item in group_usage),
            4,
        )
        scoped_total_cost = round(
            sum(as_float(item.get("total_cost")) or 0.0 for item in group_usage),
            4,
        )

        groups_view = []
        for group in groups.get("items", []):
            group_id = int(group["id"])
            availability_group = availability_groups.get(group_id, {})
            capacity = capacity_by_group.get(group_id, {})
            usage = usage_by_group.get(group_id, {})
            rate_limited = as_int(availability_group.get("rate_limit_count"))
            if rate_limited is None:
                rate_limited = as_int(group.get("rate_limited_account_count")) or 0
            group_total = as_int(group.get("account_count")) or 0
            group_available = as_int(availability_group.get("available_count"))
            if group_available is None:
                active_count = as_int(group.get("active_account_count")) or 0
                group_available = max(active_count - rate_limited, 0)
            error_count = as_int(availability_group.get("error_count")) or 0
            groups_view.append(
                {
                    "id": group_id,
                    "name": group.get("name"),
                    "platform": group.get("platform"),
                    "default_model": group.get("default_mapped_model") or "-",
                    "account_count": group_total,
                    "available_count": group_available,
                    "rate_limited_count": rate_limited,
                    "error_count": error_count,
                    "concurrency_used": as_int(capacity.get("concurrency_used")) or 0,
                    "concurrency_max": as_int(capacity.get("concurrency_max")) or 0,
                    "today_cost": round(as_float(usage.get("today_cost")) or 0.0, 4),
                    "total_cost": round(as_float(usage.get("total_cost")) or 0.0, 4),
                    "sort_order": as_int(group.get("sort_order")) or 0,
                    "status": self._classify_group_status(
                        total=group_total,
                        available=group_available,
                        rate_limited=rate_limited,
                        error_count=error_count,
                    ),
                }
            )
        groups_view.sort(key=lambda item: (item["sort_order"], item["name"]))

        platform_view = []
        for platform in availability_platforms:
            total = as_int(platform.get("total_accounts")) or 0
            available = as_int(platform.get("available_count")) or 0
            rate_limited = as_int(platform.get("rate_limit_count")) or 0
            errors = as_int(platform.get("error_count")) or 0
            platform_view.append(
                {
                    "platform": platform.get("platform"),
                    "total_accounts": total,
                    "available_count": available,
                    "rate_limited_count": rate_limited,
                    "error_count": errors,
                    "availability_ratio": round(available / total, 4) if total else 0,
                }
            )
        platform_view.sort(key=lambda item: item["platform"])

        model_group_sections, model_rows = self._build_group_model_sections(
            model_usage=model_usage,
            model_groups=model_groups,
        )
        insights = self._build_insights(
            total_accounts=total_accounts,
            available_accounts=available_accounts,
            rate_limited_accounts=rate_limited_accounts,
            error_accounts=error_accounts,
            capacity_utilization=capacity_utilization,
            ops_overview=ops_overview,
            quota_estimate=quota_estimate,
            model_rows=model_rows,
            probe_meta=probe_meta,
        )

        ops_duration = ops_overview.get("duration", {})
        qps = ops_overview.get("qps", {})
        tps = ops_overview.get("tps", {})

        return {
            "generated_at": utc_now_iso(),
            "config": {
                "monitor_key_configured": bool(probe_meta.get("configured")),
                "monitor_probe_endpoint": self.settings.sub2api_monitor_probe_endpoint,
                "monitor_model_sources": self.settings.sub2api_monitor_model_sources,
                "account_scan_enabled": self.settings.account_scan_enabled,
                "refresh_interval_ms": self.settings.dashboard_cache_ttl_seconds * 1000,
                "group_scope": group_scope,
                "probe_groups": probe_meta.get("configured_groups", []),
                "probe_missing_groups": probe_meta.get("missing_groups", []),
            },
            "summary": {
                "total_accounts": total_accounts,
                "available_accounts": available_accounts,
                "rate_limited_accounts": rate_limited_accounts,
                "error_accounts": error_accounts,
                "overload_accounts": overload_accounts,
                "total_api_keys": as_int(snapshot_stats.get("total_api_keys")) or 0,
                "active_api_keys": as_int(snapshot_stats.get("active_api_keys")) or 0,
                "active_users": as_int(snapshot_stats.get("active_users")) or 0,
                "today_requests": as_int(snapshot_stats.get("today_requests")) or 0,
                "today_cost": (
                    scoped_today_cost
                    if group_scope["enabled"]
                    else round(as_float(snapshot_stats.get("today_cost")) or 0.0, 4)
                ),
                "total_cost": (
                    scoped_total_cost
                    if group_scope["enabled"]
                    else round(as_float(snapshot_stats.get("total_cost")) or 0.0, 4)
                ),
                "rpm": as_int(snapshot_stats.get("rpm")) or 0,
                "tpm": as_int(snapshot_stats.get("tpm")) or 0,
                "current_requests_per_minute": as_int(realtime.get("requests_per_minute")) or 0,
                "current_active_requests": as_int(realtime.get("active_requests")) or 0,
                "success_rate_1h": round(as_float(ops_overview.get("sla")) or 0.0, 4),
                "error_rate_1h": round(as_float(ops_overview.get("error_rate")) or 0.0, 4),
                "avg_latency_ms_1h": round(as_float(ops_duration.get("avg_ms")) or 0.0, 2),
                "p95_latency_ms_1h": round(as_float(ops_duration.get("p95_ms")) or 0.0, 2),
                "capacity_used": capacity_used,
                "capacity_max": capacity_max,
                "capacity_utilization": round(capacity_utilization, 4),
                "health_score": as_int(ops_overview.get("health_score")) or 0,
                "stats_updated_at": snapshot_stats.get("stats_updated_at"),
                "snapshot_generated_at": snapshot.get("generated_at"),
                "qps": {
                    "current": round(as_float(qps.get("current")) or 0.0, 3),
                    "avg": round(as_float(qps.get("avg")) or 0.0, 3),
                    "peak": round(as_float(qps.get("peak")) or 0.0, 3),
                },
                "tps": {
                    "current": round(as_float(tps.get("current")) or 0.0, 1),
                    "avg": round(as_float(tps.get("avg")) or 0.0, 1),
                    "peak": round(as_float(tps.get("peak")) or 0.0, 1),
                },
            },
            "quota_estimate": quota_estimate,
            "timeseries": {
                "daily": [
                    {
                        "date": item.get("date"),
                        "requests": as_int(item.get("requests")) or 0,
                        "cost": round(as_float(item.get("cost")) or 0.0, 4),
                        "tokens": as_int(item.get("total_tokens")) or 0,
                    }
                    for item in trend
                ]
            },
            "models": model_rows,
            "model_groups": model_group_sections,
            "pool": {
                "status_breakdown": {
                    "available": available_accounts,
                    "rate_limited": rate_limited_accounts,
                    "errors": error_accounts,
                    "overloaded": overload_accounts,
                    "other": max(total_accounts - available_accounts - rate_limited_accounts - error_accounts - overload_accounts, 0),
                },
                "platforms": platform_view,
                "groups": groups_view,
                "capacity": {
                    "used": capacity_used,
                    "max": capacity_max,
                    "utilization": round(capacity_utilization, 4),
                },
            },
            "ops": {
                "overview": {
                    "success_count": as_int(ops_overview.get("success_count")) or 0,
                    "error_count_total": as_int(ops_overview.get("error_count_total")) or 0,
                    "request_count_total": as_int(ops_overview.get("request_count_total")) or 0,
                    "upstream_error_rate": round(as_float(ops_overview.get("upstream_error_rate")) or 0.0, 4),
                    "upstream_error_count_excl_429_529": as_int(
                        ops_overview.get("upstream_error_count_excl_429_529")
                    )
                    or 0,
                },
                "duration": {
                    key: round(as_float(value) or 0.0, 2) for key, value in ops_duration.items()
                },
            },
            "insights": insights,
            "sources": {
                "admin_api": {
                    "ok": True,
                    "mode": "x-api-key",
                    "latency_ms": admin_latency_ms,
                },
                "availability_summary": {
                    "ok": True,
                    "latency_ms": availability_latency_ms,
                    "enabled": availability.get("enabled", True),
                    "timestamp": availability.get("timestamp"),
                },
                "model_probe": {
                    "ok": bool(probe_meta.get("configured")),
                    "configured": bool(probe_meta.get("configured")),
                    "catalog_loaded": any(section.get("catalog") is not None for section in model_groups),
                    "probed_models": sum(len(section.get("probes") or {}) for section in model_groups),
                    "configured_groups": probe_meta.get("configured_groups", []),
                    "missing_groups": probe_meta.get("missing_groups", []),
                },
            },
        }

    def _build_group_model_sections(
        self,
        model_usage: list[dict[str, Any]],
        model_groups: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        usage_by_model = {item.get("model"): item for item in model_usage if item.get("model")}
        sections: list[dict[str, Any]] = []
        flat_rows: list[dict[str, Any]] = []

        for group in model_groups:
            monitored_models = set(group.get("monitored_models") or set())
            probe_map = group.get("probes") or {}
            catalog_map = group.get("catalog")
            rows: list[dict[str, Any]] = []
            for model in sorted(
                monitored_models,
                key=lambda value: (-(as_int(usage_by_model.get(value, {}).get("requests")) or 0), value),
            ):
                usage = usage_by_model.get(model, {})
                probe = probe_map.get(model, {})
                catalog_available = catalog_map.get(model) if isinstance(catalog_map, dict) else None
                row = {
                    "group_id": group["group_id"],
                    "group_name": group["group_name"],
                    "model": model,
                    "provider": self._infer_provider(model),
                    "requests_7d": as_int(usage.get("requests")) or 0,
                    "cost_7d": round(as_float(usage.get("cost")) or 0.0, 4),
                    "tokens_7d": as_int(usage.get("total_tokens")) or 0,
                    "catalog_available": catalog_available,
                    "probe_status": probe.get(
                        "status",
                        "disabled" if not group.get("api_key") else "untracked",
                    ),
                    "probe_latency_ms": probe.get("latency_ms"),
                    "probe_ttft_ms": probe.get("ttft_ms"),
                    "probe_http_status": probe.get("http_status"),
                    "probe_error": probe.get("error"),
                    "probe_streaming": probe.get("streaming"),
                    "observed": model in usage_by_model,
                }
                rows.append(row)
                flat_rows.append(row)

            sections.append(
                {
                    "group_id": group["group_id"],
                    "group_name": group["group_name"],
                    "has_probe_key": bool(group.get("api_key")),
                    "status": self._classify_model_group_status(rows, has_probe_key=bool(group.get("api_key"))),
                    "models": rows,
                }
            )
        return sections, flat_rows

    def _classify_model_group_status(
        self,
        rows: list[dict[str, Any]],
        *,
        has_probe_key: bool,
    ) -> str:
        if not has_probe_key:
            return "disabled"
        if not rows:
            return "disabled"
        statuses = [row.get("probe_status") for row in rows]
        if any(status == "down" for status in statuses):
            return "down"
        if any(status == "degraded" for status in statuses):
            return "degraded"
        if all(status == "healthy" for status in statuses):
            return "healthy"
        return "disabled"

    def _resolve_monitored_models(
        self,
        *,
        snapshot: dict[str, Any],
        groups: list[dict[str, Any]],
        catalog_items: list[dict[str, Any]],
    ) -> set[str]:
        sources = set(self.settings.sub2api_monitor_model_sources)
        models: set[str] = set()

        if "configured" in sources:
            models.update(self.settings.sub2api_monitor_models)
        if "groups" in sources:
            models.update(self._extract_models_from_groups(groups))
        if "usage" in sources:
            ranked_usage = sorted(
                (item for item in snapshot.get("models", []) if item.get("model")),
                key=lambda item: -(as_int(item.get("requests")) or 0),
            )
            for item in ranked_usage[: self.settings.sub2api_monitor_usage_model_limit]:
                self._add_model_name(models, item.get("model"))
        if "catalog" in sources:
            for item in catalog_items:
                self._add_model_name(models, item.get("id"))

        return {model for model in models if model}

    def _extract_models_from_groups(self, groups: list[dict[str, Any]]) -> set[str]:
        models: set[str] = set()
        for group in groups:
            self._add_model_name(models, group.get("default_mapped_model"))

            dispatch_config = group.get("messages_dispatch_model_config") or {}
            if isinstance(dispatch_config, dict):
                for value in dispatch_config.values():
                    self._add_model_name(models, value)

            model_routing = group.get("model_routing") or {}
            if isinstance(model_routing, dict):
                for route_key, route_value in model_routing.items():
                    self._add_model_name(models, route_key)
                    if isinstance(route_value, str):
                        self._add_model_name(models, route_value)
                    elif isinstance(route_value, dict):
                        for field in ("mapped_model", "model", "target_model", "upstream_model"):
                            self._add_model_name(models, route_value.get(field))
        return models

    def _add_model_name(self, models: set[str], value: Any) -> None:
        if not isinstance(value, str):
            return
        normalized = value.strip()
        if normalized:
            models.add(normalized)

    def _merge_availability_payloads(self, payloads: list[dict[str, Any]]) -> dict[str, Any]:
        group_summary: dict[str, dict[str, Any]] = {}
        dedup_accounts: dict[str, dict[str, Any]] = {}
        timestamps = [payload.get("timestamp") for payload in payloads if payload.get("timestamp")]

        for payload in payloads:
            for group_id, group_payload in (payload.get("group") or {}).items():
                group_summary[str(group_id)] = group_payload
            for account_id, account_payload in (payload.get("account") or {}).items():
                dedup_accounts[str(account_id)] = account_payload

        platform_summary: dict[str, dict[str, Any]] = {}
        account_summary = {
            "total_accounts": 0,
            "available_count": 0,
            "rate_limit_count": 0,
            "error_count": 0,
            "overload_count": 0,
        }
        for account in dedup_accounts.values():
            platform = str(account.get("platform") or "unknown")
            platform_row = platform_summary.setdefault(
                platform,
                {
                    "platform": platform,
                    "total_accounts": 0,
                    "available_count": 0,
                    "rate_limit_count": 0,
                    "error_count": 0,
                },
            )
            platform_row["total_accounts"] += 1
            account_summary["total_accounts"] += 1

            if account.get("is_available"):
                platform_row["available_count"] += 1
                account_summary["available_count"] += 1
            if account.get("is_rate_limited"):
                platform_row["rate_limit_count"] += 1
                account_summary["rate_limit_count"] += 1
            if account.get("has_error"):
                platform_row["error_count"] += 1
                account_summary["error_count"] += 1
            if account.get("is_overloaded"):
                account_summary["overload_count"] += 1

        return {
            "enabled": all(payload.get("enabled", True) for payload in payloads),
            "timestamp": max(timestamps) if timestamps else utc_now_iso(),
            "group": group_summary,
            "platform": platform_summary,
            "account_summary": account_summary,
        }

    def _merge_ops_overviews(
        self,
        payloads: list[dict[str, Any]],
        *,
        group_ids: list[int],
    ) -> dict[str, Any]:
        request_total = sum(as_int(payload.get("request_count_total")) or 0 for payload in payloads)
        success_total = sum(as_int(payload.get("success_count")) or 0 for payload in payloads)
        error_total = sum(as_int(payload.get("error_count_total")) or 0 for payload in payloads)
        upstream_error_total = sum(
            as_int(payload.get("upstream_error_count_excl_429_529")) or 0 for payload in payloads
        )

        weight_total = sum(
            max(as_int(payload.get("request_count_total")) or 0, 1) for payload in payloads
        )
        health_score = (
            round(
                sum(
                    (as_int(payload.get("health_score")) or 0)
                    * max(as_int(payload.get("request_count_total")) or 0, 1)
                    for payload in payloads
                )
                / weight_total
            )
            if weight_total
            else 0
        )

        duration: dict[str, float] = {}
        duration_keys = {
            key
            for payload in payloads
            for key in (payload.get("duration") or {}).keys()
        }
        for key in duration_keys:
            values = [as_float((payload.get("duration") or {}).get(key)) for payload in payloads]
            numeric_values = [value for value in values if value is not None]
            if not numeric_values:
                continue
            if key.startswith("p") or key in {"max_ms"}:
                duration[key] = round(max(numeric_values), 2)
                continue
            weighted = 0.0
            for payload in payloads:
                req_count = max(as_int(payload.get("request_count_total")) or 0, 1)
                weighted += (as_float((payload.get("duration") or {}).get(key)) or 0.0) * req_count
            duration[key] = round(weighted / weight_total, 2) if weight_total else 0.0

        return {
            "group_ids": group_ids,
            "health_score": health_score,
            "sla": round(success_total / request_total, 4) if request_total else 0.0,
            "error_rate": round(error_total / request_total, 4) if request_total else 0.0,
            "success_count": success_total,
            "error_count_total": error_total,
            "request_count_total": request_total,
            "upstream_error_rate": round(upstream_error_total / request_total, 4)
            if request_total
            else 0.0,
            "upstream_error_count_excl_429_529": upstream_error_total,
            "duration": duration,
            "qps": {
                "current": round(
                    sum(as_float((payload.get("qps") or {}).get("current")) or 0.0 for payload in payloads),
                    3,
                ),
                "avg": round(
                    sum(as_float((payload.get("qps") or {}).get("avg")) or 0.0 for payload in payloads),
                    3,
                ),
                "peak": round(
                    max(as_float((payload.get("qps") or {}).get("peak")) or 0.0 for payload in payloads),
                    3,
                )
                if payloads
                else 0.0,
            },
            "tps": {
                "current": round(
                    sum(as_float((payload.get("tps") or {}).get("current")) or 0.0 for payload in payloads),
                    1,
                ),
                "avg": round(
                    sum(as_float((payload.get("tps") or {}).get("avg")) or 0.0 for payload in payloads),
                    1,
                ),
                "peak": round(
                    max(as_float((payload.get("tps") or {}).get("peak")) or 0.0 for payload in payloads),
                    1,
                )
                if payloads
                else 0.0,
            },
        }

    def _extract_explicit_quota(self, account: dict[str, Any]) -> tuple[float | None, float | None]:
        quota_limit = as_float(account.get("quota_limit"))
        quota_used = as_float(account.get("quota_used"))
        if quota_limit and quota_limit > 0 and quota_used is not None:
            return quota_limit, quota_used

        window_limit = as_float(account.get("window_cost_limit"))
        window_used = as_float(account.get("current_window_cost"))
        if window_limit and window_limit > 0 and window_used is not None:
            return window_limit, window_used

        extra = account.get("extra") or {}
        window_limit = as_float(extra.get("window_cost_limit"))
        window_used = as_float(extra.get("current_window_cost"))
        if window_limit and window_limit > 0 and window_used is not None:
            return window_limit, window_used
        return None, None

    def _infer_provider(self, model: str) -> str:
        lowered = model.lower()
        if "claude" in lowered:
            return "Anthropic"
        if "gemini" in lowered or lowered.startswith("google/"):
            return "Google"
        if lowered.startswith("gpt") or lowered.startswith("o") or "codex" in lowered:
            return "OpenAI"
        if "qwen" in lowered:
            return "Qwen"
        return "Other"

    def _classify_group_status(
        self, *, total: int, available: int, rate_limited: int, error_count: int
    ) -> str:
        if total <= 0:
            return "empty"
        if error_count > 0:
            return "error"
        if available / total < 0.35:
            return "critical"
        if rate_limited / total > 0.45:
            return "warning"
        return "healthy"

    def _build_insights(
        self,
        *,
        total_accounts: int,
        available_accounts: int,
        rate_limited_accounts: int,
        error_accounts: int,
        capacity_utilization: float,
        ops_overview: dict[str, Any],
        quota_estimate: dict[str, Any],
        model_rows: list[dict[str, Any]],
        probe_meta: dict[str, Any],
    ) -> list[dict[str, str]]:
        insights: list[dict[str, str]] = []
        availability_ratio = available_accounts / total_accounts if total_accounts else 0
        if availability_ratio < 0.45:
            insights.append(
                {
                    "severity": "critical",
                    "title": "可用账号池偏低",
                    "message": f"当前仅有 {available_accounts}/{total_accounts} 个账号处于可用状态，建议优先排查限流组与坏号来源。",
                }
            )
        if total_accounts and rate_limited_accounts / total_accounts > 0.5:
            insights.append(
                {
                    "severity": "warning",
                    "title": "限流占比过高",
                    "message": f"限流账号达到 {rate_limited_accounts}/{total_accounts}，需要结合分组与模型流量做限速或扩池。",
                }
            )
        if error_accounts > 0:
            insights.append(
                {
                    "severity": "warning",
                    "title": "存在异常账号",
                    "message": f"当前有 {error_accounts} 个账号处于错误状态，建议结合 Sub2API 后台错误详情复核。",
                }
            )
        success_rate = as_float(ops_overview.get("sla")) or 0.0
        if success_rate < 0.9:
            insights.append(
                {
                    "severity": "critical",
                    "title": "近 1 小时成功率偏低",
                    "message": f"当前 1h 成功率仅 {success_rate:.1%}，应优先查看模型探针、上游错误率和限流分布。",
                }
            )
        if capacity_utilization > 0.8:
            insights.append(
                {
                    "severity": "warning",
                    "title": "并发产能接近上限",
                    "message": f"当前并发产能利用率约 {capacity_utilization:.1%}，继续增长会更容易触发切号和限流。",
                }
            )
        if probe_meta.get("missing_groups"):
            missing_names = [
                str(item.get("name") or item.get("id"))
                for item in probe_meta.get("missing_groups", [])
            ]
            insights.append(
                {
                    "severity": "info",
                    "title": "部分分组未配置探针 Key",
                    "message": f"以下分组当前没有可用探针 key：{', '.join(missing_names[:5])}。",
                }
            )
        if not probe_meta.get("configured"):
            insights.append(
                {
                    "severity": "info",
                    "title": "尚未启用真实模型探针",
                    "message": "当前没有可用于本监控范围的 probe key，所以模型可用性只能显示历史 usage 和探针占位。",
                }
            )
        elif model_rows and any(
            row.get("probe_status") in {"degraded", "down"} for row in model_rows
        ):
            bad = [
                f"{row.get('group_name')} / {row.get('model')}"
                for row in model_rows
                if row.get("probe_status") in {"degraded", "down"}
            ]
            insights.append(
                {
                    "severity": "warning",
                    "title": "存在探针异常模型",
                    "message": f"以下模型最新探针未通过：{', '.join(sorted(bad)[:5])}。",
                }
            )
        if quota_estimate.get("enabled") and (quota_estimate.get("coverage_ratio") or 0) < 0.2:
            insights.append(
                {
                    "severity": "info",
                    "title": "显式额度覆盖率偏低",
                    "message": "显式额度估算只覆盖少量账号，结果更适合做趋势参考，不适合作为精确总额度。",
                }
            )
        return insights
