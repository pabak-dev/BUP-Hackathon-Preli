import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas import Directive, OptimizeRequest
from app.validator import JUDGE_TOLERANCE, validate_schedule
from tests.conftest import CASES, mock_client


def assert_public_result(case, response):
    expected = case["expected_output"]
    actual = response["directive_interpretation"]
    assert len(actual) == len(expected["directive_interpretation"])
    for result, reference in zip(actual, expected["directive_interpretation"]):
        for key in ("note_index", "applies", "directive_type"):
            assert result[key] == reference[key]
        adjustment = reference["structured_adjustment"]
        if adjustment is None:
            assert result["structured_adjustment"] is None
        else:
            assert set(result["structured_adjustment"]) == set(adjustment)
            for key, value in adjustment.items():
                if key == "hours":
                    assert result["structured_adjustment"][key] == value
                else:
                    assert result["structured_adjustment"][key] == pytest.approx(value, abs=0.01, rel=0)
    request = OptimizeRequest.model_validate(case["input"])
    # Replay against reference ground truth, not only the team's self-reported interpretation.
    truth = [Directive.model_validate(d) for d in expected["directive_interpretation"]]
    replay = {**response, "directive_interpretation": [d.model_dump() for d in truth]}
    validate_schedule(request, truth, replay, tolerance=JUDGE_TOLERANCE)
    assert response["total_cost_bdt"] == pytest.approx(expected["total_cost_bdt"], abs=0.01, rel=0)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_public_sample_offline(case):
    calls = []
    with mock_client(case["input"], case["expected_output"]["directive_interpretation"], calls) as client:
        response = client.post("/optimize-energy", json=case["input"])
    assert response.status_code == 200, response.text
    assert len(calls) == 1
    assert calls[0]["response_format"]["type"] == "json_schema"
    assert_public_result(case, response.json())


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_public_reference_is_valid(case):
    request = OptimizeRequest.model_validate(case["input"])
    truth = [Directive.model_validate(d) for d in case["expected_output"]["directive_interpretation"]]
    validate_schedule(request, truth, case["expected_output"], tolerance=0.01)


@pytest.mark.live
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_public_sample_live(case):
    settings = Settings.from_env()
    assert settings.api_key, "Configure GROQ_API_KEY or GEMINI_API_KEY locally before --live"
    with TestClient(create_app(settings)) as client:
        response = client.post("/optimize-energy", json=case["input"])
    assert response.status_code == 200, response.text
    assert_public_result(case, response.json())
