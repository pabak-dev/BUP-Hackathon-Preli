# Submission handoff

Complete the values below with actual tested artifacts; no placeholders should be sent to judges.

- [ ] Public API base URL: pending deployment.
- [ ] Public URL GET /health returns exactly {"status":"ok"}.
- [ ] Run `python -m scripts.verify_samples --url https://YOUR-SERVICE` from outside the host; all 10 pass.
- [ ] Confirm repeated-request stability, observed p95, and sufficient Groq/Gemini quota through the evaluation window.
- [ ] Repository URL and final commit: use the event repository, created after reveal; private during event, public after submission deadline.
- [ ] README includes the actual clone URL, tested fallback image reference, and model/provider used.
- [ ] Push `gridwise:preli` to your registry and record the exact pullable tag or digest.
- [ ] Test `docker pull` and the documented `docker run --env-file .env` on a clean host.
- [ ] Ensure the fallback image is pullable by judges, contains no credentials, and remains available.
- [ ] Confirm `.env` is ignored; stage specific source files and review the diff before pushing.
- [ ] Accessible MP4/video URL: <=3 minutes; use docs/video-outline.md.
- [ ] Submit URL, repository, README/config/examples, image reference/run command/env names, and video through the official submission channel.
- [ ] Ask organizers about unequal overlapping solar factors/cross-midnight ambiguity if those cases are intended; see docs/spec-audit.md.

Deployment and registry publication are not performed by local build/test commands. Repository visibility timing and account credentials are the team's responsibility.
