# GridWise

Backend-only submission for the **BUP CSE Fest 2026 Preliminary Hackathon**.

GridWise accepts a 24-hour campus energy scenario plus natural-language operator notes, interprets each note with a hosted LLM, validates the extracted directives, solves the minimum-cost schedule with linear programming, and independently replays the final plan before returning it.

## Submission

- **Public API:** `http://103.174.50.194:8000`
- **Health:** `http://103.174.50.194:8000/health`
- **Repository:** `https://github.com/pabak-dev/BUP-Hackathon-Preli`
- **Docker image:** `pabakdev/gridwise:preli-v1`
- **Docker digest:** `sha256:c618fb3b63f263ae75c26edab1b09a35a8b7ccedb1b3f422f46ee8fd45c80add`

### Deployed verification

The public VPS deployment was tested against all 10 organizer-provided public cases:

```text
Passed: 10 / 10
p95 latency: 1.749 s
```

All 10 requests returned HTTP 200 and passed directive, replay, and optimal-cost checks.

---

## Architecture

```text
Request
  -> strict request validation
  -> LLM interpretation
       Vertex AI
         -> Groq fallback
           -> Google AI Studio fallback
  -> deterministic directive validation
  -> LP optimizer
  -> independent schedule replay
  -> response
```

### LLM provider order

1. **Google Vertex AI** — `gemini-3.8-flash`
2. **Groq** — `openai/gpt-oss-120b`
3. **Google AI Studio** — `gemini-3.5-flash-lite`

Each configured provider is attempted at most once. Provider failures such as timeout, HTTP 429/5xx, refusal, malformed JSON, or invalid structured output immediately fall through to the next configured provider.

There is no application-side rate limiter, request pacing, retry sleep, or throttling queue.

### Language handling

The LLM handles natural-language understanding. Deterministic code validates the resulting structure and numeric safety rather than trying to re-interpret operator language with regexes.

This keeps the system tolerant of paraphrases and multilingual wording while still enforcing a strict directive schema.

Supported directives:

| Directive                 | Adjustment                                    |
| ------------------------- | --------------------------------------------- |
| `solar_reduction`         | `{"hours":[...],"factor":number}`             |
| `minimum_battery_reserve` | `{"hours":[...],"minimum_energy_kwh":number}` |
| `no_charge_window`        | `{"hours":[...]}`                             |
| `no_discharge_window`     | `{"hours":[...]}`                             |
| `max_grid_window`         | `{"hours":[...],"max_grid_kwh":number}`       |
| `no_op`                   | `null`                                        |

Guardrails enforce note ordering, valid directive type, exact adjustment shape, no extra fields, correct `applies` semantics, sorted unique hours in `0..23`, finite numeric values, valid solar factors, and reserve bounds.

---

## Optimization

The schedule is solved with SciPy HiGHS:

```python
scipy.optimize.linprog(method="highs-ds")
```

Objective:

```text
minimize sum(grid[h] * tariff[h])
```

Core constraints:

```text
grid[h] + solar_used[h] + discharge[h]
    = demand[h] + charge[h]

energy[h]
    = energy[h-1] + charge[h] - discharge[h]

energy[23] = initial_energy
```

The optimizer also enforces:

- battery capacity and minimum reserve
- hourly charge/discharge limits
- solar availability after active reductions
- no-charge / no-discharge windows
- active grid caps
- nonnegative grid import
- no grid export
- final battery neutrality

`app/validator.py` independently reconstructs the active constraints from the original request and validated directives, then replays the final 24-hour schedule. HTTP 200 is returned only after this validation passes.

---

## API

### `GET /health`

```bash
curl http://103.174.50.194:8000/health
```

Expected:

```json
{ "status": "ok" }
```

### `POST /optimize-energy`

Using the included sample request:

```bash
curl --fail-with-body \
  -X POST http://103.174.50.194:8000/optimize-energy \
  -H "Content-Type: application/json" \
  --data-binary @examples/request.json
```

Successful responses contain:

```text
scenario_id
directive_interpretation
hourly_plan
total_grid_kwh
total_cost_bdt
peak_grid_kwh
plan_summary
```

### Status codes

| Code  | Meaning                                                  |
| ----- | -------------------------------------------------------- |
| `200` | Valid health response or validated optimization result   |
| `400` | Malformed or invalid request                             |
| `422` | Well-formed scenario is infeasible                       |
| `500` | Controlled interpretation/provider/solver/replay failure |

Public errors do not expose prompts, provider bodies, stack traces, API keys, or credentials.

---

## Local Setup

