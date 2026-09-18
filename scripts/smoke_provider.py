"""Explicit opt-in smoke tests: one scenario, real model quota, independent replay."""

import argparse
import asyncio
import json
import logging
from dataclasses import replace
from pathlib import Path

import httpx

from app.config import Settings
from app.errors import ProviderError
from app.llm_interpreter import LLMInterpreter
from app.providers import build_providers
from app.schemas import OptimizeRequest
from app.service import build_response


class SimulatedFailure:
    def __init__(self, name):
        self.name = name

    async def generate(self, prompt, payload):
        raise ProviderError("Manual test injected provider failure")


async def run(args):
    settings = Settings.from_env()
    if args.provider != "chain":
        settings = replace(settings, provider_order=(args.provider,))
    if not all(settings.configured(name) for name in settings.provider_order):
        raise SystemExit("Configure all selected providers and model IDs first")
    request = OptimizeRequest.model_validate(json.loads(args.input.read_text(encoding="utf-8-sig")))
    async with httpx.AsyncClient(timeout=settings.timeout_seconds, follow_redirects=False) as client:
        providers = build_providers(settings, client)
        providers = [SimulatedFailure(p.name) if p.name in args.simulate_failure else p for p in providers]
        async with asyncio.timeout(settings.request_timeout_seconds):
            directives = await LLMInterpreter(settings, client, providers).interpret(request)
            result = await asyncio.to_thread(build_response, request, directives)
    print(
        json.dumps(
            {
                "directive_interpretation": result["directive_interpretation"],
                "total_cost_bdt": result["total_cost_bdt"],
                "replay": "passed",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-live", action="store_true", required=True)
    parser.add_argument("--provider", choices=["vertex", "groq", "aistudio", "chain"], required=True)
    parser.add_argument("--simulate-failure", nargs="*", choices=["vertex", "groq", "aistudio"], default=[])
    parser.add_argument("--input", type=Path, default=Path("examples/request.json"))
    args = parser.parse_args()
    if args.simulate_failure and args.provider != "chain":
        parser.error("Failure injection is only supported with --provider chain")
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("gridwise").setLevel(logging.INFO)
    try:
        asyncio.run(run(args))
    except Exception:
        raise SystemExit("Smoke test failed; check configuration, credentials, quota and model/schema access") from None


if __name__ == "__main__":
    main()
