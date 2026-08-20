from dataclasses import dataclass
from typing import Literal, Protocol

from app.config import Settings


@dataclass(frozen=True)
class ModelConfig:
    provider: Literal["google_genai", "ollama", "browser"]
    model: str

    @property
    def langchain_id(self) -> str:
        return f"{self.provider}:{self.model}"


class Planner(Protocol):
    def create(self): ...


class ModelGateway:
    """Provider boundary: agent code never imports a vendor-specific client."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.config = ModelConfig(provider=settings.model_provider, model=settings.model_name)

    def create_chat_model(self):
        if self.config.provider == "browser":
            raise RuntimeError("Browser models execute client-side and cannot be created by the API.")
        from langchain.chat_models import init_chat_model

        # Gemini 3.6 Flash deprecates temperature/top_p/top_k. Keep its config minimal.
        options = {"max_retries": 3, "timeout": 90}
        if self.config.provider == "google_genai" and self.settings.google_api_key:
            options["google_api_key"] = self.settings.google_api_key
        return init_chat_model(self.config.langchain_id, **options)