Tested with **Python 3.13**.

```bash
git clone https://github.com/pabak-dev/BUP-Hackathon-Preli.git
cd BUP-Hackathon-Preli
```

### Windows PowerShell

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-dev.txt
Copy-Item .env.example .env
# Fill in .env with credentials/model access available to you.
.venv\Scripts\python.exe -m app
```

### Linux / macOS

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --require-hashes -r requirements-dev.txt
cp .env.example .env
# Fill in .env with credentials/model access available to you.
python -m app
```

For production-only dependencies:

```bash
python -m pip install --require-hashes -r requirements.txt
```

---

## Configuration

Example `.env`:

```env
LLM_PROVIDER_ORDER=vertex,groq,aistudio

VERTEX_PROJECT_ID=<YOUR_GCP_PROJECT_ID>
VERTEX_LOCATION=global
VERTEX_MODEL=gemini-3.8-flash

GROQ_API_KEY=<YOUR_GROQ_API_KEY>
GROQ_MODEL=openai/gpt-oss-120b

GEMINI_API_KEY=<YOUR_GEMINI_API_KEY>
AISTUDIO_MODEL=gemini-3.5-flash-lite

LLM_PROVIDER_TIMEOUT_SECONDS=6
PORT=8000
```

Only providers with complete configuration are used. The model IDs above are the models used by the submitted deployment; evaluators may substitute compatible models available to their own accounts.

### Vertex authentication

Vertex uses Google Application Default Credentials.

For local authentication:

```bash
gcloud auth application-default login
gcloud auth application-default set-quota-project <YOUR_GCP_PROJECT_ID>
gcloud services enable aiplatform.googleapis.com --project <YOUR_GCP_PROJECT_ID>
```

The submitted deployment uses the team's own Google Cloud project, but evaluators should use a project they control and have permission to access.

Never commit ADC credential files or API keys.

---

## Testing

### Offline tests

These do not use hosted-model quota:

```bash
python -m pytest -q
```

### Individual live provider checks

These consume hosted-model quota:

```bash
python -m scripts.smoke_provider --allow-live --provider vertex
python -m scripts.smoke_provider --allow-live --provider groq
python -m scripts.smoke_provider --allow-live --provider aistudio
```

### Public sample regression

Against the submitted deployment:

```bash
python -m scripts.verify_samples --allow-live --url http://103.174.50.194:8000
```

Against a local deployment:

```bash
python -m scripts.verify_samples --allow-live --url http://127.0.0.1:8000
```

The verifier checks directive semantics, independently replays schedules, validates totals, and checks optimal cost within the organizer tolerance.

---

## Docker

### Pull submitted image

```bash
docker pull pabakdev/gridwise:preli-v1
```

Exact submitted digest:

```text
sha256:c618fb3b63f263ae75c26edab1b09a35a8b7ccedb1b3f422f46ee8fd45c80add
```

Pull by digest:

```bash
docker pull pabakdev/gridwise@sha256:c618fb3b63f263ae75c26edab1b09a35a8b7ccedb1b3f422f46ee8fd45c80add
```

Run with any configured provider set:

```bash
docker run --rm \
  --name gridwise \
  -p 8000:8000 \
  --env-file .env \
  pabakdev/gridwise:preli-v1
```

For Vertex ADC, mount a credential file at runtime:

```bash
docker run --rm \
  --name gridwise \
  -p 8000:8000 \
  --env-file .env \
  -v /path/to/application_default_credentials.json:/run/secrets/gcp-adc.json:ro \
  -e GOOGLE_APPLICATION_CREDENTIALS=/run/secrets/gcp-adc.json \
  pabakdev/gridwise:preli-v1
```

The published image contains no API keys or Google credentials.

---

## Repository Structure

```text
app/
  config.py
  guardrails.py
  llm_interpreter.py
  main.py
  model_contract.py
  optimizer.py
  providers.py
  schemas.py
  service.py
  validator.py

tests/
scripts/
examples/
docs/
```

## Known Limitations

- Natural-language interpretation still depends on hosted-model accuracy.
- Provider availability and quota are external dependencies, mitigated by three-provider failover.
- Unequal overlapping `solar_reduction` factors have no defined composition rule in the supplied specification, so that ambiguity is rejected.
- Extremely large floating-point magnitudes may exceed practical solver numerical limits.

## Main Dependencies

Python 3.13, FastAPI, Pydantic, HTTPX, Uvicorn, SciPy/HiGHS, NumPy, google-auth, pytest, and Docker.

OpenAI Codex assisted implementation and verification.
