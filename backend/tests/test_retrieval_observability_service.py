from app.services.retrieval_observability_service import _p95


def test_retrieval_observability_p95_empty():
    assert _p95([]) is None


def test_retrieval_observability_p95_value():
    assert _p95([10, 20, 30, 40, 100]) == 40
