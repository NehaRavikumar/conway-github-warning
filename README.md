# Conway GitHub Warning System

## Novelty


- **Workflow-first threat model inspired by real attacks**  
  Detection logic is explicitly shaped by real-world workflow hijacking incidents, focusing on configuration drift, secret reuse, and personalized exfiltration patterns *before* an exploit or outage occurs.

- **Signals as risk expansion, not isolated events**  
  Instead of treating GitHub events as standalone alerts, the system defines signals as moments where operational power (automation, secrets, dependencies) expands faster than guardrails.

- **Ecosystem exposure as a first-class signal**  
  Repositories are flagged not only when they fail locally, but when they depend on external ecosystems (e.g. npm) that are currently unstable elsewhere, surfacing second-order risk early.

- **Contextual vulnerability enrichment, not blanket scanning**  
  Known vulnerabilities (via OSV.dev) are queried only for dependencies implicated by the triggering signal, framing vulnerabilities as contextual exposure rather than static defects.

- **Attention-bounded live presentation for triage, not dashboards**  
  The frontend models human attention as scarce: only five incidents occupy the live surface at once, high-severity signals interrupt lower-priority ones, and investigation pauses the stream.

---

## Inspiration & Motivation

This project was motivated by a recurring pattern in recent real-world incidents: **serious GitHub failures rarely begin with an obvious exploit or outage**. Instead, they emerge from small, legitimate-looking changes to workflows, automation, or dependencies that quietly expand risk over time—often going unnoticed until the blast radius is already large.

Rather than treating these incidents as isolated failures, the system is designed around the idea that **risk accumulates gradually through operational power**, and that early warning comes from detecting *how that power changes*.

Two classes of incidents directly shaped both the detectors and the presentation of signals in this system.

---

### GitHub Actions as an Attack Surface → GhostWatcher-style workflow signals

Investigations into AI-assisted workflow hijacking  
(see: https://breached.company/when-github-became-the-battlefield-how-ai-powered-malware-and-workflow-hijacking-exposed-thousands-of-developer-secrets/) revealed a critical shift in how modern attacks operate: **CI/CD automation itself has become the primary attack surface**, rather than application code.

Key observations from this analysis:

- Malicious workflows often appear normal at first glance  
- Attackers enumerate and reuse existing secret names, tailoring attacks per repository  
- Small workflow changes can dramatically increase blast radius without triggering traditional alarms  

This directly inspired the system’s **GhostWatcher-style detection format**, which treats workflow changes as *risk signals*, not just configuration updates.

Detectors explicitly look for:
- workflow configuration drift  
- expansion in secret usage  
- personalized exfiltration patterns  

Crucially, these signals are surfaced **even when no exploit or outage has yet occurred**, reflecting the insight that workflow abuse is often detectable *before* damage is visible.

---

### Ecosystem Fragility & Supply Chain Incidents  → Ecosystem exposure signals

A second major influence came from recent npm supply-chain disruptions  
(see: https://dev.to/usman_awan/the-night-npm-caught-fire-inside-the-2025-javascript-supply-chain-meltdown-52o3), which highlighted a different but related failure mode:

- A single compromised maintainer or authentication failure can ripple across thousands of repositories  
- Many affected projects were “innocent bystanders” whose own code never changed  
- Risk was visible at the ecosystem level before local failures, but most tooling reacted only after breakage  

This directly motivated treating **ecosystem exposure as a first-class signal**. In this system, repositories are flagged not only when they fail locally, but when they depend on infrastructure that is currently unstable elsewhere.

To keep this actionable rather than noisy, vulnerability enrichment (via OSV.dev) is intentionally scoped to **dependencies implicated by the triggering signal**, framing vulnerabilities as contextual exposure rather than static defects.

---

## Improvements & Next Steps

- Org-wide patterns: currently only tracking issues for each repo and looking at ecosystem wide issue, a next step would be to cluster and look at signals for repos on an org-wide basis.
- As the system runs for longer, summary graphs could be used to track  risk accumulation fover time or certain repos
- Add a human feedback loop for the summaries and risk assesment
- Add timelines for multi-process issues (ex. workflow modified → secret referenced → outbound POST → detection)
