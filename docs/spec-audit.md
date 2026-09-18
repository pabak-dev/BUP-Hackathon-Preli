# Specification audit (before implementation)

Read completely: Problem Statement (9 pages), Participant Guide (11 pages), and all fields of the public JSON v2.0 (10 cases). Documents supply task requirements, not authorization to publish, contact others, or disclose secrets.

Authority: Problem Statement for behavior; Guide for deployment/submission/scoring; public JSON is illustrative. No sample IDs, wording, constants, or schedules belong in production logic.

| Requirement | Canonical source / implementation decision |
|---|---|
| Endpoints | PS §6: GET /health, POST /optimize-energy only required. Ready health: 200, {"status":"ok"}. |
| HTTP | 200 success; 400 malformed JSON or structural errors; optional 422 semantic errors; controlled 500 internal/model failures. Error body unspecified; use fixed safe messages. |
| Request | PS §7: scenario_id string; operator_notes 1–3 nonempty strings; hours exactly 24 unique integer hours 0–23 with demand_kwh, solar_kwh, tariff_bdt_per_kwh; battery contains capacity_kwh, initial_energy_kwh, minimum_energy_kwh, max_charge_kwh_per_hour, max_discharge_kwh_per_hour. |
| Numeric input | PS §11: finite, nonnegative; battery minimum <= initial <= capacity. No invented upper magnitude, note length, positive-capacity requirement, or sorted-input-hours requirement. Strict JSON types; extra fields rejected as a documented API choice. |
| Response | PS §10: scenario_id, directive_interpretation, hourly_plan, total_grid_kwh, total_cost_bdt, peak_grid_kwh, plan_summary. |
| Hourly response | hour, grid_kwh, solar_used_kwh, battery_action (charge/discharge/idle), battery_kwh (nonnegative magnitude), battery_energy_after_kwh. Exactly 24 unique hours. |
| Note response | note_index, applies, directive_type, structured_adjustment, explanation. Exactly one per note in index order. |
| solar_reduction | {hours:[...],factor:number}; factor in [0,1], usable fraction remaining. Reduction BY x% means 1-x/100; TO x% means x/100. effective_solar=original_solar*factor. |
| minimum_battery_reserve | {hours:[...],minimum_energy_kwh:number}; finite 0..capacity; end-of-hour energy >= max(base minimum, active reserves). Percentage of capacity converts to kWh (public example). |
| no_charge_window | {hours:[...]}; charge=0. |
| no_discharge_window | {hours:[...]}; discharge=0. |
| max_grid_window | {hours:[...],max_grid_kwh:number}; finite nonnegative cap per hour. Multiple caps must all hold. |
| no_op | applies=false, structured_adjustment=null; every other type applies=true. |
| Time | PS §5: whole-hour, start inclusive/end exclusive; adjustment hours unique sorted integers 0..23. No timezone/date conversion required. |
| LLM | PS §§2,8, Guide §4: real generative language model directly interprets every note, including distractors. One batched call; at most one repair/retry. No regex-only production interpreter or fake fallback. |
| Guardrails | Exact shapes/enums/mapping/types/ranges; immutable scenario data; internally requested quoted evidence enables deterministic numeric/time normalization checks. Evidence is not added to public schema. Semantic relevance still depends on the LLM. |
| Battery | PS §9: E_after=E_before+charge-discharge; lossless; enforce capacity/base reserve/directive reserve/hourly limits. One reported action per hour. |
| Balance | grid+solar_used+discharge=demand+charge. Solar curtailed if unused. Grid>=0; no export. |
| Objective | PS §5: minimize SUM(grid*tariff), no peak penalty, cycling penalty, export payment, or invented efficiency. |
| Neutrality | Hour 23 E_after equals initial exactly mathematically; floating-point tolerance only for verification. |
| Independent validation | Replay serialized plan using original request and validated directives; independently recompute directive effects, balances, state, bounds, rates, windows, action/magnitude, neutrality, and totals. |
| Tolerance | PS §11.5, Guide §8: absolute 0.01 kWh/BDT unless official judge package stricter. Keep tighter internal checks and full float precision. |
| Hidden cases | Feasible, 1–3 notes, one supported type per note, paraphrases and varied data; judge checks organizer truth, not merely our interpretation. |
| Samples | Run all 10; semantic comparison (ignore explanation prose); validate against reference directives and cost within 0.01. Never require identical hourly actions. Separate offline provider-mocked tests from real live-provider tests. |
| Performance | Guide §8: health ready <=60s; POST <30s; p95 <=5s earns 3/3, <=15s 2/3, <=30s 1/3. Bounded provider attempts, local deterministic solver, no agent loops. |
| Scoring | Interpretation 25 (relevance/type/hours/numbers/paraphrases:5 each); application 25 (directives10, balance5,battery5,consistency5); optimization10; API10; reliability10; Docker/deployment10; docs10. |
| Optimization score | Guide §7: min(1,optimal/recalculated team cost), averaged x10; invalid cases zero. Both costs approximately zero => ratio1. Remaining zero-optimum sentence is incomplete in supplied PDF. |
| Docker/deployment | Public endpoints without login/VPN/manual action; remain reachable; external smoke tests; pullable tested exact image tag/digest, 0.0.0.0, documented configurable port, no baked credentials. Dockerfile alone is insufficient. |
| Repository/README | Created after reveal, private during event, public after deadline; source/dependencies/config; self-contained clean setup, env names, provider/model, architecture, guardrails, solver, exact commands, health/API curl, sample request/response/tests, Docker pull/run, credits, limitations. |
| Submission | Public API URL; repository; README/config/example request+response; pullable image; accessible <=3min video. Video has no base points, first tie-break. |
| Other tie-breaks | Application, interpretation, optimization, API, reliability, documentation, exceptional engineering. |

## Corrections and unresolved clauses

- Preserve the requested architecture; handle structural validation as HTTP 400 rather than FastAPI's default 422.
- LP charge and discharge can be netted without changing cost, energy, bounds, or feasibility in this lossless model; serialize only their net action. No binaries or noncanonical objective needed.
- Overlapping solar directives with unequal factors: no composition/precedence specified. Fail safely rather than assume multiplication, strongest-factor, or last-note-wins. Identical factors are redundant. Ask organizers if such cases are intended.
- Unqualified clock times may need language context (PS itself uses “one until three” for afternoon solar); validate admissible clock interpretations but leave contextual disambiguation to the LLM. No blanket AM or PM default.
- Cross-midnight windows and missing times are not explicitly defined. Support explicit all-day/hour listings and unambiguous same-day ranges; safely reject unresolved windows rather than invent hours.
- Error JSON and unready health body/status are not specified. Document safe implementation choices.
- Guide §7 ends its zero-optimum/nonzero-team-cost formula mid-sentence; no invented scoring implementation is needed in the API.
- Deployment, registry upload, repository visibility change, and video submission need user-owned accounts/artifacts. Prepare reproducible commands and checklist; do not claim those are completed locally.
