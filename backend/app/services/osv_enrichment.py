import asyncio
import json
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

import httpx

from ..config import settings
from ..db import connect
from ..github import GitHubClient
from ..incidents import set_enrichment

OSV_ENDPOINT = "https://api.osv.dev/v1/query"
OSV_TTL_SECONDS = 24 * 60 * 60

class EnrichmentQueue:
    def __init__(self, maxsize: int = 500):
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=maxsize)

    async def enqueue(self, incident_id: str) -> None:
        try:
            self._queue.put_nowait(incident_id)
        except asyncio.QueueFull:
            pass

    async def dequeue(self) -> str:
        return await self._queue.get()

class OsvCache:
    def __init__(self):
        self._cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        item = self._cache.get(key)
        if not item:
            return None
        ts, value = item
        if time.time() - ts > OSV_TTL_SECONDS:
            self._cache.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Dict[str, Any]) -> None:
        self._cache[key] = (time.time(), value)

def _extract_candidates(texts: Iterable[str]) -> List[Tuple[str, str]]:
    import re
    candidates = []
    pattern = re.compile(r"(@?[\w.-]+(?:/[\w.-]+)?)@([0-9]+\.[0-9]+\.[0-9]+[\w.-]*)")
    for text in texts:
        for match in pattern.finditer(text):
            name = match.group(1)
            version = match.group(2)
            candidates.append((name, version))
    return candidates

def _is_exact_version(version: str) -> bool:
    if any(ch in version for ch in ["^", "~", ">", "<", "*", "x"]):
        return False
    return True

def _extract_packages_from_incident(incident: Dict[str, Any]) -> List[Tuple[str, str]]:
    evidence = incident.get("evidence") or incident.get("_evidence") or {}
    summary = incident.get("summary") or {}
    texts: List[str] = []

    for key in ("evidence_lines", "snippets"):
        lines = evidence.get(key) or []
        texts.extend([str(line) for line in lines])

    samples = evidence.get("evidence_samples") or []
    texts.extend([str(s.get("matched_line")) for s in samples if s.get("matched_line")])

    for section in ("root_cause", "impact", "next_steps"):
        items = summary.get(section) or []
        texts.extend([str(item) for item in items])

    structured = []
    if evidence.get("package"):
        structured.append((evidence.get("package"), evidence.get("package_version")))
    if evidence.get("affected_packages"):
        for pkg in evidence.get("affected_packages"):
            if isinstance(pkg, dict):
                structured.append((pkg.get("name"), pkg.get("version")))

    candidates = _extract_candidates(texts)
    for name, version in structured:
        if name and version:
            candidates.append((name, version))

    exact = []
    for name, version in candidates:
        if name and version and _is_exact_version(version):
            exact.append((name, version))
    return list(dict.fromkeys(exact))

def _normalize_osv_response(name: str, version: str, data: Dict[str, Any]) -> List[Dict[str, Any]]:
    vulns = data.get("vulns") or []
    top_vulns = []
    for v in vulns[:5]:
        affected = v.get("affected") or []
        ranges = []
        for aff in affected:
            pkg = aff.get("package", {}).get("name")
            if pkg != name:
                continue
            for r in aff.get("ranges") or []:
                ranges.append(r.get("events") or [])
        references = [ref.get("url") for ref in v.get("references") or [] if ref.get("url")]
        severity = "UNKNOWN"
        if v.get("severity"):
            sev = v.get("severity")[0]
            severity = sev.get("score") or sev.get("type") or "UNKNOWN"
        top_vulns.append({
            "package": name,
            "version": version,
            "osv_id": v.get("id"),
            "summary": v.get("summary"),
            "severity": severity,
            "affected_ranges": ranges[:3],
            "references": references[:3],
        })
    return top_vulns

def _is_osv_relevant(incident: Dict[str, Any]) -> bool:
    kind = incident.get("kind") or ""
    tags = incident.get("tags") or incident.get("_tags") or []
    evidence = incident.get("evidence") or incident.get("_evidence") or {}
    signature = (evidence.get("signature") or "").lower()
    tag_blob = " ".join(tags).lower()
    if kind == "ecosystem_incident" and "npm" in (signature + tag_blob):
        return True
    if "npm" in tag_blob or "dependency" in tag_blob or "supply" in tag_blob:
        return True
    return False

