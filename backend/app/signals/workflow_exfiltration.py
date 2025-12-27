import base64
import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

from ..config import settings

WORKFLOW_DIR = ".github/workflows/"
SUSPICIOUS_TRIGGERS = ("pull_request_target", "workflow_run", "workflow_call")
SUSPICIOUS_STEPS = ("security", "audit", "scanner")
SAFE_DOMAINS = {"github.com", "api.github.com", "objects.githubusercontent.com"}
IOC_DOMAINS = {
    "bold-dhawan.45-139-104-115.plesk.page",
    "493networking.cc",
}
IOC_WORKFLOW_NAME = "Github Actions Security"

SECRET_RE = re.compile(r"secrets\.([A-Z0-9_]+)")
SECRET_EXPR_RE = re.compile(r"\$\{\{\s*secrets\.([A-Z0-9_]+)\s*\}\}")
TOJSON_SECRETS_RE = re.compile(r"toJSON\(\s*secrets\s*\)", re.IGNORECASE)
URL_RE = re.compile(r"https?://[^\s)\"']+")
EXFIL_TOOL_RE = re.compile(r"\b(curl|wget|Invoke-WebRequest|nc)\b", re.IGNORECASE)
POST_FLAG_RE = re.compile(r"(\-X\s*POST|\-\-data|\-d\s)", re.IGNORECASE)
BASE64_RE = re.compile(r"\bbase64\b", re.IGNORECASE)
TRIGGER_RE = re.compile(r"\b(" + "|".join(SUSPICIOUS_TRIGGERS) + r")\b")
PERMISSIONS_WRITE_RE = re.compile(r"\b(contents|id-token|pull-requests)\s*:\s*write\b", re.IGNORECASE)
RUNNER_RE = re.compile(r"\bself-hosted\b", re.IGNORECASE)
USES_RE = re.compile(r"uses:\s*([^\s@]+)@([^\s]+)", re.IGNORECASE)

class FetchBudget:
    def __init__(self, remaining: int):
        self.remaining = remaining

    def take(self) -> bool:
        if self.remaining <= 0:
            return False
        self.remaining -= 1
        return True

def _is_workflow_path(path: str) -> bool:
    if not path:
        return False
    if not path.startswith(WORKFLOW_DIR):
        return False
    return path.endswith(".yml") or path.endswith(".yaml")

def _extract_domains(urls: Sequence[str]) -> List[str]:
    domains = []
    for u in urls:
        try:
            parsed = urlparse(u)
        except Exception:
            continue
        if not parsed.netloc:
            continue
        domains.append(parsed.netloc.lower())
    return domains

def _external_domains(urls: Sequence[str]) -> List[str]:
    domains = []
    for d in _extract_domains(urls):
        if d in SAFE_DOMAINS:
            continue
        if d.endswith(".github.com"):
            continue
        domains.append(d)
    return sorted(set(domains))

def _redact_secrets(line: str) -> str:
    line = SECRET_EXPR_RE.sub("${{ secrets.REDACTED }}", line)
    return SECRET_RE.sub("secrets.REDACTED", line)

def _extract_snippets(text: str, max_lines: int = 3) -> List[str]:
    lines = text.splitlines()
    matches: List[str] = []
    for line in lines:
        if SECRET_RE.search(line) or EXFIL_TOOL_RE.search(line) or URL_RE.search(line) or TRIGGER_RE.search(line) or PERMISSIONS_WRITE_RE.search(line):
            matches.append(_redact_secrets(line).strip())
        if len(matches) >= max_lines:
            break
    return matches

def _extract_evidence_lines(text: str, max_lines: int = 8) -> List[str]:
    lines = text.splitlines()
    matches: List[str] = []
    for line in lines:
        if (
            SECRET_RE.search(line)
            or EXFIL_TOOL_RE.search(line)
            or POST_FLAG_RE.search(line)
            or BASE64_RE.search(line)
            or URL_RE.search(line)
            or IOC_WORKFLOW_NAME in line
        ):
            matches.append(_redact_secrets(line).strip())
        if len(matches) >= max_lines:
            break
    return matches

def _hash_secret_name(name: str) -> str:
    return hashlib.sha1(name.encode("utf-8")).hexdigest()[:10]

def _stable_run_id(key: str) -> int:
    digest = hashlib.sha1(key.encode("utf-8")).digest()
    value = int.from_bytes(digest[:8], "big", signed=False)
    return -int(value % (2**63))

