from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv


load_dotenv(Path(__file__).parents[2] / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    app_name: str = "Water Operations Agentic Harness"
    model_provider: Literal["google_genai", "ollama", "browser"] = "google_genai"
    model_name: str = "gemini-3.6-flash"
    google_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    )
    agent_execution_mode: Literal["live", "simulation"] = "live"
    langsmith_tracing: bool = False
    langsmith_project: str = "water-operations-agentic-harness"
    allowed_origins: str = "http://localhost:3000"

    @property
    def langchain_model_id(self) -> str:
        return f"{self.model_provider}:{self.model_name}"

    @property
    def live_model_available(self) -> bool:
        return self.agent_execution_mode == "live" and (self.model_provider != "google_genai" or bool(self.google_api_key))


@lru_cache
def get_settings() -> Settings:
    return Settings()
