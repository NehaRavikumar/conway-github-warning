import time
from collections import deque
from typing import Deque, Dict, List, Optional, Set

class RepoScheduler:
    def __init__(self, high_traffic: List[str], min_interval_seconds: int = 120):
        self.high_traffic = [r for r in high_traffic if "/" in r]
        self.queue: Deque[str] = deque()
        self.last_checked: Dict[str, float] = {}
        self.min_interval = min_interval_seconds

    def add_recent_repo(self, repo_full_name: Optional[str]) -> None:
        if not repo_full_name or "/" not in repo_full_name:
            return
        self.queue.append(repo_full_name)

    def next_batch(self, max_repos: int) -> List[str]:
        now = time.time()
        picked: List[str] = []
        seen: Set[str] = set()

        # 1) high-traffic first
        for r in self.high_traffic:
            if len(picked) >= max_repos:
                break
            if r in seen:
                continue
            if now - self.last_checked.get(r, 0) >= self.min_interval:
                picked.append(r); seen.add(r); self.last_checked[r] = now

        # 2) fill from recent queue
        while len(picked) < max_repos and self.queue:
            r = self.queue.popleft()
            if r in seen:
                continue
            if now - self.last_checked.get(r, 0) < self.min_interval:
                continue
            picked.append(r); seen.add(r); self.last_checked[r] = now

        return picked

