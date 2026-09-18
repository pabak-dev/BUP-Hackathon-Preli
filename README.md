# GridWise: LLM-assisted campus energy optimization

One FastAPI service interprets operator notes with a real hosted model, validates the extracted directives, solves a 24-hour linear program, and independently replays the returned schedule. There is no frontend and no sample-specific production logic.

## Quickstart (Python 3.13)

Obtain this repository using the GitHub URL supplied with the submission, then open a terminal in its root. A Git remote has not yet been configured in this working copy; the team must provide the repository URL before submission. Python 3.13 is the tested version and matches the locked dependencies and Docker runtime.

Windows PowerShell:

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-dev.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Edit .env locally: configure provider credentials and explicit model IDs.
.venv\Scripts\python.exe -m app
```

Linux/macOS:

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --require-hashes -r requirements-dev.txt
test -f .env || cp .env.example .env
# Edit .env locally: configure provider credentials and explicit model IDs.
python -m app
```

For a production-only install use `requirements.txt` instead. Both files pin transitive versions and hashes. Run all commands from the repository root. The server binds to `0.0.0.0`; default port is `8000`. The `.env` file is loaded without overriding already-set environment variables. No environment activation is necessary for the Windows commands.

## Configuration and model

Default failover order: **Vertex AI -> Groq -> Google AI Studio**. Missing provider configuration is skipped. Set model IDs explicitly to models supported by your account, location and structured-output API; there are no assumed model defaults. Select Gemini Flash for Vertex, GPT-OSS for Groq and Gemini Flash-Lite for AI Studio as available. The previously used Groq ID was `openai/gpt-oss-120b`; verify current account access before choosing it.

| Variable name | Purpose / default |
|---|---|
| `LLM_PROVIDER_ORDER` | Ordered subset of `vertex,groq,aistudio`; defaults to all three in that order. |
| `VERTEX_PROJECT_ID` | Google Cloud project with Vertex AI enabled. |
| `VERTEX_LOCATION` | Location supported by your chosen Vertex model (including `global` when supported). |
| `VERTEX_MODEL` | Explicit Vertex model ID. |
| `GROQ_API_KEY`, `GROQ_MODEL` | Groq secret and explicit model ID. |
| `GEMINI_API_KEY`, `AISTUDIO_MODEL` | AI Studio secret and explicit model ID. |
| `LLM_PROVIDER_TIMEOUT_SECONDS` | Total time per provider including ADC and validation; default 6, maximum 7 seconds. |
| `GOOGLE_APPLICATION_CREDENTIALS` | Optional standard ADC path to an external credential/config file. Never commit that file. |
| `PORT` | HTTP port; default 8000. |

Migration: replace legacy `LLM_PROVIDER`, `LLM_MODEL`, and `LLM_BASE_URL` with the explicit variables above. A Groq key alone now also requires `GROQ_MODEL`. `.env` stays private and is excluded from Git and Docker; no credentials are embedded in source or images.

Vertex uses official `google-auth[requests]` Application Default Credentials, included in the locked dependencies. For local development install the Google Cloud CLI, enable billing and the Vertex AI API on your project, grant the identity appropriate Vertex AI permissions (normally Vertex AI User), then run:

```powershell
gcloud auth application-default login
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
gcloud services enable aiplatform.googleapis.com --project YOUR_PROJECT_ID
```

