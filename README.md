# GridWise: LLM-assisted campus energy optimization

One FastAPI service interprets operator notes with a real hosted model, validates the extracted directives, solves a 24-hour linear program, and independently replays the returned schedule. There is no frontend and no sample-specific production logic.

## Quickstart (Python 3.13)

Obtain this repository using the GitHub URL supplied with the submission, then open a terminal in its root. A Git remote has not yet been configured in this working copy; the team must provide the repository URL before submission. Python 3.13 is the tested version and matches the locked dependencies and Docker runtime.

Windows PowerShell:

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-dev.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Edit .env locally and set GROQ_API_KEY.
.venv\Scripts\python.exe -m app
```

Linux/macOS:

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --require-hashes -r requirements-dev.txt
test -f .env || cp .env.example .env
# Edit .env locally and set GROQ_API_KEY.
python -m app
```

For a production-only install use `requirements.txt` instead. Both files pin transitive versions and hashes. Run all commands from the repository root. The server binds to `0.0.0.0`; default port is `8000`. The `.env` file is loaded without overriding already-set environment variables. No environment activation is necessary for the Windows commands.

## Configuration and model

| Variable name | Purpose / default |
|---|---|
| `GROQ_API_KEY` | Required secret for the default Groq provider; obtain from your Groq account and set privately. |
| `LLM_PROVIDER` | Optional: `groq` (default) or `gemini`. |
| `GEMINI_API_KEY` | Required instead of GROQ_API_KEY when selecting Gemini; obtain from Google AI Studio. |
| `LLM_MODEL` | Optional model override. Groq default: `openai/gpt-oss-120b`; Gemini default: `gemini-2.5-flash`. |
| `LLM_BASE_URL` | Optional API endpoint override; normal provider URLs are selected automatically. |
| `PORT` | Optional HTTP port; default `8000`. |

Only `GROQ_API_KEY` is needed for the default configuration. No key values belong in this README, Git, Docker layers, screenshots, or submission fields. `.env` is ignored by Git and excluded from Docker's allowlisted build context.

