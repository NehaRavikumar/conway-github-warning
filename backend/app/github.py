import asyncio
import random
import httpx
from typing import Any, Dict, Optional, Tuple

GITHUB_API = "https://api.github.com"

class GitHubClient:
    def __init__(self, token: str):
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        self._client = httpx.AsyncClient(
            base_url=GITHUB_API,
            headers=headers,
            timeout=httpx.Timeout(15.0),
        )

    async def close(self):
        await self._client.aclose()

    async def get_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Tuple[Any, httpx.Headers]:
        delay = 1.0
        for _ in range(8):
            resp = await self._client.get(url, params=params)

            if resp.status_code == 200:
                return resp.json(), resp.headers

            # backoff on rate limit / transient errors
            if resp.status_code in (403, 429) or 500 <= resp.status_code < 600:
                ra = resp.headers.get("Retry-After")
                if ra:
                    sleep_s = float(ra)
                else:
                    sleep_s = delay + random.uniform(0, delay * 0.25)
                await asyncio.sleep(sleep_s)
                delay *= 2
                continue

            resp.raise_for_status()

        resp.raise_for_status()

    async def list_global_events(self):
        data, _headers = await self.get_json("/events")
        return data
    async def list_workflow_runs(self, owner: str, repo: str, per_page: int = 5):
        data, _headers = await self.get_json(
            f"/repos/{owner}/{repo}/actions/runs",
            params={"per_page": per_page},
        )
        return data