Set `VERTEX_PROJECT_ID`, `VERTEX_LOCATION`, and `VERTEX_MODEL` separately in `.env`. Cloud deployments should use an attached service account or workload identity. A local ADC file is not automatically available inside Docker: supply credentials securely at runtime or use the platform identity; never bake them into the image. See [Google ADC setup](https://cloud.google.com/docs/authentication/provide-credentials-adc) and [Vertex authentication](https://cloud.google.com/vertex-ai/docs/authentication).

Separate adapters normalize Groq strict JSON Schema output and Google's native `generateContent` structured output into the same internal `ModelOutput` and public `Directive` objects. Google's schema uses its supported subset; Pydantic always applies the full strict contract locally. Every note is interpreted by a generative model. The model receives only notes and battery capacity, and extracts relevance, one directive, hours, numeric values and a short explanation. It never receives an optimization task, demand arrays, tariffs or credentials.

## API examples

Run in a second terminal. On Windows, use `curl.exe` in place of `curl` if PowerShell aliases it.

```bash
curl --fail-with-body http://127.0.0.1:8000/health
curl --fail-with-body -X POST http://127.0.0.1:8000/optimize-energy -H "Content-Type: application/json" --data-binary @examples/request.json
```

Ready health is HTTP 200 with exactly `{"status":"ok"}`. Readiness requires at least one configured provider and a working local solver, without spending model quota on health probes. Valid credentials, model access and quota must additionally be checked with a real POST. Missing configuration/unready solver returns a safe 500; the specification does not prescribe an unready body.

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
request -> strict request validation -> Vertex / Groq / AI Studio attempts
        -> structural directive guardrails after each attempt -> LP optimization
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

The LLM understands language; deterministic code validates structure and math. There are no evidence fields, quoted-substring checks, time/number regex parsers, English-number normalizers, or deterministic linguistic reinterpretation. The prompt teaches multilingual semantic interpretation, end-exclusive windows, solar reduced BY versus remaining/TO, and percent-of-capacity reserves. Structurally valid outputs are accepted regardless of the original wording. This deliberately leaves semantic accuracy to the model; it cannot change scenario data through the directive schema.

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

One batched call handles all notes per provider attempt. Each configured provider is attempted once, in order, with a six-second total deadline (configurable up to seven). HTTP errors, timeouts, network failures, refusals, malformed JSON and invalid schema/ranges immediately advance to the next provider. Exhaustion returns a safe 500. Invalid clients never reach providers; infeasibility and optimizer/replay errors never trigger provider failover. The existing 27-second request deadline and three-second solver limit remain.

There is no application rate limiter, pacing, retry backoff, LLM concurrency cap or throttling queue. Transport redirects and retries are disabled by default. ADC refresh uses bounded fail-fast HTTP. An already running ADC thread may finish after cancellation, but cannot issue a model request afterward. Provider quotas and latency remain external constraints; three slow attempts can exceed the rubric's best latency tier even while remaining under the request deadline. Health performs no authentication or model request.

See [verification record](docs/verification.md) for completed checks, measured latency, and outstanding submission artifacts.

## Tests and public regression

Offline tests do not need a key and do not spend provider quota:

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m pytest tests/test_public_samples.py -q
```

These run real application code, guardrails, optimizer, and replay using an explicitly mocked provider transport. Public references are loaded automatically from the root JSON file and only used in tests. Tests compare directive semantics and optimal cost, never exact action sequences. Additional tests cover paraphrases, malformed input/output, provider failover/failure handling, no_op, every directive, repeated requests, zero/full batteries, and tampered schedules. Small random integer cases compare the LP optimum to an independent dynamic program.

Real provider tests (uses configured key and quota; all tests including 27 live cases):

```powershell
.venv\Scripts\python.exe -m pytest --live -q
```

Live tests have no artificial pacing. Offline runs block outbound provider/authentication HTTP and skip live tests; these skips are not evidence of live model accuracy.

Run all 10 public cases through a running local, Docker, or deployed HTTP service:

```powershell
.venv\Scripts\python.exe -m scripts.verify_samples --allow-live --url http://127.0.0.1:8000
```

Expected: `Passed 10/10`, matching reference directive semantics, valid replay against organizer reference directives, and cost differences <=0.01 BDT. The script checks recalculated totals and writes responses/latencies to `output/sample-report.json` (ignored by Git). Use `--repeat 2` for stability and `--output PATH` to preserve a report. Linux/macOS commands use the activated environment's `python` instead of the Windows executable path.

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
3. Configure the selected providers, explicit model IDs and Vertex ADC privately, allow the platform's `PORT`, and set health check path `/health`. Ensure outbound HTTPS access to the model provider, adequate quota, and no sleep during evaluation.
4. Expose HTTPS publicly with no login, VPN, manual approval, or private-network restriction. Keep both endpoints available throughout judging.
5. From a different machine/network, call health, POST the example, and run `python -m scripts.verify_samples --allow-live --url https://YOUR-SERVICE`. Check repeated cases and actual latency/failure rate.
6. Push and verify the pullable Docker fallback. Submit the public API base URL, repository, README/config/sample request+response, image reference/run command/env names, and accessible <=3-minute video. Use [submission checklist](docs/submission-checklist.md) and [video outline](docs/video-outline.md).

No hosted deployment, registry publication, GitHub visibility change, or video submission is implied by a successful local test. Those artifacts must be supplied through the team's accounts.

## Specification audit and limitations

[docs/spec-audit.md](docs/spec-audit.md) records the pre-code audit of both complete PDFs and all ten JSON examples, source precedence, rubric, and corrections to the proposed plan. Interpretation/application together carry 50/100 points; optimization, API, reliability, deployment/Docker, and documentation carry 10 each. Video has no base score but is the first tie-break.

- Unequal solar-reduction factors covering the same hour have no defined composition/precedence rule in the supplied problem. The service rejects this ambiguity; it does not silently multiply or choose one. Identical factors are redundant.
- The supplied problem does not define wraparound/cross-midnight semantics. The prompt does not invent a composition rule; contextual language interpretation is the model's responsibility. No deterministic language parser claims to resolve this ambiguity.
- The guide's optimization formula for zero optimum/nonzero team cost is visibly cut off after `quality_ratio`. No missing scoring rule has been invented in the service.
- Semantic model mistakes can survive structural checks. Tests measure this risk; the judge independently checks its own ground truth.
- Extremely large floating-point magnitudes may exceed solver numerical range. No artificial request bound is claimed by the specification; unsupported numerical solves fail in a controlled way.
- Hosted-provider availability, rate limits, and valid credentials remain external dependencies. Health does not validate quota or authenticate a key on every probe. All new provider adapters require account-specific live verification before judging; no hosted-model calls were made during the failover change.

## Files and credits

`app/` contains configuration, strict schemas, the real model adapter, deterministic guardrails, LP optimizer, independent validator, API, and service orchestration. `tests/` contains offline/live public regressions and hidden-style checks. `scripts/verify_samples.py` exercises HTTP deployments; `examples/` contains attributed organizer sample data; `docs/` contains the audit and submission/video aids.

External libraries/tools: Python, FastAPI/Starlette, Pydantic, HTTPX, Uvicorn, SciPy/HiGHS, NumPy, python-dotenv, google-auth, pytest, Ruff, uv, Docker; Groq's hosted OpenAI GPT-OSS model (or configured Google Gemini); OpenAI Codex assisted implementation and verification. Organizer problem/guide/public samples define the challenge and reference data. No live campus, utility, billing, or personal data is used.

## Manual provider checks (consume hosted-model quota)

These are opt-in commands, not part of offline verification. Run from the repository root. Each isolated smoke sends one model request and replays the resulting schedule. The full public regression sends ten requests, potentially up to thirty model attempts with failover.

```powershell
.venv\Scripts\python.exe -m scripts.smoke_provider --allow-live --provider vertex
.venv\Scripts\python.exe -m scripts.smoke_provider --allow-live --provider groq
.venv\Scripts\python.exe -m scripts.smoke_provider --allow-live --provider aistudio
# Start the API in one terminal:
.venv\Scripts\python.exe -m app
# Run the ten public cases in another:
.venv\Scripts\python.exe -m scripts.verify_samples --allow-live --url http://127.0.0.1:8000
# Local failure injection skips the primary without calling it; the fallback is real:
.venv\Scripts\python.exe -m scripts.smoke_provider --allow-live --provider chain --simulate-failure vertex
.venv\Scripts\python.exe -m scripts.smoke_provider --allow-live --provider chain --simulate-failure vertex groq
```

Failure injection exists only in the manual script; it never changes production behavior. It checks orchestration with a real fallback, not genuine provider outage behavior. Mocked tests cover actual HTTP 429/500/timeouts, malformed/refused output, strict guardrail rejection, all-provider exhaustion and no failover after math errors. Smoke scripts print safe results/provider names without raw provider errors or secrets.
