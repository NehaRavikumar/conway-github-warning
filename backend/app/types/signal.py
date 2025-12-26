from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol

@dataclass(frozen=True)
class RunContext:
    repo_full_name: str
    owner: str
    run_id: int
    html_url: str
    workflow_name: Optional[str]
    conclusion: Optional[str]
    updated_at: Optional[str]
    job_name: Optional[str] = None
    step_name: Optional[str] = None

@dataclass(frozen=True)
class SignalMatch:
    signature: str
    evidence: Dict[str, Any]
    confidence: float

class SignalPlugin(Protocol):
    name: str

    def match(self, run_context: RunContext, log_text: str) -> Optional[SignalMatch]:
        ...
