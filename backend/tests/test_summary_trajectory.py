from app.summary_queue import _validate_trajectory

def test_validate_trajectory_accepts_valid():
    payload = {"risk_trajectory": "increasing", "risk_trajectory_reason": "Errors are accelerating."}
    out = _validate_trajectory(payload)
    assert out["risk_trajectory"] == "increasing"
    assert out["risk_trajectory_reason"] == "Errors are accelerating."

def test_validate_trajectory_fallback():
    payload = {"risk_trajectory": "unknown", "risk_trajectory_reason": None}
    out = _validate_trajectory(payload)
    assert out["risk_trajectory"] == "stable"
    assert "defaulting" in out["risk_trajectory_reason"].lower()
