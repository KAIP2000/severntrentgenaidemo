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
    model_name: str = "gemini-3.5-flash-lite"
    google_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    )
    agent_execution_mode: Literal["live", "simulation"] = "live"
    keep_threads: bool = False
    langsmith_tracing: bool = False
    langsmith_project: str = "water-operations-agentic-harness"
    eval_judge_model_name: str | None = None
    eval_dataset_name: str = "Water Operations - Harness Scenarios v1"
    eval_max_concurrency: int = Field(default=1, ge=1, le=10)
    eval_repetitions: int = Field(default=1, ge=1, le=10)
    eval_scenario_timeout_seconds: int = Field(default=600, ge=60, le=1800)
    eval_scenario_ids: str = ""
    eval_run_on_startup: bool = True
    allowed_origins: str = "http://localhost:3000"

    @property
    def langchain_model_id(self) -> str:
        return f"{self.model_provider}:{self.model_name}"

    @property
    def live_model_available(self) -> bool:
        return self.agent_execution_mode == "live" and (self.model_provider != "google_genai" or bool(self.google_api_key))

    @property
    def judge_model_name(self) -> str:
        return self.eval_judge_model_name or self.model_name

    @property
    def selected_eval_scenario_ids(self) -> set[str]:
        return {item.strip() for item in self.eval_scenario_ids.split(",") if item.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
