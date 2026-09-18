"""Live HTTP regression: real provider, canonical sample semantics, independent replay."""

import argparse
import json
import math
import time
from pathlib import Path

import httpx

from app.errors import ScheduleError
from app.schemas import Directive, OptimizeRequest
from app.validator import validate_schedule

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"


def verify(case, actual):
    reference = case["expected_output"]
    expected = reference["directive_interpretation"]
    interpretations = actual["directive_interpretation"]
    if len(interpretations) != len(expected):
        raise ValueError("Incorrect interpretation count")
    for given, truth in zip(interpretations, expected):
        for field in ("note_index", "applies", "directive_type"):
            if given[field] != truth[field]:
                raise ValueError("Incorrect directive " + field)
        adjustment = truth["structured_adjustment"]
        proposed = given["structured_adjustment"]
        if adjustment is None:
            if proposed is not None:
                raise ValueError("no_op adjustment must be null")
        else:
            if not isinstance(proposed, dict) or set(proposed) != set(adjustment):
                raise ValueError("Incorrect adjustment shape")
            for field, value in adjustment.items():
                if field == "hours":
                    if proposed[field] != value:
                        raise ValueError("Incorrect affected hours")
                elif not math.isclose(proposed[field], value, abs_tol=0.01, rel_tol=0):
                    raise ValueError("Incorrect numeric adjustment")
    request = OptimizeRequest.model_validate(case["input"])
    reported = [Directive.model_validate(d) for d in interpretations]
    validate_schedule(request, reported, actual)
    truth = [Directive.model_validate(d) for d in expected]
    validate_schedule(request, truth, {**actual, "directive_interpretation": expected}, tolerance=0.01)
    if not math.isclose(actual["total_cost_bdt"], reference["total_cost_bdt"], abs_tol=0.01, rel_tol=0):
        raise ValueError("Cost differs from public optimum by more than 0.01 BDT")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--delay", type=float, default=17, help="Seconds between requests; excluded from latency")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "sample-report.json")
    args = parser.parse_args()
    if args.repeat < 1 or args.delay < 0:
        parser.error("repeat must be positive and delay must be nonnegative")
    cases = json.loads(SAMPLES.read_text(encoding="utf-8-sig"))["cases"]
    records = []
    with httpx.Client(base_url=args.url.rstrip("/"), timeout=30) as client:
        health = client.get("/health")
        if health.status_code != 200 or health.json() != {"status": "ok"}:
            raise SystemExit("Health check failed")
        for iteration in range(args.repeat):
            for case in cases:
                if records:
                    time.sleep(args.delay)
                start = time.perf_counter()
                record = {"case": case["id"], "iteration": iteration + 1}
                try:
                    response = client.post("/optimize-energy", json=case["input"])
                    record["latency_seconds"] = time.perf_counter() - start
                    record["http_status"] = response.status_code
                    if response.status_code != 200:
                        raise ValueError("Service returned a non-success status")
                    actual = response.json()
                    verify(case, actual)
                    record.update(passed=True, response=actual)
                except (httpx.HTTPError, ValueError, KeyError, TypeError, RuntimeError, ScheduleError) as error:
                    # Do not log server response bodies, request data, or credentials.
                    record.update(passed=False, error_type=type(error).__name__)
                records.append(record)
                print(
                    f"{case['id']}: {'PASS' if record['passed'] else 'FAIL'} ({record.get('latency_seconds', 30):.3f}s)",
                    flush=True,
                )
    latencies = sorted(record.get("latency_seconds", 30) for record in records)
    report = {
        "cases": len(records),
        "passed": sum(record["passed"] for record in records),
        "p95_seconds": latencies[math.ceil(0.95 * len(latencies)) - 1],
        "results": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Passed {report['passed']}/{report['cases']}; p95={report['p95_seconds']:.3f}s; report: {args.output}")
    raise SystemExit(0 if report["passed"] == report["cases"] else 1)


if __name__ == "__main__":
    main()
