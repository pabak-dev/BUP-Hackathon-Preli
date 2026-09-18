import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    api_key: str = field(default="", repr=False)
    base_url: str = "https://api.groq.com/openai/v1"
    model: str = "openai/gpt-oss-120b"
    provider: str = "groq"
    timeout_seconds: float = 10.0
    request_timeout_seconds: float = 27.0

    @classmethod
    def from_env(cls):
        load_dotenv()
        provider = os.getenv("LLM_PROVIDER", "groq").lower()
        defaults = {
            "groq": ("https://api.groq.com/openai/v1", "openai/gpt-oss-120b", "GROQ_API_KEY"),
            "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash", "GEMINI_API_KEY"),
        }
        if provider not in defaults:
            raise ValueError("LLM_PROVIDER must be groq or gemini")
        url, model, key_name = defaults[provider]
        return cls(
            api_key=os.getenv(key_name, ""),
            provider=provider,
            base_url=(os.getenv("LLM_BASE_URL") or url).rstrip("/"),
            model=os.getenv("LLM_MODEL") or model,
        )
