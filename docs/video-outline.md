# Maximum 3-minute architecture / solution video

The guide makes this mandatory and the first tie-break for equal total scores, with no base points. Record the actual running service; do not claim tests or deployments that have not completed.

| Time | Demonstration / narration |
|---|---|
| 0:00–0:20 | Explain the 24-hour campus problem: demand, solar, tariffs, battery, and natural-language operational notes. Correct constraints precede low cost. |
| 0:20–0:50 | Show README pipeline: FastAPI → real Groq GPT-OSS 120B → Pydantic/evidence guardrails → SciPy HiGHS LP → independent replay → exact JSON. |
| 0:50–1:20 | Show one interpretation: end-exclusive hours, remaining solar fraction, irrelevant no_op. Explain that the model cannot optimize or overwrite scenario parameters. |
| 1:20–1:50 | Show LP energy/state equations and final neutrality; show independent replay and exact totals. Explain that valid equal-cost schedules can differ. |
| 1:50–2:25 | Run /health and a POST using examples/request.json. Show returned directives, 24 hours, and cost. Show completed public regression report, real provider, and offline tests. |
| 2:25–2:50 | Show the Docker command and reachable deployment URL. Explain environment names, secrets excluded, provider quotas, and documented ambiguity handling. |
| 2:50–3:00 | Show the submission artifact list. Stop by 3:00. |

Keep .env, API headers, account dashboards, and terminal history containing secrets off-screen. Provide an MP4 or a judge-accessible link and test access from a signed-out browser.