def _uses_unpinned_action(text: str) -> bool:
    for match in USES_RE.finditer(text):
        ref = match.group(2)
        if ref in ("main", "master", "v1"):
            return True
        if re.fullmatch(r"v\d+", ref):
            return True
        if not re.fullmatch(r"[0-9a-f]{40}", ref, re.IGNORECASE):
            return True
    return False

def analyze_workflow_text(text: str) -> Dict[str, Any]:
    secret_refs = SECRET_RE.findall(text)
    secret_ref_count = len(secret_refs)
    urls = URL_RE.findall(text)
    external_domains = _external_domains(urls)

    has_exfil_tool = bool(EXFIL_TOOL_RE.search(text))
    has_post = bool(POST_FLAG_RE.search(text))
    has_suspicious_trigger = bool(TRIGGER_RE.search(text))
    has_permissions_write = bool(PERMISSIONS_WRITE_RE.search(text))
    has_self_hosted = bool(RUNNER_RE.search(text))
    has_unpinned_action = _uses_unpinned_action(text)
    has_suspicious_step = any(s in text.lower() for s in SUSPICIOUS_STEPS)

    ioc_domains = [d for d in external_domains if d in IOC_DOMAINS or d.endswith(".plesk.page")]

    matched_indicators = []
    if secret_ref_count:
        matched_indicators.append("secrets_reference")
    if has_suspicious_trigger:
        matched_indicators.append("suspicious_trigger")
    if has_permissions_write:
        matched_indicators.append("permissions_write")
    if has_self_hosted:
        matched_indicators.append("self_hosted_runner")
    if has_unpinned_action:
        matched_indicators.append("unpinned_action_ref")
    if has_suspicious_step:
        matched_indicators.append("suspicious_step_name")
    if has_exfil_tool and external_domains:
        matched_indicators.append("exfil_tool_with_external_url")
    if has_post:
        matched_indicators.append("post_body_exfil")
    if ioc_domains:
        matched_indicators.append("known_ioc_domain")

    score = 0
    score += min(secret_ref_count, 5) * 8
    if has_suspicious_trigger:
        score += 12
    if has_permissions_write:
        score += 12
    if has_self_hosted:
        score += 10
    if has_unpinned_action:
        score += 10
    if has_suspicious_step:
        score += 6
    if has_exfil_tool and external_domains:
        score += 20
    if has_post:
        score += 10
    if ioc_domains:
        score += 25

    snippets = _extract_snippets(text, max_lines=3)

    return {
        "secret_ref_count": secret_ref_count,
        "external_domains": external_domains,
        "ioc_domains": ioc_domains,
        "matched_indicators": matched_indicators,
        "score": score,
        "snippets": snippets,
    }

async def _get_commit_files(gh, owner: str, repo: str, sha: str, budget: FetchBudget) -> Optional[List[Dict[str, Any]]]:
    if not budget.take():
        return None
    try:
        data = await gh.get_commit(owner, repo, sha)
    except Exception as e:
        print(f"[signals] commit fetch failed for {owner}/{repo}@{sha[:7]}: {type(e).__name__}")
        return None
    return data.get("files") or []

async def _get_workflow_text(gh, owner: str, repo: str, path: str, sha: str, budget: FetchBudget) -> Optional[str]:
    if not budget.take():
        return None
    try:
        data = await gh.get_contents(owner, repo, path, ref=sha)
    except Exception as e:
        print(f"[signals] content fetch failed for {owner}/{repo}:{path}@{sha[:7]}: {type(e).__name__}")
        return None
    content = data.get("content")
    encoding = data.get("encoding")
    if not content or encoding != "base64":
        return None
    try:
        return base64.b64decode(content).decode("utf-8", errors="replace")
    except Exception:
        return None

async def _list_workflow_files(gh, owner: str, repo: str, ref: str, budget: FetchBudget) -> List[str]:
    if not budget.take():
        return []
    try:
        data = await gh.get_contents(owner, repo, WORKFLOW_DIR.rstrip("/"), ref=ref)
    except Exception as e:
        print(f"[signals] workflows list failed for {owner}/{repo}@{ref}: {type(e).__name__}")
        return []
    files = []
    for item in data or []:
        if item.get("type") != "file":
            continue
        path = item.get("path") or ""
        if _is_workflow_path(path):
            files.append(path)
    return files

async def _collect_known_secrets(gh, owner: str, repo: str, ref: str, budget: FetchBudget) -> List[str]:
    secrets: List[str] = []
    files = await _list_workflow_files(gh, owner, repo, ref, budget)
    for path in files[:10]:
        text = await _get_workflow_text(gh, owner, repo, path, ref, budget)
        if not text:
            continue
        secrets.extend(SECRET_EXPR_RE.findall(text))
    return sorted(set(secrets))

