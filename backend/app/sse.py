import asyncio
from typing import Any, AsyncIterator, Dict, List

class IncidentBroadcaster:
    def __init__(self):
        self._subscribers: List[asyncio.Queue] = []

    async def publish(self, incident: Dict[str, Any]) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(incident)
            except asyncio.QueueFull:
                pass

    async def subscribe(self) -> AsyncIterator[Dict[str, Any]]:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.append(q)
        try:
            while True:
                item = await q.get()
                yield item
        finally:
            if q in self._subscribers:
                self._subscribers.remove(q)

