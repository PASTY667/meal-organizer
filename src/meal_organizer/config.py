from pathlib import Path

import keyring
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_DIR = Path.home() / ".meal-organizer"
DB_PATH = APP_DIR / "meal-organizer.db"
CONFIG_PATH = APP_DIR / "config.toml"
KEYRING_SERVICE = "meal-organizer/openrouter"


class LLMConfig(BaseModel):
    provider: str = "ollama"
    model: str = "qwen3:8b"
    ollama_host: str = "http://127.0.0.1:11434"
    openrouter_model: str = ""
    openrouter_api_key: str = Field(default="", repr=False)


class UserConfig(BaseModel):
    name: str = ""
    servings: int = Field(default=1, ge=1, le=20)
    weekly_budget: float = Field(default=50.0, ge=0)
    allergies: list[str] = Field(default_factory=list)
    dislikes: list[str] = Field(default_factory=list)
    equipment: list[str] = Field(default_factory=list)
    llm: LLMConfig = Field(default_factory=LLMConfig)


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MEAL_ORGANIZER_", extra="ignore")
    debug: bool = False


def ensure_app_dir() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)


def _get_api_key() -> str:
    try:
        return keyring.get_password(KEYRING_SERVICE, "api_key") or ""
    except Exception:
        return ""


def load_config() -> UserConfig:
    ensure_app_dir()
    if not CONFIG_PATH.exists():
        return UserConfig(llm=LLMConfig(openrouter_api_key=_get_api_key()))
    try:
        import tomllib

        config = UserConfig.model_validate(tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        config.llm.openrouter_api_key = _get_api_key()
        return config
    except (OSError, ValueError, TypeError):
        return UserConfig(llm=LLMConfig(openrouter_api_key=_get_api_key()))


def save_config(config: UserConfig) -> None:
    ensure_app_dir()
    if config.llm.openrouter_api_key:
        try:
            keyring.set_password(KEYRING_SERVICE, "api_key", config.llm.openrouter_api_key)
        except Exception:
            pass
    lines = [
        f'name = {config.name!r}',
        f"servings = {config.servings}",
        f"weekly_budget = {config.weekly_budget}",
        f"allergies = {config.allergies!r}",
        f"dislikes = {config.dislikes!r}",
        f"equipment = {config.equipment!r}",
        "",
        "[llm]",
        f'provider = {config.llm.provider!r}',
        f'model = {config.llm.model!r}',
        f'ollama_host = {config.llm.ollama_host!r}',
        f'openrouter_model = {config.llm.openrouter_model!r}',
    ]
    CONFIG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