async def _fetch_actor_context(gh, owner: str, repo: str, login: str, budget: FetchBudget) -> Optional[Dict[str, Any]]:
    if not login or not budget.take():
        return None
    try:
        user = await gh.get_user(login)
    except Exception as e:
        print(f"[signals] actor fetch failed for {login}: {type(e).__name__}")
        return None

    ctx = {
        "login": login,
        "type": user.get("type"),
        "created_at": user.get("created_at"),
        "followers": user.get("followers"),
        "public_repos": user.get("public_repos"),
        "site_admin": user.get("site_admin"),
    }

    if budget.take():
        try:
            perm = await gh.get_collaborator_permission(owner, repo, login)
            if perm:
                ctx["permission"] = perm
        except Exception:
            pass

    return ctx

async def detect_ghostaction_risk(event: Dict[str, Any], gh, budget: FetchBudget) -> List[Dict[str, Any]]:
    if event.get("type") != "PushEvent":
        return []

    repo = event.get("repo") or {}
    repo_full_name = repo.get("name")
    if not repo_full_name or "/" not in repo_full_name:
        return []
    owner, name = repo_full_name.split("/", 1)

    payload = event.get("payload") or {}
    commits = payload.get("commits") or []
    head_sha = payload.get("head")
    actor = (event.get("actor") or {}).get("login")
    created_at = event.get("created_at")

    workflow_paths: List[Tuple[str, str]] = []
    for c in commits:
        sha = c.get("sha") or head_sha
        if not sha:
            continue
        for key in ("added", "modified", "removed"):
            for path in c.get(key) or []:
                if _is_workflow_path(path):
                    workflow_paths.append((sha, path))

    if not workflow_paths and head_sha:
        files = await _get_commit_files(gh, owner, name, head_sha, budget)
        if files:
            for f in files:
                path = f.get("filename")
                if _is_workflow_path(path or ""):
                    workflow_paths.append((head_sha, path))

    if not workflow_paths:
        return []

    all_indicators: List[str] = []
    all_domains: List[str] = []
    all_snippets: List[str] = []
    secret_ref_count = 0
    max_score = 0

    for sha, path in workflow_paths:
        text = await _get_workflow_text(gh, owner, name, path, sha, budget)
        if not text:
            continue
        analysis = analyze_workflow_text(text)
        secret_ref_count += analysis["secret_ref_count"]
        all_domains.extend(analysis["external_domains"])
        all_indicators.extend(analysis["matched_indicators"])
        all_snippets.extend(analysis["snippets"])
        max_score = max(max_score, analysis["score"])

    if not all_indicators:
        return []

    score = max_score
    should_emit = secret_ref_count > 0 or score >= settings.GHOSTACTION_SCORE_THRESHOLD
    if not should_emit:
        return []

    dedupe_key = f"ghostaction:{repo_full_name}:{head_sha}"
    run_id = _stable_run_id(dedupe_key)
    severity = "critical" if score >= 80 else "high"
    tags = [
        "security",
        "ghostaction",
        f"risk:{severity}",
        f"signals:{','.join(sorted(set(all_indicators)))}",
        f"actor:{'bot' if (actor or '').lower().endswith('[bot]') else 'user'}",
        f"score:{score}",
    ]

    actor_context = None
    if actor:
        actor_context = await _fetch_actor_context(gh, owner, name, actor, budget)

    evidence = {
        "repo_full_name": repo_full_name,
        "sha": head_sha,
        "actor": actor,
        "workflow_paths": sorted(set(p for _sha, p in workflow_paths)),
        "secret_ref_count": secret_ref_count,
        "external_domains": sorted(set(all_domains)),
        "matched_indicators": sorted(set(all_indicators)),
        "snippets": all_snippets[:3],
        "actor_context": actor_context,
        "detected_at": created_at,
        "source": "global_events",
    }

    incident = {
        "incident_id": hashlib.sha1(dedupe_key.encode("utf-8")).hexdigest(),
        "kind": "ghostaction_risk",
        "run_id": run_id,
        "dedupe_key": dedupe_key,
        "repo_full_name": repo_full_name,
        "workflow_name": "workflow_change",
        "run_number": None,
        "status": "detected",
        "conclusion": severity,
        "html_url": f"https://github.com/{repo_full_name}/commit/{head_sha}",
        "created_at": created_at,
        "updated_at": created_at,
        "title": f"GhostAction-style workflow risk detected in {repo_full_name}",
        "tags_json": json.dumps(tags),
        "evidence_json": json.dumps(evidence),
        "_tags": tags,
        "_evidence": evidence,
    }

    return [incident]

