from app.agent.runtime.langgraph_compat import native_checkpoint_support_status


def test_native_checkpoint_support_status_detects_incompatible_langgraph(monkeypatch):
    versions = {
        "langgraph": "0.2.34",
        "langgraph-checkpoint-postgres": "2.0.25",
        "langgraph-checkpoint": "2.1.2",
    }

    monkeypatch.setattr(
        "app.agent.runtime.langgraph_compat._safe_version",
        lambda package_name: versions.get(package_name),
    )

    status = native_checkpoint_support_status()

    assert status["enabled"] is True
    assert status["available"] is False
    assert status["compatible"] is False
    assert status["reason"] == "langgraph_checkpoint_postgres_requires_langgraph_gte_0_5"


def test_native_checkpoint_support_status_accepts_compatible_langgraph(monkeypatch):
    versions = {
        "langgraph": "0.5.1",
        "langgraph-checkpoint-postgres": "2.0.25",
        "langgraph-checkpoint": "2.1.2",
    }

    monkeypatch.setattr(
        "app.agent.runtime.langgraph_compat._safe_version",
        lambda package_name: versions.get(package_name),
    )

    status = native_checkpoint_support_status()

    assert status["enabled"] is True
    assert status["available"] is True
    assert status["compatible"] is True
    assert status["reason"] == "ok"
