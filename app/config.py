from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Sub2API Status Check"
    app_env: str = "development"
    host: str = "0.0.0.0"
    port: int = 38481
    allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://127.0.0.1:38482", "http://localhost:38482"]
    )
    admin_token: str = ""

    sub2api_base_url: str = "http://127.0.0.1:18081"
    sub2api_admin_api_key: str = ""
    sub2api_timeout_seconds: float = 20.0
    sub2api_group_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)
    sub2api_include_exclusive_groups: bool = False

    dashboard_cache_ttl_seconds: int = 20
    account_scan_enabled: bool = False
    account_scan_ttl_seconds: int = 180
    account_scan_page_size: int = 100
    account_scan_max_pages: int = 0

    sub2api_monitor_api_key: str | None = None
    sub2api_monitor_group_api_keys: Annotated[dict[int, str], NoDecode] = Field(default_factory=dict)
    sub2api_monitor_models: Annotated[list[str], NoDecode] = Field(default_factory=list)
    sub2api_monitor_group_models: Annotated[dict[int, list[str]], NoDecode] = Field(default_factory=dict)
    sub2api_monitor_model_sources: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["groups", "configured"]
    )
    sub2api_monitor_usage_model_limit: int = 10
    sub2api_monitor_timeout_seconds: float = 18.0
    sub2api_monitor_max_tokens: int = 8
    sub2api_monitor_temperature: float = 0.0
    sub2api_monitor_prompt: str = "Reply with OK only."
    sub2api_monitor_concurrency: int = 3
    sub2api_monitor_probe_endpoint: Literal["chat_completions", "responses"] = "chat_completions"

    @field_validator("sub2api_base_url")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def split_allowed_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, list):
            return value
        return [item.strip() for item in value.split(",") if item.strip()]

    @field_validator("sub2api_group_ids", mode="before")
    @classmethod
    def split_group_ids(cls, value: str | list[int] | list[str] | None) -> list[int]:
        if value is None:
            return []
        if isinstance(value, list):
            items = value
        else:
            items = [item.strip() for item in value.split(",") if item.strip()]
        result: list[int] = []
        for item in items:
            if item in ("", None):
                continue
            result.append(int(item))
        return result

    @field_validator("sub2api_monitor_models", mode="before")
    @classmethod
    def split_monitor_models(cls, value: str | list[str] | None) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [item.strip() for item in value if item and item.strip()]
        return [item.strip() for item in value.split(",") if item.strip()]


    @field_validator("sub2api_monitor_group_models", mode="before")
    @classmethod
    def split_monitor_group_models(
        cls, value: str | dict[int, list[str]] | dict[str, list[str] | str] | None
    ) -> dict[int, list[str]]:
        if value is None:
            return {}
        if isinstance(value, dict):
            result: dict[int, list[str]] = {}
            for group_id, models in value.items():
                if isinstance(models, str):
                    items = [item.strip() for item in models.replace("\n", ",").replace("|", ",").split(",") if item.strip()]
                else:
                    items = [str(item).strip() for item in models if str(item).strip()]
                result[int(group_id)] = items
            return result

        text = value.strip()
        if not text:
            return {}

        if text.startswith("{"):
            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                raise ValueError("SUB2API_MONITOR_GROUP_MODELS 的 JSON 必须是对象映射")
            return cls.split_monitor_group_models(parsed)

        result: dict[int, list[str]] = {}
        for item in [part.strip() for part in text.replace("\n", ";").split(";") if part.strip()]:
            if "=" not in item:
                raise ValueError("SUB2API_MONITOR_GROUP_MODELS 格式应为 `2=modelA|modelB;6=modelC` 或 JSON 对象")
            group_text, models_text = item.split("=", 1)
            models = [model.strip() for model in models_text.replace("|", ",").split(",") if model.strip()]
            result[int(group_text.strip())] = models
        return result

    @field_validator("sub2api_monitor_group_api_keys", mode="before")
    @classmethod
    def split_monitor_group_api_keys(
        cls, value: str | dict[int, str] | dict[str, str] | None
    ) -> dict[int, str]:
        if value is None:
            return {}
        if isinstance(value, dict):
            result: dict[int, str] = {}
            for group_id, api_key in value.items():
                key_text = str(api_key).strip()
                if not key_text:
                    continue
                result[int(group_id)] = key_text
            return result

        text = value.strip()
        if not text:
            return {}

        if text.startswith("{"):
            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                raise ValueError("SUB2API_MONITOR_GROUP_API_KEYS 的 JSON 必须是对象映射")
            return {
                int(group_id): str(api_key).strip()
                for group_id, api_key in parsed.items()
                if str(api_key).strip()
            }

        result: dict[int, str] = {}
        for item in [part.strip() for part in text.replace("\n", ",").split(",") if part.strip()]:
            if "=" not in item:
                raise ValueError(
                    "SUB2API_MONITOR_GROUP_API_KEYS 格式应为 `2=keyA,6=keyB` 或 JSON 对象"
                )
            group_text, api_key = item.split("=", 1)
            group_id = int(group_text.strip())
            key_text = api_key.strip()
            if key_text:
                result[group_id] = key_text
        return result

    @field_validator("sub2api_monitor_model_sources", mode="before")
    @classmethod
    def split_monitor_model_sources(cls, value: str | list[str] | None) -> list[str]:
        if value is None:
            return ["groups", "configured"]
        if isinstance(value, list):
            items = [item.strip().lower() for item in value if item and item.strip()]
        else:
            items = [item.strip().lower() for item in value.split(",") if item.strip()]

        allowed = {"configured", "groups", "catalog", "usage"}
        invalid = [item for item in items if item not in allowed]
        if invalid:
            raise ValueError(
                f"SUB2API_MONITOR_MODEL_SOURCES 包含不支持的值: {', '.join(sorted(invalid))}"
            )
        return items or ["groups", "configured"]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