async def detect_personalized_exfiltration(event: Dict[str, Any], gh, budget: FetchBudget) -> List[Dict[str, Any]]:
    if event.get("type") != "PushEvent":
        return []

    repo = event.get("repo") or {}
    repo_full_name = repo.get("name")
    if not repo_full_name or "/" not in repo_full_name:
        return []
    owner, name = repo_full_name.split("/", 1)

    payload = event.get("payload") or {}
    commits = payload.get("commits") or []
    base_sha = payload.get("before")
    head_sha = payload.get("after")
    actor = (event.get("actor") or {}).get("login")
    created_at = event.get("created_at")

    workflow_paths: List[str] = []
    for c in commits:
        for key in ("added", "modified", "removed"):
            for path in c.get(key) or []:
                if _is_workflow_path(path):
                    workflow_paths.append(path)

    if not workflow_paths and head_sha:
        files = await _get_commit_files(gh, owner, name, head_sha, budget)
        if files:
            for f in files:
                path = f.get("filename")
                if _is_workflow_path(path or ""):
                    workflow_paths.append(path)

    if not workflow_paths or not head_sha or not base_sha:
        return []

    known_secrets = await _collect_known_secrets(gh, owner, name, base_sha, budget)

    incidents: List[Dict[str, Any]] = []
    for path in sorted(set(workflow_paths)):
        text = await _get_workflow_text(gh, owner, name, path, head_sha, budget)
        if not text:
            continue

        new_secrets = sorted(set(SECRET_EXPR_RE.findall(text)))
        overlap = sorted(set(new_secrets) & set(known_secrets))

        has_curl = bool(EXFIL_TOOL_RE.search(text))
        has_post = bool(POST_FLAG_RE.search(text))
        has_base64 = bool(BASE64_RE.search(text))
        urls = URL_RE.findall(text)
        external_domains = _external_domains(urls)
        has_secret_ref = bool(SECRET_RE.search(text) or TOJSON_SECRETS_RE.search(text))
        exfil_ok = has_curl and has_post and urls and has_secret_ref
        if not exfil_ok:
            continue

        ioc_domains = [d for d in external_domains if d in IOC_DOMAINS or d.endswith(".plesk.page")]
        has_ioc_name = IOC_WORKFLOW_NAME in text
        confidence = "low"
        if overlap:
            confidence = "medium"
        if has_base64 or TOJSON_SECRETS_RE.search(text):
            confidence = "medium" if confidence == "low" else confidence
        if ioc_domains or has_ioc_name:
            confidence = "high"

        evidence_lines = _extract_evidence_lines(text, max_lines=8)
        overlap_hashes = [_hash_secret_name(n) for n in overlap]
        evidence = {
            "repo_full_name": repo_full_name,
            "sha": head_sha,
            "actor": actor,
            "workflow_path": path,
            "overlap_secrets": overlap_hashes,
            "overlap_count": len(overlap),
            "exfil_domain": ioc_domains[0] if ioc_domains else (external_domains[0] if external_domains else None),
            "confidence": confidence,
            "evidence_lines": evidence_lines,
            "source": "global_events",
        }

        dedupe_key = f"personalized_exfil:{repo_full_name}:{head_sha}:{path}"
        run_id = _stable_run_id(dedupe_key)
        tags = [
            "security",
            "workflow_injection",
            "secret_enumeration",
            f"confidence:{confidence}",
            f"overlap:{len(overlap)}",
        ]

        incident = {
            "incident_id": hashlib.sha1(dedupe_key.encode("utf-8")).hexdigest(),
            "kind": "personalized_secret_exfiltration",
            "run_id": run_id,
            "dedupe_key": dedupe_key,
            "repo_full_name": repo_full_name,
            "workflow_name": path,
            "run_number": None,
            "status": "detected",
            "conclusion": confidence,
            "html_url": f"https://github.com/{repo_full_name}/commit/{head_sha}",
            "created_at": created_at,
            "updated_at": created_at,
            "title": f"Personalized secret exfiltration risk in {repo_full_name}",
            "tags_json": json.dumps(tags),
            "evidence_json": json.dumps(evidence),
            "_tags": tags,
            "_evidence": evidence,
        }
        incidents.append(incident)

    return incidents
