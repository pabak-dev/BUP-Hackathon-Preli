import math
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    provider_order: tuple[str, ...] = ("vertex", "groq", "aistudio")
    vertex_project_id: str = ""
    vertex_location: str = ""
    vertex_model: str = ""
    groq_api_key: str = field(default="", repr=False)
    groq_model: str = ""
    gemini_api_key: str = field(default="", repr=False)
    aistudio_model: str = ""
    timeout_seconds: float = 6.0
    request_timeout_seconds: float = 27.0

    def __post_init__(self):
        if not self.provider_order or len(set(self.provider_order)) != len(self.provider_order):
            raise ValueError("Provider order must be nonempty and unique")
        if set(self.provider_order) - {"vertex", "groq", "aistudio"}:
            raise ValueError("Unknown provider")
        if not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 7:
            raise ValueError("Provider timeout must be greater than zero and at most 7 seconds")
        if self.vertex_location and not all(c.isascii() and (c.isalnum() or c == "-") for c in self.vertex_location):
            raise ValueError("Invalid Vertex location")

    def configured(self, name: str) -> bool:
        return bool(
            {
                "vertex": self.vertex_project_id and self.vertex_location and self.vertex_model,
                "groq": self.groq_api_key and self.groq_model,
                "aistudio": self.gemini_api_key and self.aistudio_model,
            }[name]
        )

    @property
    def ready(self) -> bool:
        return any(self.configured(name) for name in self.provider_order)

    @classmethod
    def from_env(cls):
        load_dotenv()
        names = (
            "vertex_project_id",
            "vertex_location",
            "vertex_model",
            "groq_api_key",
            "groq_model",
            "gemini_api_key",
            "aistudio_model",
        )
        return cls(
            **{name: os.getenv(name.upper(), "").strip() for name in names},
            provider_order=tuple(
                x.strip().lower() for x in os.getenv("LLM_PROVIDER_ORDER", "vertex,groq,aistudio").split(",")
            ),
            timeout_seconds=float(os.getenv("LLM_PROVIDER_TIMEOUT_SECONDS") or "6"),
        )
