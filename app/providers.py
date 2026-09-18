"""Provider wire adapters. Each generate call makes at most one model request."""

import asyncio
import json
from urllib.parse import quote

import google.auth
import httpx
from google.auth.transport.requests import Request

from app.config import Settings
from app.errors import ProviderError
from app.model_contract import provider_schema


class FailFastAuthRequest(Request):
    def __call__(self, *args, **kwargs):
        # Bound ADC/token I/O and prevent OAuth error responses triggering retries.
        kwargs["timeout"] = 2.0
        try:
            response = super().__call__(*args, **kwargs)
            if response.status >= 400:
                raise ProviderError("ADC authentication failed")
            return response
        except Exception:
            raise ProviderError("ADC authentication failed") from None


class VertexAuth:
    def __init__(self):
        self.credentials = None

    def _headers(self, url):
        transport = FailFastAuthRequest()
        try:
            if self.credentials is None:
                self.credentials, _ = google.auth.default(
                    scopes=["https://www.googleapis.com/auth/cloud-platform"], request=transport
                )
            headers = {}
            self.credentials.before_request(transport, "POST", url, headers)
            return headers
        except Exception:
            raise ProviderError("ADC authentication failed") from None
        finally:
            transport.session.close()

    async def headers(self, url):
        return await asyncio.to_thread(self._headers, url)


def google_schema():
    """Expand references into Google's supported responseSchema subset."""
    source = provider_schema()
    definitions = source["$defs"]

    def convert(node):
        if isinstance(node, list):
            return [convert(item) for item in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            return convert(definitions[node["$ref"].split("/")[-1]])
        if node.get("type") == "null":
            # The Google responseSchema subset represents null with nullable.
            # Pydantic still rejects any non-null no_op adjustment.
            return {
                "type": "OBJECT",
                "nullable": True,
                "description": "Must be null for no_op.",
                "properties": {"hours": {"type": "ARRAY", "items": {"type": "INTEGER"}}},
            }
        result = {key: convert(value) for key, value in node.items() if key not in {"$defs", "additionalProperties"}}
        if "type" in result:
            result["type"] = result["type"].upper()
        return result

    return convert(source)


class GroqProvider:
    name = "groq"

    def __init__(self, settings, client):
        self.settings, self.client = settings, client

    async def generate(self, prompt, payload):
        body = {
            "model": self.settings.groq_model,
            "temperature": 0,
            "max_completion_tokens": 1536,
            "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": payload}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "operator_directives", "strict": True, "schema": provider_schema()},
            },
        }
        if "gpt-oss" in self.settings.groq_model:
            body["reasoning_effort"] = "low"
        response = await self.client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": "Bearer " + self.settings.groq_api_key},
            json=body,
        )
        response.raise_for_status()
        choice = response.json()["choices"][0]
        if choice.get("finish_reason") != "stop" or choice["message"].get("refusal"):
            raise ProviderError("Incomplete model response")
        return json.loads(choice["message"]["content"])


class GoogleProvider:
    async def generate(self, prompt, payload):
        headers = await self.headers()
        response = await self.client.post(
            self.url,
            headers=headers,
            json={
                "systemInstruction": {"parts": [{"text": prompt}]},
                "contents": [{"role": "user", "parts": [{"text": payload}]}],
                "generationConfig": {
                    "temperature": 0,
                    "maxOutputTokens": 4096,
                    "responseMimeType": "application/json",
                    "responseSchema": google_schema(),
                },
            },
        )
        response.raise_for_status()
        body = response.json()
        if body.get("promptFeedback", {}).get("blockReason"):
            raise ProviderError("Model refused the request")
        candidate = body["candidates"][0]
        if candidate.get("finishReason") != "STOP":
            raise ProviderError("Incomplete model response")
        parts = candidate["content"]["parts"]
        return json.loads("".join(part["text"] for part in parts if not part.get("thought", False)))


class VertexProvider(GoogleProvider):
    name = "vertex"

    def __init__(self, settings, client):
        self.client, self.auth = client, VertexAuth()
        location = settings.vertex_location
        host = "aiplatform.googleapis.com" if location == "global" else location + "-aiplatform.googleapis.com"
        self.url = (
            f"https://{host}/v1/projects/{quote(settings.vertex_project_id, safe='')}/"
            f"locations/{quote(location, safe='')}/publishers/google/models/"
            f"{quote(settings.vertex_model, safe='')}:generateContent"
        )

    async def headers(self):
        return await self.auth.headers(self.url)


class AIStudioProvider(GoogleProvider):
    name = "aistudio"

    def __init__(self, settings, client):
        self.settings, self.client = settings, client
        self.url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            + quote(settings.aistudio_model, safe="")
            + ":generateContent"
        )

    async def headers(self):
        return {"x-goog-api-key": self.settings.gemini_api_key}


def build_providers(settings: Settings, client: httpx.AsyncClient):
    factories = {"vertex": VertexProvider, "groq": GroqProvider, "aistudio": AIStudioProvider}
    return [factories[name](settings, client) for name in settings.provider_order]
