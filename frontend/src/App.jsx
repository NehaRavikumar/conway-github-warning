import { useEffect, useMemo, useState } from "react";
import {
  parseTime,
  getSeverity,
  compareIncidents,
  insertWithPriority,
  insertHighLeftmost,
  buildWhyFired,
  mergeQueued
} from "./incidentUtils.js";

const TIME_WINDOWS = [
  { label: "All", value: "all" },
  { label: "5m", value: 5 },
  { label: "15m", value: 15 },
  { label: "1h", value: 60 },
  { label: "6h", value: 360 },
  { label: "24h", value: 1440 }
];

const SEVERITIES = ["High", "Medium", "Low"];

const TYPE_LABELS = {
  ghostaction_risk: "GhostWatcher",
  ecosystem_incident: "npm Ecosystem",
  workflow_failure: "Workflow Failure",
  personalized_secret_exfiltration: "Personalized Exfiltration"
};

const relativeTime = (date) => {
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
};

const getIssueType = (incident) => {
  if (TYPE_LABELS[incident.kind]) return TYPE_LABELS[incident.kind];
  if (incident.kind === "ecosystem_incident" && incident.evidence?.signature) {
    return incident.evidence.signature.replace(/_/g, " ");
  }
  return incident.kind ? incident.kind.replace(/_/g, " ") : "Incident";
};

const summaryLine = (incident) => {
  const summary = incident.summary;
  if (summary?.root_cause?.length) return summary.root_cause[0];
  if (summary?.impact?.length) return summary.impact[0];
  if (summary?.next_steps?.length) return summary.next_steps[0];
  return incident.title || "New incident detected";
};

const extractSnippets = (incident) => {
  const evidence = incident.evidence || {};
  if (Array.isArray(evidence.evidence_lines) && evidence.evidence_lines.length) {
    return evidence.evidence_lines;
  }
  if (Array.isArray(evidence.snippets) && evidence.snippets.length) {
    return evidence.snippets;
  }
  if (Array.isArray(evidence.evidence_samples) && evidence.evidence_samples.length) {
    return evidence.evidence_samples.map((s) => s.matched_line).filter(Boolean);
  }
  return [];
};

const tagPillClass = (severity) => {
  if (severity === "High") return "bg-rose-100 text-rose-700 border-rose-200";
  if (severity === "Medium") return "bg-amber-100 text-amber-700 border-amber-200";
  return "bg-emerald-100 text-emerald-700 border-emerald-200";
};

const TAG_COLORS = [
  "bg-purple-100 text-purple-700 border-purple-200",
  "bg-sky-100 text-sky-700 border-sky-200",
  "bg-pink-100 text-pink-700 border-pink-200",
  "bg-orange-100 text-orange-700 border-orange-200"
];

const tagColor = (tag) => {
  const idx = Math.abs(tag.split("").reduce((acc, ch) => acc + ch.charCodeAt(0), 0)) % TAG_COLORS.length;
  return TAG_COLORS[idx];
};

