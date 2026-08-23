from __future__ import annotations

import os
import stat
from pathlib import Path

import httpx
from dotenv import dotenv_values
from pydantic import BaseModel, Field, field_validator

APP_DIR = Path.home() / ".meal-organizer"
DB_PATH = APP_DIR / "meal-organizer.db"
ENV_PATH = APP_DIR / ".env"


class LLMConfig(BaseModel):
    provider: str = "ollama"
    model: str = "qwen3:8b"
    ollama_host: str = "http://127.0.0.1:11434"
    openrouter_model: str = ""
    openrouter_api_key: str = Field(default="", repr=False)

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in {"ollama", "openrouter"}:
            raise ValueError("LLM provider must be 'ollama' or 'openrouter'")
        return value


class UserConfig(BaseModel):
    name: str = ""
    servings: int = Field(default=1, ge=1, le=20)
    weekly_budget: float = Field(default=50.0, ge=0)
    allergies: list[str] = Field(default_factory=list)
    dislikes: list[str] = Field(default_factory=list)
    equipment: list[str] = Field(default_factory=list)
    llm: LLMConfig = Field(default_factory=LLMConfig)


def ensure_app_dir() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)


def _csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _env_values() -> dict[str, str]:
    ensure_app_dir()
    values = {key: value for key, value in dotenv_values(ENV_PATH).items() if value is not None}
    values.update({key: value for key, value in os.environ.items() if key.startswith("MEAL_ORGANIZER_")})
    return values


def load_config() -> UserConfig:
    values = _env_values()
    return UserConfig(
        name=values.get("MEAL_ORGANIZER_NAME", ""),
        servings=int(values.get("MEAL_ORGANIZER_SERVINGS", "1")),
        weekly_budget=float(values.get("MEAL_ORGANIZER_WEEKLY_BUDGET", "50")),
        allergies=_csv(values.get("MEAL_ORGANIZER_ALLERGIES")),
        dislikes=_csv(values.get("MEAL_ORGANIZER_DISLIKES")),
        equipment=_csv(values.get("MEAL_ORGANIZER_EQUIPMENT")),
        llm=LLMConfig(
            provider=values.get("MEAL_ORGANIZER_LLM_PROVIDER", "ollama"),
            model=values.get("MEAL_ORGANIZER_OLLAMA_MODEL", "qwen3:8b"),
            ollama_host=values.get("MEAL_ORGANIZER_OLLAMA_HOST", "http://127.0.0.1:11434"),
            openrouter_model=values.get("MEAL_ORGANIZER_OPENROUTER_MODEL", ""),
            openrouter_api_key=values.get("MEAL_ORGANIZER_OPENROUTER_API_KEY", ""),
        ),
    )


def _quote_env(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def save_config(config: UserConfig) -> None:
    """Persist non-secret and secret settings in the user's ignored .env file."""
    ensure_app_dir()
    content = "\n".join(
        [
            "# Meal Organizer configuration. This file contains your API key; never commit it.",
            f"MEAL_ORGANIZER_NAME={_quote_env(config.name)}",
            f"MEAL_ORGANIZER_SERVINGS={config.servings}",
            f"MEAL_ORGANIZER_WEEKLY_BUDGET={config.weekly_budget}",
            f"MEAL_ORGANIZER_ALLERGIES={_quote_env(','.join(config.allergies))}",
            f"MEAL_ORGANIZER_DISLIKES={_quote_env(','.join(config.dislikes))}",
            f"MEAL_ORGANIZER_EQUIPMENT={_quote_env(','.join(config.equipment))}",
            f"MEAL_ORGANIZER_LLM_PROVIDER={config.llm.provider}",
            f"MEAL_ORGANIZER_OLLAMA_MODEL={_quote_env(config.llm.model)}",
            f"MEAL_ORGANIZER_OLLAMA_HOST={_quote_env(config.llm.ollama_host)}",
            f"MEAL_ORGANIZER_OPENROUTER_MODEL={_quote_env(config.llm.openrouter_model)}",
            f"MEAL_ORGANIZER_OPENROUTER_API_KEY={_quote_env(config.llm.openrouter_api_key)}",
            "",
        ]
    )
    tmp_path = ENV_PATH.with_suffix(".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    if os.name != "nt":
        tmp_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    tmp_path.replace(ENV_PATH)


def check_ollama(host: str) -> tuple[bool, list[str]]:
    """Return whether Ollama is reachable and the locally available model names."""
    try:
        response = httpx.get(f"{host.rstrip('/')}/api/tags", timeout=3)
        response.raise_for_status()
        models = [item.get("name", "") for item in response.json().get("models", [])]
        return True, [name for name in models if name]
    except (httpx.HTTPError, ValueError, TypeError):
        return False, []
