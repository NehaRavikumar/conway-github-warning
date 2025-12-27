from app.incident_fields import derive_actor, derive_scope, derive_surface

def test_derive_scope_surface():
    assert derive_scope("ecosystem_incident") == "ecosystem"
    assert derive_scope("ghostaction_risk") == "repo"
    assert derive_surface("personalized_secret_exfiltration", []) == "credentials"
    assert derive_surface("ecosystem_incident", ["npm"]) == "dependencies"
    assert derive_surface("workflow_failure", []) == "ops"

def test_derive_actor():
    actor = derive_actor({"actor": "octo[bot]", "actor_context": {"type": "Bot"}})
    assert actor["is_bot"] is True
    assert actor["type"] == "bot"