async def _fetch_incident(db_path: str, incident_id: str) -> Optional[Dict[str, Any]]:
    async with connect(db_path) as db:
        cur = await db.execute(
            """
            SELECT
              incident_id, kind, repo_full_name, workflow_name, run_id,
              status, conclusion, html_url, created_at, updated_at, title,
              tags_json, evidence_json, summary_json, enrichment_json
            FROM incidents
            WHERE incident_id = ?
            """,
            (incident_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None

    (
        incident_id, kind, repo_full_name, workflow_name, run_id,
        status, conclusion, html_url, created_at, updated_at, title,
        tags_json, evidence_json, summary_json, enrichment_json
    ) = row

    return {
        "incident_id": incident_id,
        "kind": kind,
        "repo_full_name": repo_full_name,
        "workflow_name": workflow_name,
        "run_id": run_id,
        "status": status,
        "conclusion": conclusion,
        "html_url": html_url,
        "created_at": created_at,
        "updated_at": updated_at,
        "title": title,
        "tags": json.loads(tags_json),
        "evidence": json.loads(evidence_json),
        "summary": json.loads(summary_json) if summary_json else {},
        "enrichment": json.loads(enrichment_json) if enrichment_json else None,
    }

async def _fetch_package_json(gh: GitHubClient, owner: str, repo: str, sha: str) -> Dict[str, Any]:
    data = await gh.get_contents(owner, repo, "package.json", ref=sha)
    content = data.get("content")
    if not content or data.get("encoding") != "base64":
        return {}
    import base64
    raw = base64.b64decode(content)
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}

def _deps_from_package_json(payload: Dict[str, Any]) -> List[Tuple[str, str]]:
    deps = payload.get("dependencies") or {}
    dev = payload.get("devDependencies") or {}
    combined = {**deps, **dev}
    items = sorted(combined.items(), key=lambda x: x[0])[:10]
    return [(name, version) for name, version in items if _is_exact_version(version)]

async def maybe_enqueue_enrichment(incident: Dict[str, Any], queue: EnrichmentQueue, db_path: str) -> None:
    if not _is_osv_relevant(incident):
        enrichment = {"osv": {"status": "not_applicable"}}
        await set_enrichment(db_path, incident["incident_id"], enrichment)
        return
    await queue.enqueue(incident["incident_id"])

async def osv_worker_loop(db_path: str, queue: EnrichmentQueue, broadcaster) -> None:
    cache = OsvCache()
    sem = asyncio.Semaphore(5)
    gh = GitHubClient(settings.GITHUB_TOKEN)

    while True:
        incident_id = await queue.dequeue()
        incident = await _fetch_incident(db_path, incident_id)
        if not incident:
            continue

        if not _is_osv_relevant(incident):
            enrichment = {"osv": {"status": "not_applicable"}}
            await set_enrichment(db_path, incident_id, enrichment)
            continue

        packages = _extract_packages_from_incident(incident)
        status = "ok"

        if not packages:
            evidence = incident.get("evidence") or {}
            sha = evidence.get("sha")
            repo_full_name = evidence.get("repo_full_name") or incident.get("repo_full_name")
            if incident.get("kind") == "ecosystem_incident" and repo_full_name and sha and "/" in repo_full_name:
                owner, repo = repo_full_name.split("/", 1)
                try:
                    pkg_json = await _fetch_package_json(gh, owner, repo, sha)
                    packages = _deps_from_package_json(pkg_json)
                except Exception:
                    packages = []
            else:
                status = "skipped_no_package_context"

        packages_queried: List[str] = []
        top_vulns: List[Dict[str, Any]] = []

        async def query_one(name: str, version: str) -> None:
            key = f"osv:npm:{name}@{version}"
            cached = cache.get(key)
            if cached is not None:
                top_vulns.extend(cached.get("top_vulns", []))
                packages_queried.append(f"{name}@{version}")
                return

            payload = {"package": {"name": name, "ecosystem": "npm"}, "version": version}
            async with sem:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(OSV_ENDPOINT, json=payload)
                    if resp.status_code != 200:
                        return
                    data = resp.json()
            norm = _normalize_osv_response(name, version, data)
            cache.set(key, {"top_vulns": norm})
            top_vulns.extend(norm)
            packages_queried.append(f"{name}@{version}")

        for name, version in packages[:10]:
            try:
                await query_one(name, version)
            except Exception:
                continue

        enrichment = {
            "osv": {
                "status": status,
                "queried_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "packages_queried": packages_queried,
                "vuln_count_total": len(top_vulns),
                "top_vulns": top_vulns[:5],
            }
        }

        await set_enrichment(db_path, incident_id, enrichment)
        await broadcaster.publish({
            "_event": "incident_enriched",
            "incident_id": incident_id,
            "enrichment": enrichment,
        })
