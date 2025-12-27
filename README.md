# Conway GitHub Warning System

This project was motivated by a recurring pattern in recent real-world incidents: serious GitHub failures rarely start with an obvious exploit or outage. Instead, they emerge from small, legitimate-looking changes to workflows, automation, or dependencies that quietly expand risk over time.
Two classes of incidents were particularly influential.
GitHub Actions as an Attack Surface
Recent investigations into AI-assisted workflow hijacking
(see: https://breached.company/when-github-became-the-battlefield-how-ai-powered-malware-and-workflow-hijacking-exposed-thousands-of-developer-secrets/) show that modern attacks increasingly target CI/CD automation itself, rather than application code.
Key observations:
Malicious workflows often appear normal at first glance.
Attackers enumerate and reuse existing secret names, personalizing attacks per repository.
Small workflow changes can dramatically increase blast radius without triggering traditional alarms.
This directly informed detectors that focus on workflow configuration drift, secret usage expansion, and personalized exfiltration patterns, even when no exploit has yet occurred.

Ecosystem Fragility & Supply Chain Incidents
Recent npm supply-chain disruptions
(see: https://dev.to/usman_awan/the-night-npm-caught-fire-inside-the-2025-javascript-supply-chain-meltdown-52o3) highlighted a different but related failure mode:
A single compromised maintainer or auth failure can ripple across thousands of repositories.
Many affected projects were “innocent bystanders” whose own code never changed.
Risk was visible before local failures, but most tooling reacted only after breakage.
This motivated treating ecosystem exposure as a first-class signal. Repositories are flagged not only when they fail locally, but when they depend on infrastructure that is currently unstable elsewhere. Vulnerability enrichment (via OSV.dev) is intentionally scoped to dependencies implicated by the triggering signal, framing vulnerabilities as exposure, not static defects


## Novelty
- Ecosystem Incident Correlator: aggregates cross-repo signals in a sliding window and emits a single ecosystem incident when thresholds are met (e.g., npm auth token expiry patterns).

