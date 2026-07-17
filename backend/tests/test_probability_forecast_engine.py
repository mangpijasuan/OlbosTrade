import math

from app.services.probability_forecast_engine import ForecastBar, generate_forecast


def _bars(count=90, drift=0.0015):
    price = 100.0
    out = []
    for idx in range(count):
        price *= 1 + drift + math.sin(idx / 5) * 0.001
        out.append(ForecastBar(close=price, high=price * 1.01, low=price * 0.99, volume=1_000_000 + idx * 1000))
    return out


def test_probabilities_sum_to_100_and_never_execute():
    result = generate_forecast("qqq", 5, _bars())
    assert sum(result["probabilities"].values()) == 100
    assert result["execution_eligible"] is False
    assert result["evidence_tier"] == "SHADOW_BASELINE"
    assert len(result["scenarios"]) == 3


def test_insufficient_history_abstains():
    result = generate_forecast("SPY", 5, _bars(20))
    assert result["status"] == "ABSTAIN"
    assert result["confidence"] == "ABSTAIN"
    assert result["probabilities"] == {"bull": 0, "base": 0, "bear": 0}


def test_invalid_horizon_is_rejected():
    try:
        generate_forecast("SPY", 7, _bars())
    except ValueError as exc:
        assert "horizon" in str(exc)
    else:
        raise AssertionError("expected ValueError")
