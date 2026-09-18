# Verification record

Verified locally on 2026-09-18 using the configured Groq `openai/gpt-oss-120b` model. No credentials are included in this record.

| Check | Result |
|---|---|
| Full suite including live tests | 161 passed in the full run (134 offline + 27 real-model cases); JUnit: `output/test-results.xml`. |
| Final expanded offline suite | 143 passed, 27 live tests explicitly skipped; JUnit: `output/offline-final.xml`. Nine additional replay/concurrency checks were added after the full live run. |
| Real-model language cases | All 10 public cases and 17 unseen paraphrase cases passed. |
| Final Docker HTTP regression | All 10 public cases passed via actual HTTP, real Groq calls, independent replay against organizer directives, total checks, and cost within 0.01 BDT. |
| Observed Docker HTTP p95 | 2.301 seconds (10 requests, nearest-rank p95; 17-second pacing excluded). |
| Docker build | Successful on Linux amd64; image `gridwise:preli`; hashed dependencies and digest-pinned base. |
| Default health | HTTP 200, exactly `{"status":"ok"}`; Docker health state healthy. |
| Configurable PORT | PORT=8080 health passed at host port 18080; first successful probe within 2.061 seconds of starting the probe script. |
| Concurrent/repeated requests | Tested; identical numerical schedules for fixed request/directives; no scenario-state leakage. |
| Independent optimizer check | 12 small random integer scenarios matched an independent dynamic program. |
| Schema audit | Request/battery/hour/response/directive/plan field names and directive enum match the source public schema metadata and PDF audit. Exactly two API routes. |
| Replay independence | No optimizer import; reconstructs directive effects and replays serialized rows independently. |
| No public hardcoding | AST/string checks found no public IDs, complete public note wording, reference schedules, or test imports in app code. |
| Secret handling | .env ignored; configured secret absent from all nonignored source/artifact files; clean image has no provider credentials or .env. |
| Static checks | Ruff and git diff --check passed. |

## Final Docker public results

| Case | Cost (BDT) | Latency (s) |
|---|---:|---:|
| SAMPLE-01 | 38365.00 | 2.286 |
| SAMPLE-02 | 42885.00 | 1.584 |
| SAMPLE-03 | 35480.00 | 1.870 |
| SAMPLE-04 | 40495.00 | 0.914 |
| SAMPLE-05 | 33950.00 | 1.460 |
| SAMPLE-06 | 34090.00 | 2.301 |
| SAMPLE-07 | 38550.00 | 1.815 |
| SAMPLE-08 | 37665.00 | 1.253 |
| SAMPLE-09 | 34873.00 | 1.395 |
| SAMPLE-10 | 41620.00 | 1.938 |

The machine-readable HTTP report and responses are at `output/docker-public-report.json` (ignored local artifact). Two dependency deprecation warnings arise in Starlette's HTTPX-based test client; all checks pass. They do not occur in the deployed API request path.

## Limits of these results

- The initial unpaced live run exhausted the observed Groq free-tier 8,000-token/minute limit. Pacing avoids this during regression, but does not solve a quota shortage under bursty judging traffic. Provision adequate quota before submission.
- p95 is from a small local Docker run, not an external hosted deployment or a load-test guarantee.
- Gemini is configurable but was not live-tested because only the Groq key was configured.
- Local image build/run is verified. No image was pushed or pulled from a team registry; no public deployment or external-network check was performed.
- No Git remote is configured. Repository publication/visibility timing, registry reference, deployed URL, and <=3-minute video still require the team.
- Undefined unequal overlapping solar reductions and unresolved/cross-midnight windows fail safely; the clipped scoring clause is documented in spec-audit.md.
- Temporary test containers were stopped/removed, freeing port 8000. The tested image remains available locally.

## Application source fingerprints

- `app/__init__.py`: `8c18af189289cc658d84b0825e131f8831d27c7d23085fe3c4130fd93db10044`
- `app/__main__.py`: `6cb747a15c7b86ec9b711e98cc0e21962ba21e377ec45cc80b39c9ea07cc7939`
- `app/config.py`: `74ce0f234aefcca3d4cb9607a2eba6994af10cb5ce5e5ea1c80b8483a4d67069`
- `app/errors.py`: `0b3a8e33c5d0d6cba02dca59b4fe2eaac534f950441ea74d54688ed61af16e37`
- `app/guardrails.py`: `2a28ef5d446fe071a905ae7ee07775d60128557d77ab86f3cc5ed9779818a613`
- `app/llm_interpreter.py`: `90cd5eaff43737c5cc934a4ad0dd15ed2f94d8bd198b6c34c449777452fcb208`
- `app/main.py`: `382703fe7faa142805789832ce4a530f36f2f8105426d5de6f3bc810e1dabbe3`
- `app/optimizer.py`: `90a716a44f19ea16f7c89959e28bc031876a1d8f5382c1527db38612be04c9e2`
- `app/schemas.py`: `3c71ee012c208c4ac4de6f8e3577a0a14ad3c674d808abb8b4ca62541f72a683`
- `app/service.py`: `9fa6d69ebd319ac190ccf8770c709beaa182dc89e5a163c6c6e90749c74f2c29`
- `app/validator.py`: `a8b5580aff334710f4fb7d99f4e4baeadae7d14de2c75491251f4c128158744b`
