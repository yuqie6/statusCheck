from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.config import Settings


class Sub2ApiError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, payload: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class Sub2ApiClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.sub2api_base_url,
            timeout=settings.sub2api_timeout_seconds,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        response = await self._client.request(
            method,
            path,
            headers=headers,
            params=params,
            json=json_body,
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise Sub2ApiError(
                f"Sub2API 返回了非 JSON 响应: {response.text[:200]}",
                status_code=response.status_code,
            ) from exc

        if response.status_code >= 400:
            message = payload.get("message") if isinstance(payload, dict) else str(payload)
            raise Sub2ApiError(message or "Sub2API 请求失败", status_code=response.status_code, payload=payload)

        if isinstance(payload, dict) and "code" in payload:
            if payload.get("code") == 0:
                return payload.get("data")
            raise Sub2ApiError(
                payload.get("message") or "Sub2API 业务错误",
                status_code=response.status_code,
                payload=payload,
            )
        return payload

    async def admin_get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        if not self.settings.sub2api_admin_api_key:
            raise Sub2ApiError("未配置 SUB2API_ADMIN_API_KEY")
        return await self._request(
            "GET",
            path,
            headers={"x-api-key": self.settings.sub2api_admin_api_key},
            params=params,
        )

    def _resolve_public_api_key(self, api_key: str | None = None) -> str:
        resolved = (api_key or self.settings.sub2api_monitor_api_key or "").strip()
        if not resolved:
            raise Sub2ApiError("未配置 SUB2API_MONITOR_API_KEY")
        return resolved

    def _public_headers(self, api_key: str | None = None) -> dict[str, str]:
        resolved_key = self._resolve_public_api_key(api_key)
        return {"Authorization": f"Bearer {resolved_key}"}

    async def public_get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        api_key: str | None = None,
    ) -> Any:
        return await self._request(
            "GET",
            path,
            headers=self._public_headers(api_key),
            params=params,
        )

    async def public_post(
        self,
        path: str,
        *,
        json_body: dict[str, Any],
        api_key: str | None = None,
    ) -> Any:
        return await self._request(
            "POST",
            path,
            headers=self._public_headers(api_key),
            json_body=json_body,
        )

    async def get_dashboard_snapshot(self, *, group_id: int | None = None) -> dict[str, Any]:
        params = {"group_id": group_id} if group_id and group_id > 0 else None
        return await self.admin_get("/api/v1/admin/dashboard/snapshot-v2", params=params)

    async def get_dashboard_stats(self, *, group_id: int | None = None) -> dict[str, Any]:
        params = {"group_id": group_id} if group_id and group_id > 0 else None
        return await self.admin_get("/api/v1/admin/dashboard/stats", params=params)

    async def get_dashboard_realtime(self, *, group_id: int | None = None) -> dict[str, Any]:
        params = {"group_id": group_id} if group_id and group_id > 0 else None
        return await self.admin_get("/api/v1/admin/dashboard/realtime", params=params)

    async def get_ops_overview(self, *, group_id: int | None = None) -> dict[str, Any]:
        params = {"group_id": group_id} if group_id and group_id > 0 else None
        return await self.admin_get("/api/v1/admin/ops/dashboard/overview", params=params)

    async def get_groups(self, *, page_size: int = 100) -> dict[str, Any]:
        return await self.admin_get("/api/v1/admin/groups", params={"page": 1, "page_size": page_size})

    async def get_group_capacity(self) -> list[dict[str, Any]]:
        return await self.admin_get("/api/v1/admin/groups/capacity-summary")

    async def get_group_usage_summary(self) -> list[dict[str, Any]]:
        return await self.admin_get("/api/v1/admin/groups/usage-summary")

    async def get_account_availability(
        self, *, platform: str | None = None, group_id: int | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if platform:
            params["platform"] = platform
        if group_id and group_id > 0:
            params["group_id"] = group_id
        return await self.admin_get("/api/v1/admin/ops/account-availability", params=params or None)

    async def iter_accounts(self, *, page_size: int, max_pages: int = 0) -> AsyncIterator[dict[str, Any]]:
        page = 1
        seen_pages = 0
        while True:
            payload = await self.admin_get(
                "/api/v1/admin/accounts",
                params={"page": page, "page_size": page_size},
            )
            for item in payload.get("items", []):
                yield item
            page += 1
            seen_pages += 1
            if page > int(payload.get("pages") or 0):
                break
            if max_pages and seen_pages >= max_pages:
                break

    async def get_public_model_catalog(self, *, api_key: str | None = None) -> list[dict[str, Any]]:
        payload = await self.public_get("/v1/models", api_key=api_key)
        return payload.get("data", []) if isinstance(payload, dict) else payload

    async def probe_model(self, model: str, *, api_key: str | None = None) -> dict[str, Any]:
        started_at = time.perf_counter()
        endpoint = self.settings.sub2api_monitor_probe_endpoint
        if endpoint == "responses":
            payload = {
                "model": model,
                "input": self.settings.sub2api_monitor_prompt,
                "max_output_tokens": self.settings.sub2api_monitor_max_tokens,
                "temperature": self.settings.sub2api_monitor_temperature,
                "stream": True,
            }
            path = "/v1/responses"
        else:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are a health check. Reply briefly."},
                    {"role": "user", "content": self.settings.sub2api_monitor_prompt},
                ],
                "max_tokens": self.settings.sub2api_monitor_max_tokens,
                "temperature": self.settings.sub2api_monitor_temperature,
                "stream": True,
            }
            path = "/v1/chat/completions"

        try:
            return await self._stream_probe(
                path=path,
                payload=payload,
                model=model,
                api_key=api_key,
                endpoint=endpoint,
                started_at=started_at,
            )
        except Sub2ApiError as exc:
            elapsed = round((time.perf_counter() - started_at) * 1000)
            status = "degraded" if exc.status_code == 429 else "down"
            return {
                "model": model,
                "status": status,
                "latency_ms": elapsed,
                "ttft_ms": None,
                "http_status": exc.status_code,
                "error": str(exc),
                "streaming": True,
            }

    async def _stream_probe(
        self,
        *,
        path: str,
        payload: dict[str, Any],
        model: str,
        api_key: str | None,
        endpoint: str,
        started_at: float,
    ) -> dict[str, Any]:
        timeout = httpx.Timeout(self.settings.sub2api_monitor_timeout_seconds)
        headers = self._public_headers(api_key)
        async with self._client.stream(
            "POST",
            path,
            headers=headers,
            json=payload,
            timeout=timeout,
        ) as response:
            if response.status_code >= 400:
                raise Sub2ApiError(
                    await self._read_error_response(response),
                    status_code=response.status_code,
                )

            content_type = (response.headers.get("content-type") or "").lower()
            if "text/event-stream" not in content_type:
                data = await response.aread()
                ttft_ms = None
                elapsed = round((time.perf_counter() - started_at) * 1000)
                error = None
                try:
                    payload_json = json.loads(data)
                    if not self._extract_response_text(payload_json, endpoint=endpoint):
                        error = "未返回文本"
                except (TypeError, ValueError):
                    error = "未返回流式数据"
                return {
                    "model": model,
                    "status": "healthy" if error is None else "degraded",
                    "latency_ms": elapsed,
                    "ttft_ms": ttft_ms,
                    "http_status": response.status_code,
                    "error": error,
                    "streaming": False,
                }

            ttft_ms: int | None = None
            async for event_data in self._iter_sse_events(response):
                if event_data == "[DONE]":
                    break
                try:
                    chunk = json.loads(event_data)
                except ValueError:
                    continue

                error_message = self._extract_stream_error(chunk)
                if error_message:
                    raise Sub2ApiError(error_message, status_code=response.status_code, payload=chunk)

                if ttft_ms is None and self._extract_response_text(chunk, endpoint=endpoint):
                    ttft_ms = round((time.perf_counter() - started_at) * 1000)

            elapsed = round((time.perf_counter() - started_at) * 1000)
            return {
                "model": model,
                "status": "healthy" if ttft_ms is not None else "degraded",
                "latency_ms": elapsed,
                "ttft_ms": ttft_ms,
                "http_status": response.status_code,
                "error": None if ttft_ms is not None else "未收到首字 Token",
                "streaming": True,
            }

    async def _read_error_response(self, response: httpx.Response) -> str:
        body = await response.aread()
        try:
            payload = json.loads(body)
        except ValueError:
            text = body.decode(errors="ignore")
            return text[:200] or "Sub2API 请求失败"

        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                return str(error.get("message") or error.get("code") or "Sub2API 请求失败")
            if isinstance(error, str) and error.strip():
                return error.strip()
            message = payload.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        return str(payload)

    async def _iter_sse_events(self, response: httpx.Response) -> AsyncIterator[str]:
        buffer: list[str] = []
        async for raw_line in response.aiter_lines():
            line = raw_line.strip()
            if not line:
                if buffer:
                    yield "\n".join(buffer)
                    buffer.clear()
                continue
            if line.startswith(":"):
                continue
            if line.startswith("data:"):
                buffer.append(line[5:].lstrip())
                continue
            if line.startswith("{") or line.startswith("["):
                yield line
        if buffer:
            yield "\n".join(buffer)

    def _extract_stream_error(self, payload: Any) -> str | None:
        if not isinstance(payload, dict):
            return None
        error = payload.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("code") or "").strip() or None
        if isinstance(error, str):
            return error.strip() or None
        return None

    def _extract_response_text(self, payload: Any, *, endpoint: str) -> str | None:
        if not isinstance(payload, dict):
            return None

        if endpoint == "responses":
            event_type = str(payload.get("type") or "")
            if event_type == "response.output_text.delta":
                delta = payload.get("delta")
                if isinstance(delta, str) and delta.strip():
                    return delta

            output_items = payload.get("output")
            if isinstance(output_items, list):
                for item in output_items:
                    if not isinstance(item, dict):
                        continue
                    for content in item.get("content") or []:
                        if not isinstance(content, dict):
                            continue
                        for field in ("text", "delta"):
                            value = content.get(field)
                            if isinstance(value, str) and value.strip():
                                return value
            return None

        choices = payload.get("choices")
        if not isinstance(choices, list):
            return None
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta") or {}
            if isinstance(delta, dict):
                content = delta.get("content")
                if isinstance(content, str) and content.strip():
                    return content
                if isinstance(content, list):
                    for item in content:
                        if not isinstance(item, dict):
                            continue
                        text = item.get("text")
                        if isinstance(text, str) and text.strip():
                            return text
            message = choice.get("message") or {}
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return content
                if isinstance(content, list):
                    for item in content:
                        if not isinstance(item, dict):
                            continue
                        text = item.get("text")
                        if isinstance(text, str) and text.strip():
                            return text
        return None
