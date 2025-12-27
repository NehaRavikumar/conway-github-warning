export const severityRank = (sev) => {
  if (sev === "High") return 0;
  if (sev === "Medium") return 1;
  return 2;
};

export const parseTime = (incident) => {
  const raw = incident.created_at || incident.inserted_at || incident.updated_at;
  return raw ? new Date(raw) : new Date();
};

export const getSeverity = (incident) => {
  const tags = incident.tags || [];
  const evidence = incident.evidence || {};
  const confidence = evidence.confidence;
  if (typeof confidence === "number") {
    if (confidence >= 0.8) return "High";
    if (confidence >= 0.3) return "Medium";
    return "Low";
  }
  if (typeof confidence === "string") {
    const lc = confidence.toLowerCase();
    if (lc.includes("high") || lc.includes("critical")) return "High";
    if (lc.includes("medium")) return "Medium";
  }

  const hints = [
    incident.conclusion,
    incident.status,
    ...tags
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();

  if (hints.includes("critical") || hints.includes("high")) return "High";
  if (hints.includes("medium")) return "Medium";
  return "Low";
};

export const compareIncidents = (a, b) => {
  const sevA = severityRank(getSeverity(a));
  const sevB = severityRank(getSeverity(b));
  if (sevA !== sevB) return sevA - sevB;
  return parseTime(b).getTime() - parseTime(a).getTime();
};

export const insertWithPriority = (queue, incident) => {
  const existing = queue.findIndex((item) => item.incident_id === incident.incident_id);
  if (existing !== -1) {
    const next = [...queue];
    next[existing] = { ...queue[existing], ...incident };
    return next.sort(compareIncidents);
  }
  return [...queue, incident].sort(compareIncidents);
};

export const insertHighLeftmost = (queue, incident) => {
  const rest = queue.filter((item) => item.incident_id !== incident.incident_id);
  return [incident, ...rest];
};

export const mergeQueued = (queue, queued) => {
  let next = [...queue];
  for (const inc of queued) {
    next = insertWithPriority(next, inc);
  }
  return next;
};

export const buildWhyFired = (incident) => {
  const kind = incident.kind || "";
  const evidence = incident.evidence || {};
  if (kind === "personalized_secret_exfiltration") {
    return "workflow change reused existing secret names + outbound POST to external domain";
  }
  if (kind === "ecosystem_incident") {
    return "repeated npm auth errors across multiple repositories in a short window";
  }
  if (kind === "ghostaction_risk") {
    const domains = (evidence.external_domains || []).length;
    return domains
      ? "suspicious workflow change + external endpoints referenced"
      : "workflow change matches GhostAction-style risk signals";
  }
  if (kind === "workflow_failure") {
    return "check-run failures detected in recent workflow runs";
  }
  return "incident matched detection rules in the current time window";
};
