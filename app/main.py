import asyncio
import json
import logging
import warnings
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.config import Settings
from app.errors import InfeasibleError, InterpretationError, ProviderError, ScheduleError
from app.llm_interpreter import LLMInterpreter
from app.schemas import OptimizeRequest
from app.service import build_response

logger = logging.getLogger("gridwise")


def strict_json(raw: bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError("Nonfinite JSON number")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=reject_constant)


def create_app(settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None):
    config = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(
            timeout=config.timeout_seconds, transport=transport, follow_redirects=False
        ) as client:
            app.state.interpreter = LLMInterpreter(config, client)
            # Prove the installed solver works before returning readiness. No provider quota
            # is spent by health probes; live credentials are verified by smoke tests.
            from scipy.optimize import OptimizeWarning, linprog

            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=OptimizeWarning, message="Unrecognized options detected.*")
                smoke = linprog([1.0], bounds=[(0, 1)], method="highs-ds", options={"threads": 1, "parallel": False})
            app.state.solver_ready = bool(smoke.success)
            yield

    api = FastAPI(title="GridWise", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @api.get("/health")
    async def health():
        if not config.api_key or not getattr(api.state, "solver_ready", False):
            return JSONResponse({"error": "Service is not configured or ready"}, status_code=500)
        return {"status": "ok"}

    @api.post("/optimize-energy")
    async def optimize_energy(request: Request):
        try:
            data = strict_json(await request.body())
            scenario = OptimizeRequest.model_validate(data)
        except (ValueError, UnicodeError, ValidationError, RecursionError):
            return JSONResponse(
                {"error": "Invalid request: expected the documented scenario JSON schema"}, status_code=400
            )
        try:
            async with asyncio.timeout(config.request_timeout_seconds):
                directives = await api.state.interpreter.interpret(scenario)
                return await run_in_threadpool(build_response, scenario, directives)
        except InfeasibleError:
            return JSONResponse({"error": "No feasible schedule satisfies the validated directives"}, status_code=422)
        except (InterpretationError, ProviderError):
            logger.warning("Operator interpretation failed")
            return JSONResponse({"error": "Operator notes could not be safely interpreted"}, status_code=500)
        except (TimeoutError, ScheduleError):
            logger.warning("Scheduling or replay failed")
            return JSONResponse({"error": "A validated schedule could not be produced"}, status_code=500)
        except Exception:  # Public boundary must never leak internal exceptions.
            logger.error("Controlled internal failure")
            return JSONResponse({"error": "Internal processing error"}, status_code=500)

    return api


app = create_app()