export default function App() {
  const [incidentQueue, setIncidentQueue] = useState([]);
  const [queuedIncidents, setQueuedIncidents] = useState([]);
  const [paused, setPaused] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [focusedIncident, setFocusedIncident] = useState(null);
  const [expandedCards, setExpandedCards] = useState({});
  const [interruptId, setInterruptId] = useState(null);
  const [viewMode, setViewMode] = useState("live");
  const [timeWindow, setTimeWindow] = useState("all");
  const [severityFilter, setSeverityFilter] = useState(new Set());
  const [typeFilter, setTypeFilter] = useState(new Set());
  const [repoQuery, setRepoQuery] = useState("");

  const pendingCount = queuedIncidents.length;
  const pauseTicker = paused || hovered || focusedIncident;

  const upsertIncident = (incident) => {
    setIncidentQueue((prev) => insertWithPriority(prev, incident));
  };

  useEffect(() => {
    const es = new EventSource("/stream");
    es.addEventListener("incident", (event) => {
      const incoming = JSON.parse(event.data);
      if (pauseTicker) {
        setQueuedIncidents((prev) => [...prev, incoming]);
        return;
      }
      const severity = getSeverity(incoming);
      setIncidentQueue((prev) => {
        const next = insertWithPriority(prev, incoming);
        if (severity === "High") {
          setInterruptId(incoming.incident_id);
          setTimeout(() => setInterruptId(null), 300);
          return insertHighLeftmost(next, incoming);
        }
        return next;
      });
    });
    es.addEventListener("incident_enriched", (event) => {
      const payload = JSON.parse(event.data);
      setIncidentQueue((prev) =>
        prev.map((item) =>
          item.incident_id === payload.incident_id
            ? { ...item, enrichment: payload.enrichment }
            : item
        )
      );
    });
    es.onerror = () => {
      es.close();
    };
    return () => es.close();
  }, [pauseTicker]);

  useEffect(() => {
    const fetchInitial = async () => {
      const since = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
      try {
        const resp = await fetch(`/summary?since=${encodeURIComponent(since)}`);
        const data = await resp.json();
        if (data.cards) {
          setIncidentQueue(data.cards.sort(compareIncidents));
        }
      } catch (err) {
        // keep quiet
      }
    };
    fetchInitial();
  }, []);

  useEffect(() => {
    if (!pauseTicker && queuedIncidents.length) {
      setIncidentQueue((prev) => {
        return mergeQueued(prev, queuedIncidents);
      });
      setQueuedIncidents([]);
    }
  }, [pauseTicker, queuedIncidents]);

  const types = useMemo(() => {
    const set = new Set(incidentQueue.map(getIssueType));
    return Array.from(set).sort();
  }, [incidentQueue]);

  const filtered = useMemo(() => {
    const now = Date.now();
    const windowMs = timeWindow === "all" ? null : timeWindow * 60 * 1000;

    return incidentQueue.filter((incident) => {
      const date = parseTime(incident);
      if (windowMs && now - date.getTime() > windowMs) return false;

      const severity = getSeverity(incident);
      if (severityFilter.size && !severityFilter.has(severity)) return false;

      const type = getIssueType(incident);
      if (typeFilter.size && !typeFilter.has(type)) return false;

      if (repoQuery) {
        const repoName = (incident.repo_full_name || incident.evidence?.repo_full_name || "").toLowerCase();
        if (!repoName.includes(repoQuery.toLowerCase())) return false;
      }

      return true;
    });
  }, [incidentQueue, timeWindow, severityFilter, typeFilter, repoQuery]);

  const sorted = useMemo(() => {
    return [...filtered].sort(compareIncidents);
  }, [filtered]);

  const topFive = sorted.slice(0, 5);
  const tickerItems = topFive.length > 0 ? [...topFive, ...topFive] : [];

  const clearFilters = () => {
    setTimeWindow("all");
    setSeverityFilter(new Set());
    setTypeFilter(new Set());
    setRepoQuery("");
  };

  const toggleSeverity = (sev) => {
    setSeverityFilter((prev) => {
      const next = new Set(prev);
      if (next.has(sev)) next.delete(sev);
      else next.add(sev);
      return next;
    });
  };

  const toggleType = (type) => {
    setTypeFilter((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  };

  const handleInspect = (incident) => {
    if (!incident) return;
    setFocusedIncident(incident);
    setPaused(true);
  };

  const toggleCardExpand = (id) => {
    setExpandedCards((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const handleUnpause = () => {
    setPaused(false);
    setFocusedIncident(null);
  };

  return (
    <div className="min-h-screen px-4 py-8 lg:px-10">
      <div className="mx-auto max-w-7xl space-y-6">
        <header className="flex flex-col gap-4 rounded-2xl bg-white/80 p-6 shadow-soft">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <p className="text-sm uppercase tracking-[0.2em] text-slate-500">
                Live Incident Ticker · Attention Window (5)
              </p>
              <h1 className="mt-2 font-display text-3xl text-slate-900">
                GhostWatcher Live Belt
              </h1>
            </div>
            <div className="flex items-center gap-3">
              <button
                className={`rounded-full px-4 py-2 text-sm font-semibold transition ${
                  viewMode === "live" ? "bg-slate-900 text-white" : "bg-white text-slate-600"
                }`}
                onClick={() => setViewMode("live")}
              >
                Live Belt
              </button>
              <button
                className={`rounded-full px-4 py-2 text-sm font-semibold transition ${
                  viewMode === "all" ? "bg-slate-900 text-white" : "bg-white text-slate-600"
                }`}
                onClick={() => setViewMode("all")}
              >
                All Incidents
              </button>
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-4">
            <div className="space-y-2">
              <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Time window</label>
              <div className="flex flex-wrap gap-2">
                {TIME_WINDOWS.map((window) => (
                  <button
                    key={window.label}
                    className={`rounded-full border px-3 py-1 text-xs font-semibold transition ${
                      timeWindow === window.value ? "border-slate-900 bg-slate-900 text-white" : "border-slate-200 text-slate-600"
                    }`}
                    onClick={() => setTimeWindow(window.value)}
                  >
                    {window.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="space-y-2">
              <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Severity</label>
              <div className="flex flex-wrap gap-2">
                {SEVERITIES.map((sev) => (
                  <button
                    key={sev}
                    className={`rounded-full border px-3 py-1 text-xs font-semibold transition ${
                      severityFilter.has(sev) ? "border-slate-900 bg-slate-900 text-white" : "border-slate-200 text-slate-600"
                    }`}
                    onClick={() => toggleSeverity(sev)}
                  >
                    {sev}
                  </button>
                ))}
              </div>
            </div>
            <div className="space-y-2">
              <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Issue type</label>
              <div className="flex flex-wrap gap-2">
                {types.map((type) => (
                  <button
                    key={type}
                    className={`rounded-full border px-3 py-1 text-xs font-semibold transition ${
                      typeFilter.has(type) ? "border-slate-900 bg-slate-900 text-white" : "border-slate-200 text-slate-600"
                    }`}
                    onClick={() => toggleType(type)}
                  >
                    {type}
                  </button>
                ))}
              </div>
            </div>
            <div className="space-y-2">
              <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Repo search</label>
              <input
                className="w-full rounded-xl border-slate-200 bg-white px-3 py-2 text-sm"
                placeholder="owner/repo"
                value={repoQuery}
                onChange={(event) => setRepoQuery(event.target.value)}
              />
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2">
            <button
              className="text-xs font-semibold uppercase tracking-wide text-slate-500"
              onClick={clearFilters}
            >
              Clear filters
            </button>
            {pendingCount > 0 && pauseTicker && (
              <div className="rounded-full bg-slate-900 px-3 py-1 text-xs font-semibold text-white">
                Queued: +{pendingCount}
              </div>
            )}
          </div>
        </header>

        {viewMode === "live" ? (
          <section className="space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="font-display text-xl text-slate-800">Live Belt</h2>
              {(pauseTicker || focusedIncident) && (
                <button
                  className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-slate-600 shadow-soft"
                  onClick={handleUnpause}
                >
                  Resume
                </button>
              )}
            </div>
            <div
              className="relative overflow-hidden rounded-3xl border border-white/70 bg-white/80 p-6 shadow-soft"
              onMouseEnter={() => setHovered(true)}
              onMouseLeave={() => setHovered(false)}
            >
              <div className={`flex gap-4 ${pauseTicker ? "" : ""}`}>
                {tickerItems.length === 0 ? (
                  <div className="text-sm text-slate-500">No incidents yet.</div>
                ) : (
                  <div
                    className={`ticker-track flex gap-4 ${pauseTicker ? "paused" : ""} animate-ticker`}
                  >
                    {tickerItems.map((incident, index) => (
                        <IncidentCard
                          key={`${incident.incident_id}-${index}`}
                          incident={incident}
                          onFlip={() => handleInspect(incident)}
                          isExpanded={!!expandedCards[incident.incident_id]}
                          onToggleExpand={() => toggleCardExpand(incident.incident_id)}
                          interrupt={interruptId === incident.incident_id}
                        />
                    ))}
                  </div>
                )}
              </div>
            </div>
          </section>
        ) : (
          <section className="space-y-4">
            <h2 className="font-display text-xl text-slate-800">All Incidents</h2>
            <div className="grid gap-4">
              {sorted.map((incident) => (
                <IncidentRow
                  key={incident.incident_id}
                  incident={incident}
                  onSelect={() => handleInspect(incident)}
                />
              ))}
            </div>
          </section>
        )}
      </div>
      {focusedIncident && (
        <IncidentOverlay incident={focusedIncident} onClose={handleUnpause} />
      )}
    </div>
  );
}

function IncidentRow({ incident, onSelect }) {
  const time = parseTime(incident);
  const severity = getSeverity(incident);
  const summary = summaryLine(incident);
  return (
    <div
      className="cursor-pointer rounded-2xl border border-slate-200 bg-white p-4 shadow-soft transition hover:-translate-y-0.5"
      onClick={onSelect}
      role="button"
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect();
        }
      }}
    >
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-semibold text-slate-800">{incident.repo_full_name}</h3>
          <p className="text-xs text-slate-500" title={time.toISOString()}>{relativeTime(time)}</p>
        </div>
        <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${tagPillClass(severity)}`}>
          {severity}
        </span>
      </div>
      <p className="mt-3 text-sm text-slate-600">{summary}</p>
    </div>
  );
}

function IncidentCard({ incident, onFlip, isExpanded, onToggleExpand, interrupt }) {
  const time = parseTime(incident);
  const severity = getSeverity(incident);
  const type = getIssueType(incident);
  const signatureTag = incident.evidence?.signature
    ? incident.evidence.signature.replace(/_/g, " ")
    : null;
  const tags = [];
  if (incident.kind === "ecosystem_incident") {
    tags.push("npm Ecosystem");
  }
  if (signatureTag && tags.length < 3) tags.push(signatureTag);
  const extraTag = (incident.tags || []).find((tag) => !tags.includes(tag));
  if (extraTag && tags.length < 3) tags.push(extraTag);

  const summary = incident.summary || {};
  const rootCause = Array.isArray(summary.root_cause) ? summary.root_cause : [];
  const impact = Array.isArray(summary.impact) ? summary.impact : [];
  const nextSteps = Array.isArray(summary.next_steps) ? summary.next_steps : [];
  const whyFired = buildWhyFired(incident);
  const trajectory = summary.risk_trajectory;
  const trajectoryReason = summary.risk_trajectory_reason;

  const renderBullets = (items) => {
    const visible = isExpanded ? items : items.slice(0, 2);
    const hiddenCount = Math.max(items.length - visible.length, 0);
    return (
      <>
        <ul className="space-y-1 text-xs leading-snug text-slate-600">
          {visible.map((item, idx) => (
            <li key={`${item}-${idx}`} className="flex gap-2">
              <span className="mt-1 h-1.5 w-1.5 rounded-full bg-slate-400/70" />
              <span>{item}</span>
            </li>
          ))}
        </ul>
        {!isExpanded && hiddenCount > 0 && (
          <button
            className="mt-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400"
            onClick={(event) => {
              event.stopPropagation();
              onToggleExpand();
            }}
          >
            +{hiddenCount} more
          </button>
        )}
      </>
    );
  };

  return (
    <div className="card-flip w-72 shrink-0">
      <div
        role="button"
        tabIndex={0}
        className={`card-face flex w-full cursor-pointer flex-col rounded-2xl bg-white p-4 text-left shadow-soft transition-transform hover:-translate-y-1 ${isExpanded ? "h-[30rem]" : "h-[26rem]"} ${interrupt ? "interrupt" : ""}`}
        onClick={onFlip}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onFlip();
          }
        }}
      >
        <div className="relative pr-20">
          <div className="space-y-1">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 truncate">
              {incident.repo_full_name}
            </p>
            <p className="text-xs text-slate-400" title={time.toISOString()}>{relativeTime(time)}</p>
            <p className="text-[11px] text-slate-500">
              <span className="font-semibold text-slate-400">Why this fired:</span> {whyFired}
            </p>
            <div className="pt-1">
              <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-semibold text-slate-600">
                {type}
              </span>
              {trajectory && (
                <span
                  className="ml-2 rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-semibold text-slate-600"
                  title={trajectoryReason || ""}
                >
                  {trajectory === "increasing" ? "Trajectory ↑" : trajectory === "recovering" ? "Trajectory ↓" : "Trajectory →"}
                </span>
              )}
            </div>
          </div>
          <span className={`absolute right-0 top-0 rounded-full border px-3 py-1 text-xs font-semibold ${tagPillClass(severity)}`}>
            {severity}
          </span>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {tags.slice(0, 3).map((tag) => (
            <span key={tag} className={`rounded-full border px-2 py-1 text-xs font-semibold ${tagColor(tag)}`}>
              {tag}
            </span>
          ))}
        </div>
        <div className={`mt-4 flex-1 space-y-3 ${isExpanded ? "overflow-y-auto pr-1" : "overflow-hidden"}`}>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-400">Root cause</p>
            {rootCause.length ? renderBullets(rootCause) : <p className="text-xs text-slate-400">Pending analysis.</p>}
          </div>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-400">Impact</p>
            {impact.length ? renderBullets(impact) : <p className="text-xs text-slate-400">Pending analysis.</p>}
          </div>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-400">Next steps</p>
            {nextSteps.length ? renderBullets(nextSteps) : <p className="text-xs text-slate-400">Pending analysis.</p>}
          </div>
        </div>
        <button
          className="mt-2 self-start text-[10px] font-semibold uppercase tracking-wide text-slate-400"
          onClick={(event) => {
            event.stopPropagation();
            onToggleExpand();
          }}
        >
          {isExpanded ? "Collapse" : "Expand"}
        </button>
      </div>
    </div>
  );
}

function IncidentOverlay({ incident, onClose }) {
  const snippets = extractSnippets(incident);
  const rawJson = JSON.stringify(incident, null, 2);
  const summary = incident.summary || {};
  const rootCause = Array.isArray(summary.root_cause) ? summary.root_cause : [];
  const impact = Array.isArray(summary.impact) ? summary.impact : [];
  const nextSteps = Array.isArray(summary.next_steps) ? summary.next_steps : [];

  const handleCopy = async () => {
    await navigator.clipboard.writeText(rawJson);
  };

  return (
    <div className="overlay">
      <button className="overlay-backdrop" onClick={onClose} aria-label="Close overlay" />
      <div className="overlay-card">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{incident.repo_full_name}</p>
            <h3 className="mt-2 font-display text-2xl text-slate-900">{incident.title || "Incident detail"}</h3>
          </div>
          <button
            className="rounded-full border border-slate-200 px-3 py-1 text-xs font-semibold text-slate-600"
            onClick={onClose}
          >
            Close
          </button>
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          <div className="space-y-3 lg:col-span-2">
            <div>
              <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Triage Summary</h4>
              <div className="mt-2 grid gap-3 sm:grid-cols-3">
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-400">Root cause</p>
                  {rootCause.length ? (
                    <ul className="mt-2 space-y-1 text-xs leading-snug text-slate-600">
                      {rootCause.map((item, idx) => (
                        <li key={`${item}-${idx}`} className="flex gap-2">
                          <span className="mt-1 h-1.5 w-1.5 rounded-full bg-slate-400/70" />
                          <span>{item}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-2 text-xs text-slate-400">Pending analysis.</p>
                  )}
                </div>
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-400">Impact</p>
                  {impact.length ? (
                    <ul className="mt-2 space-y-1 text-xs leading-snug text-slate-600">
                      {impact.map((item, idx) => (
                        <li key={`${item}-${idx}`} className="flex gap-2">
                          <span className="mt-1 h-1.5 w-1.5 rounded-full bg-slate-400/70" />
                          <span>{item}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-2 text-xs text-slate-400">Pending analysis.</p>
                  )}
                </div>
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-400">Next steps</p>
                  {nextSteps.length ? (
                    <ul className="mt-2 space-y-1 text-xs leading-snug text-slate-600">
                      {nextSteps.map((item, idx) => (
                        <li key={`${item}-${idx}`} className="flex gap-2">
                          <span className="mt-1 h-1.5 w-1.5 rounded-full bg-slate-400/70" />
                          <span>{item}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-2 text-xs text-slate-400">Pending analysis.</p>
                  )}
                </div>
              </div>
            </div>
            <div>
              <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Evidence</h4>
              <div className="mt-2 space-y-2">
                {snippets.length ? (
                  snippets.map((line, index) => (
                    <pre key={index} className="whitespace-pre-wrap rounded-lg bg-slate-900/90 p-2 text-xs font-mono text-slate-100">
                      {line}
                    </pre>
                  ))
                ) : (
                  <p className="text-xs text-slate-500">No log snippets available.</p>
                )}
              </div>
            </div>
          </div>
          <div>
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Raw JSON</h4>
              <button
                className="text-xs font-semibold uppercase tracking-wide text-slate-500"
                onClick={handleCopy}
              >
                Copy JSON
              </button>
            </div>
            <pre className="mt-2 max-h-[26rem] overflow-auto rounded-lg bg-slate-100 p-3 text-xs text-slate-600">
              {rawJson}
            </pre>
          </div>
        </div>
      </div>
    </div>
  );
}
