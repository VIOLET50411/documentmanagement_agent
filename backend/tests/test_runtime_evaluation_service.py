from app.services.runtime_evaluation_service import _p95, _safe_div


def test_safe_div_handles_zero_denominator():
    assert _safe_div(10, 0) == 0.0


def test_safe_div_rounds_ratio():
    assert _safe_div(1, 3) == 0.3333


def test_p95_returns_none_for_empty_values():
    assert _p95([]) is None


def test_p95_returns_expected_value():
    values = [1, 2, 3, 4, 5, 6, 7, 8, 100, 120]
    assert _p95(values) == 100
