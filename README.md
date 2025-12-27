# Conway GitHub Warning System

This backend polls the GitHub Global Events API, stores raw payloads + summaries, and emits live incidents over SSE.

## Novelty
- Ecosystem Incident Correlator: aggregates cross-repo signals in a sliding window and emits a single ecosystem incident when thresholds are met (e.g., npm auth token expiry patterns).

