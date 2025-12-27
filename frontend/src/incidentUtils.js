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
  return parseTime(a).getTime() - parseTime(b).getTime();
};

export const insertWithPriority = (queue, incident) => {
  if (incident.kind === "ecosystem_incident") {
    const signature = incident.evidence?.signature || "";
    const source = incident.evidence?.source || "";
    const title = incident.title || "";
    const dupe = queue.find(
      (item) =>
        item.kind === "ecosystem_incident" &&
        (item.evidence?.signature || "") === signature &&
        (item.evidence?.source || "") === source &&
        (item.title || "") === title
    );
    if (dupe) {
      return queue;
    }
  }
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

export const dedupeEcosystem = (queue) => {
  const seen = new Set();
  const next = [];
  for (const item of queue) {
    if (item.kind === "ecosystem_incident") {
      const signature = item.evidence?.signature || "";
      const source = item.evidence?.source || "";
      const title = item.title || "";
      const key = `${signature}|${source}|${title}`;
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
    }
    next.push(item);
  }
  return next;
};

export const mergeQueued = (queue, queued) => {
  let next = [...queue];
  for (const inc of queued) {
    next = insertWithPriority(next, inc);
  }
  return dedupeEcosystem(next);
};

export const buildWhyFired = (incident) => {
  if (incident.why_this_fired) return incident.why_this_fired;
  const summary = incident.summary || {};
  if (summary.why_this_fired) return summary.why_this_fired;
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

export const getScope = (incident) => {
  if (incident.scope) return incident.scope;
  const kind = incident.kind || "";
  if (kind === "ecosystem_incident") return "ecosystem";
  if (kind === "ghostaction_risk" || kind === "personalized_secret_exfiltration") return "repo";
  if (kind === "workflow_failure") return "repo";
  return "repo";
};

export const getSurface = (incident) => {
  if (incident.surface) return incident.surface;
  const kind = incident.kind || "";
  const tagBlob = (incident.tags || []).join(" ").toLowerCase();
  if (kind === "ghostaction_risk" || kind === "personalized_secret_exfiltration") return "credentials";
  if (kind === "ecosystem_incident" || tagBlob.includes("npm") || tagBlob.includes("dependency")) return "dependencies";
  if (kind === "workflow_failure") return "ops";
  return "automation";
};
