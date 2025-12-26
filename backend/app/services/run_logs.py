import time
from collections import OrderedDict, deque
from typing import Any, Dict, List, Optional

class RunLogFetcher:
    def __init__(self, gh, per_minute: int = 20, cache_size: int = 200):
        self._gh = gh
        self._per_minute = per_minute
        self._timestamps = deque()
        self._cache: "OrderedDict[int, List[Dict[str, Any]]]" = OrderedDict()
        self._cache_size = cache_size

    def _allow(self) -> bool:
        now = time.time()
        while self._timestamps and now - self._timestamps[0] > 60:
            self._timestamps.popleft()
        if len(self._timestamps) >= self._per_minute:
            return False
        self._timestamps.append(now)
        return True

    def _cache_put(self, run_id: int, logs: List[Dict[str, Any]]) -> None:
        self._cache[run_id] = logs
        self._cache.move_to_end(run_id)
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)

    async def fetch_run_logs(self, owner: str, repo: str, run_id: int) -> Optional[List[Dict[str, Any]]]:
        if run_id in self._cache:
            return self._cache[run_id]
        if not self._allow():
            return None

        try:
            jobs_data = await self._gh.list_jobs_for_workflow_run(owner, repo, run_id)
        except Exception:
            return None

        jobs = jobs_data.get("jobs") or []
        results: List[Dict[str, Any]] = []

        for job in jobs:
            job_id = job.get("id")
            job_name = job.get("name")
            if not job_id:
                continue
            if not self._allow():
                break
            try:
                log_text = await self._gh.get_job_logs(owner, repo, int(job_id))
            except Exception:
                continue
            if log_text:
                results.append({"job_name": job_name, "log_text": log_text})

        self._cache_put(run_id, results)
        return results