Groq uses `https://api.groq.com/openai/v1/chat/completions`. Gemini uses `https://generativelanguage.googleapis.com/v1beta/openai/chat/completions`. The same HTTP adapter requests strict JSON Schema output. See [Groq structured outputs](https://console.groq.com/docs/structured-outputs), [GPT-OSS 120B](https://console.groq.com/docs/model/openai/gpt-oss-120b), and [Gemini OpenAI compatibility](https://ai.google.dev/gemini-api/docs/openai). Gemini is an optional configuration, not an automatically invoked fallback; test its model/schema access before switching a deployment.

The model is responsible only for relevance, directive type, affected hours, numeric values, and a short explanation. It receives notes and battery capacity (needed for percentage reserves), never credentials, demand arrays, tariffs, or an optimization task. Every request calls the real model, including irrelevant notes and repeated requests. There is no regex-only interpreter, cached sample answer, or silent no_op fallback.

## API examples

Run in a second terminal. On Windows, use `curl.exe` in place of `curl` if PowerShell aliases it.

```bash
curl --fail-with-body http://127.0.0.1:8000/health
curl --fail-with-body -X POST http://127.0.0.1:8000/optimize-energy -H "Content-Type: application/json" --data-binary @examples/request.json
```

Ready health is HTTP 200 with exactly `{"status":"ok"}`. Readiness requires a configured provider key and a working local solver, without spending model quota on health probes. A valid key/quota must additionally be checked with a real POST. Missing configuration/unready solver returns a safe 500; the specification does not prescribe an unready body.

`examples/request.json` is the first organizer public request. `examples/reference-response.json` is its organizer reference response, clearly separated from generated results. A successful implementation can return a different hourly schedule with the same optimal cost. Request fields are `scenario_id`, 1Ã¢â‚¬â€œ3 nonempty `operator_notes`, 24 unique `hours`, and `battery`. Inputs are strict JSON types, finite and nonnegative; duplicate JSON keys, unknown fields, missing fields, NaN/Infinity, coerced numeric strings, and inconsistent battery bounds are rejected. Input hours may be in any order. No undocumented positive minimum capacity or arbitrary numeric magnitude maximum is imposed.

The response contains only `scenario_id`, `directive_interpretation`, `hourly_plan`, `total_grid_kwh`, `total_cost_bdt`, `peak_grid_kwh`, and `plan_summary`. Every plan row has `hour`, `grid_kwh`, `solar_used_kwh`, `battery_action`, `battery_kwh`, and `battery_energy_after_kwh`.

| Status | Behavior |
|---|---|
| 200 | Exact health success or independently validated optimization response. |
| 400 | Malformed JSON or structurally/semantically invalid request data (the optional 422 distinction is not required). |
| 422 | A well-formed scenario is infeasible under its validated directives. |
| 500 | Controlled model/provider/timeout/solver/replay failure; fixed safe JSON message. |

Errors contain an `error` string. Provider bodies, API keys, raw prompts, and stack traces are never returned or logged by application error handlers.

## Architecture and correctness

```text
request -> strict request validation -> one batched hosted LLM call
        -> deterministic directive/evidence guardrails -> LP optimization
        -> response serialization -> independent replay -> success JSON
```

The only allowed directives and exact public adjustments are:

| Directive | structured_adjustment |
|---|---|
| `solar_reduction` | `{"hours":[...],"factor":number}` |
| `minimum_battery_reserve` | `{"hours":[...],"minimum_energy_kwh":number}` |
| `no_charge_window` | `{"hours":[...]}` |
| `no_discharge_window` | `{"hours":[...]}` |
| `max_grid_window` | `{"hours":[...],"max_grid_kwh":number}` |
| `no_op` | `null` |

There must be exactly one ordered interpretation per note. Only no_op has `applies=false`; all other types have `applies=true`. Pydantic rejects extra adjustment fields, invalid enums, noninteger/duplicate/unsorted/out-of-range hours, nonfinite/negative values, factors outside [0,1], and reserves exceeding capacity.

Internally, the model supplies exact quoted time and numeric evidence. General deterministic normalizers check whole-hour start-inclusive/end-exclusive ranges, AM/PM/noon/midnight, 24-hour clocks, explicit all-day/hour lists, numeric words, supported fractions, percent-of-capacity reserves, and remaining versus reduced solar. Evidence is stripped before public serialization. Unsupported or unresolved evidence is rejected, with at most one repair. These checks constrain the model's extraction; relevance and linguistic context still require the model. Code does not manufacture a directive when interpretation fails.

### Mathematical model

SciPy `linprog(method="highs-ds")` runs HiGHS dual simplex with fixed variable/constraint order, presolve defaults, one solver thread, and a 3-second solver limit. It proves an LP optimum before success. It uses nonnegative grid, solar-used, charge, discharge, and end-of-hour energy variables for all 24 hours.

```text
minimize sum(grid[h] * tariff[h])
grid[h] + solar_used[h] + discharge[h] = demand[h] + charge[h]
energy[h] = energy[h-1] + charge[h] - discharge[h]
energy[-1] = initial_energy; energy[23] = initial_energy
0 <= solar_used[h] <= original_solar[h] * applicable_factor
active_reserve[h] <= energy[h] <= capacity
0 <= charge[h] <= allowed_charge_rate[h]
0 <= discharge[h] <= allowed_discharge_rate[h]
0 <= grid[h] <= active_grid_cap[h] (when present)
```

The battery is lossless, unused solar may be curtailed, and grid export is prohibited. Active reserves take the maximum of base/all directive reserves; caps take the minimum of applicable caps. No-charge/no-discharge windows set the respective bound to zero. There is no cycling penalty, peak penalty, invented efficiency, or secondary objective. If the LP contains simultaneous charge/discharge, subtract their common amount: the net preserves all equations, objective, and upper bounds in this lossless model. Only one charge/discharge/idle action is serialized, with a nonnegative magnitude.

`app/validator.py` independently reconstructs solar and directive limits from the original scenario, replays battery state, checks every balance/bound/rate/window/action, and verifies final neutrality. It does not import the optimizer or trust its matrices, feasibility status, or effective profiles. Totals use the final public plan with full float precision, not rounded solver summaries. Internal replay uses absolute tolerance 1e-6; public comparison uses the documented 0.01 kWh/BDT tolerance.

### Reliability and latency

One model call handles all 1Ã¢â‚¬â€œ3 notes. A maximum of two provider attempts covers transient failures or one structured-output repair; each attempt has a 10-second total deadline. The request deadline is 27 seconds, leaving margin below the judge's 30-second timeout. Temperature is zero and GPT-OSS reasoning effort is low. There are no agents, retrieval, training, or model-based optimization loops. The optimizer is deterministic for fixed inputs/directives and runtime; model interpretation is not mathematically guaranteed deterministic.

Groq free-tier quota observed during development was 8,000 tokens/minute. A burst can exhaust quota even with fast individual responses. The regression runner spaces requests by 17 seconds by default; that spacing is excluded from measured request latency. Judging traffic may require a paid quota or another tested model/account. The guide requires p95 <=5 seconds for full latency points, <=15 seconds for partial credit, health readiness within 60 seconds, and availability throughout evaluation. Local test measurements are not a guarantee of deployed latency.

See [verification record](docs/verification.md) for completed checks, measured latency, and outstanding submission artifacts.

## Tests and public regression

Offline tests do not need a key and do not spend provider quota:

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m pytest tests/test_public_samples.py -q
```

These run real application code, guardrails, optimizer, and replay using an explicitly mocked provider transport. Public references are loaded automatically from the root JSON file and only used in tests. Tests compare directive semantics and optimal cost, never exact action sequences. Additional tests cover paraphrases, malformed input/output, repair/failure handling, no_op, every directive, repeated requests, zero/full batteries, and tampered schedules. Small random integer cases compare the LP optimum to an independent dynamic program.

Real provider tests (uses configured key and quota; all tests including 27 live cases):

```powershell
.venv\Scripts\python.exe -m pytest --live -q
```

Each live case is paced by 17 seconds to fit the observed free-tier quota. Offline test runs explicitly report these as skipped; skipped live tests are not evidence of LLM accuracy.

Run all 10 public cases through a running local, Docker, or deployed HTTP service:

```powershell
.venv\Scripts\python.exe -m scripts.verify_samples --url http://127.0.0.1:8000
```

Expected: `Passed 10/10`, matching reference directive semantics, valid replay against organizer reference directives, and cost differences <=0.01 BDT. The script checks recalculated totals and writes responses/latencies to `output/sample-report.json` (ignored by Git). Use `--repeat 2` for stability, `--delay 0` only with adequate provider quota, and `--output PATH` to preserve a report. Linux/macOS commands use the activated environment's `python` instead of the Windows executable path.

## Docker build and fallback

The base image is pinned by digest; all Python dependencies are hash-locked. The container runs as an unprivileged user and includes only application source and dependencies. It does not copy `.env`, tests, sample JSON, or local reports. Install Docker Engine/Desktop with Linux containers.

```bash
docker build -t gridwise:preli .
docker run --rm --name gridwise -p 8000:8000 --env-file .env gridwise:preli
curl --fail-with-body http://127.0.0.1:8000/health
```

Custom port example:

```bash
docker run --rm --name gridwise -p 8080:8080 --env-file .env -e PORT=8080 gridwise:preli
```

A Dockerfile/local image is not the required pullable fallback artifact. Choose your actual registry namespace and exact version tag, authenticate, then:

```bash
docker tag gridwise:preli YOUR_REGISTRY/gridwise:preli-v1
docker push YOUR_REGISTRY/gridwise:preli-v1
docker pull YOUR_REGISTRY/gridwise:preli-v1
docker run --rm --name gridwise -p 8000:8000 --env-file .env YOUR_REGISTRY/gridwise:preli-v1
```

Replace `YOUR_REGISTRY` with your Docker Hub namespace or registry path. Before submitting, record the real pullable image tag/digest here and in the submission form, verify pull/run on a clean machine, and keep it accessible to judges. The user supplies runtime credentials through environment variables; no secrets are built into the image.

## Deployment and submission

1. Create/use the event GitHub repository after reveal, keep it private during the event, and push reviewed source. Make it public only after the submission deadline.
2. Deploy this Dockerfile on any public container host (Render/Railway/Fly/etc.), or install `requirements.txt` and run `python -m app` on a Python 3.13 host. No platform-specific application code is required.
3. Configure `GROQ_API_KEY` privately (or select/configure Gemini), allow the platform's `PORT`, and set health check path `/health`. Ensure outbound HTTPS access to the model provider, adequate quota, and no sleep during evaluation.
4. Expose HTTPS publicly with no login, VPN, manual approval, or private-network restriction. Keep both endpoints available throughout judging.
5. From a different machine/network, call health, POST the example, and run `python -m scripts.verify_samples --url https://YOUR-SERVICE`. Check repeated cases and actual latency/failure rate.
6. Push and verify the pullable Docker fallback. Submit the public API base URL, repository, README/config/sample request+response, image reference/run command/env names, and accessible <=3-minute video. Use [submission checklist](docs/submission-checklist.md) and [video outline](docs/video-outline.md).

No hosted deployment, registry publication, GitHub visibility change, or video submission is implied by a successful local test. Those artifacts must be supplied through the team's accounts.

## Specification audit and limitations

[docs/spec-audit.md](docs/spec-audit.md) records the pre-code audit of both complete PDFs and all ten JSON examples, source precedence, rubric, and corrections to the proposed plan. Interpretation/application together carry 50/100 points; optimization, API, reliability, deployment/Docker, and documentation carry 10 each. Video has no base score but is the first tie-break.

- Unequal solar-reduction factors covering the same hour have no defined composition/precedence rule in the supplied problem. The service rejects this ambiguity; it does not silently multiply or choose one. Identical factors are redundant.
- The supplied problem does not define wraparound/cross-midnight windows. Clear ranges ending at midnight are supported; windows crossing into the next day or unresolved/missing times fail safely. English whole-hour expressions and common English numeric fractions are supported by the evidence checker. Unknown phrasing can safely fail instead of being guessed.
- The statement's afternoon example omits AM/PM in one paraphrase. The model supplies contextual disambiguation; deterministic checks validate possible clock mappings, not arbitrary English meaning.
- The guide's optimization formula for zero optimum/nonzero team cost is visibly cut off after `quality_ratio`. No missing scoring rule has been invented in the service.
- Semantic model mistakes can survive structural/evidence checks. Tests measure this risk; the judge independently checks its own ground truth.
- Extremely large floating-point magnitudes may exceed solver numerical range. No artificial request bound is claimed by the specification; unsupported numerical solves fail in a controlled way.
- Hosted-provider availability, rate limits, and valid credentials remain external dependencies. Health does not validate quota or authenticate a key on every probe. Gemini configuration needs its own live verification if used.

## Files and credits

`app/` contains configuration, strict schemas, the real model adapter, deterministic guardrails, LP optimizer, independent validator, API, and service orchestration. `tests/` contains offline/live public regressions and hidden-style checks. `scripts/verify_samples.py` exercises HTTP deployments; `examples/` contains attributed organizer sample data; `docs/` contains the audit and submission/video aids.

External libraries/tools: Python, FastAPI/Starlette, Pydantic, HTTPX, Uvicorn, SciPy/HiGHS, NumPy, python-dotenv, pytest, Ruff, uv, Docker; Groq's hosted OpenAI GPT-OSS model (or configured Google Gemini); OpenAI Codex assisted implementation and verification. Organizer problem/guide/public samples define the challenge and reference data. No live campus, utility, billing, or personal data is used.
