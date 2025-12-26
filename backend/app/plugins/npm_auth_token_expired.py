import re
from typing import Optional

from ..types.signal import RunContext, SignalMatch

_EXPIRED_RE = re.compile(r"access token expired or revoked", re.IGNORECASE)
_UNABLE_AUTH_RE = re.compile(r"npm ERR!\s+Unable to authenticate", re.IGNORECASE)
_E401_CODE_RE = re.compile(r"npm ERR!\s+code\s+E401", re.IGNORECASE)
_E401_UNAUTHORIZED_RE = re.compile(r"E401\s+Unauthorized", re.IGNORECASE)
_TS_RE = re.compile(
    r"^\s*(\[[^\]]+\]|\d{4}-\d{2}-\d{2}T[^\s]+|\d{4}-\d{2}-\d{2}\s+[0-9:.]+)\s*"
)

def _normalize_line(line: str) -> str:
    line = _TS_RE.sub("", line)
    line = re.sub(r"\s+", " ", line).strip()
    if len(line) > 200:
        line = line[:197] + "..."
    return line

class NpmAuthTokenExpiredPlugin:
    name = "npm_auth_token_expired"

    def match(self, run_context: RunContext, log_text: str) -> Optional[SignalMatch]:
        matched_line = None
        confidence = None

        for raw_line in log_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if _EXPIRED_RE.search(line) or _UNABLE_AUTH_RE.search(line):
                matched_line = _normalize_line(line)
                confidence = 0.9
                break
            if _E401_CODE_RE.search(line) or _E401_UNAUTHORIZED_RE.search(line):
                matched_line = _normalize_line(line)
                confidence = 0.7
                break

        if not matched_line:
            return None

        evidence = {
            "matched_line": matched_line,
            "job_name": run_context.job_name,
            "step_name": run_context.step_name,
            "run_id": run_context.run_id,
        }
        return SignalMatch(
            signature="npm_auth_token_expired",
            evidence=evidence,
            confidence=confidence,
        )
