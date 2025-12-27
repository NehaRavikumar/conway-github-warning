from typing import Any, Dict, List

def derive_scope(kind: str) -> str:
    if kind in ("ecosystem_incident",):
        return "ecosystem"
    if kind in ("ghostaction_risk", "personalized_secret_exfiltration", "workflow_failure"):
        return "repo"
    return "repo"

def derive_surface(kind: str, tags: list[str]) -> str:
    tag_blob = " ".join(tags).lower()
    if kind in ("ghostaction_risk", "personalized_secret_exfiltration"):
        return "credentials"
    if kind == "ecosystem_incident" or "npm" in tag_blob or "dependency" in tag_blob:
        return "dependencies"
    if kind == "workflow_failure":
        return "ops"
    return "automation"

def derive_actor(evidence: Dict[str, Any]) -> Dict[str, Any]:
    login = evidence.get("actor") or evidence.get("actor_login")
    ctx = evidence.get("actor_context") or {}
    actor_type = ctx.get("type")
    if actor_type:
        actor_type = actor_type.lower()
    is_bot = False
    if isinstance(login, str) and login.lower().endswith("[bot]"):
        is_bot = True
    if actor_type == "bot":
        is_bot = True
    if actor_type not in ("user", "bot", "org"):
        actor_type = "unknown"
    return {
        "login": login or "unknown",
        "type": actor_type,
        "is_bot": is_bot,
    }

def apply_incident_fields(inc: Dict[str, Any]) -> Dict[str, Any]:
    tags: List[str] = inc.get("tags") or []
    if not tags and isinstance(inc.get("tags_json"), str):
        try:
            import json
            tags = json.loads(inc["tags_json"])
        except Exception:
            tags = []
    evidence = inc.get("evidence") or inc.get("_evidence") or {}
    if not evidence and isinstance(inc.get("evidence_json"), str):
        try:
            import json
            evidence = json.loads(inc["evidence_json"])
        except Exception:
            evidence = {}

    inc["scope"] = inc.get("scope") or derive_scope(inc.get("kind", ""))
    inc["surface"] = inc.get("surface") or derive_surface(inc.get("kind", ""), tags)
    inc["actor"] = inc.get("actor") or derive_actor(evidence)
    return inc
