import { describe, expect, it } from "vitest";
import {
  compareIncidents,
  insertHighLeftmost,
  insertWithPriority,
  mergeQueued
} from "./incidentUtils.js";

const makeIncident = (id, severity, createdAt) => ({
  incident_id: id,
  created_at: createdAt,
  tags: [],
  evidence: { confidence: severity === "High" ? 0.9 : severity === "Medium" ? 0.5 : 0.1 }
});

it("orders incidents by severity then recency", () => {
  const a = makeIncident("a", "Low", "2024-01-01T00:00:00Z");
  const b = makeIncident("b", "High", "2024-01-01T00:00:00Z");
  const c = makeIncident("c", "Medium", "2024-01-02T00:00:00Z");

  const sorted = [a, b, c].sort(compareIncidents);
  expect(sorted[0].incident_id).toBe("b");
  expect(sorted[1].incident_id).toBe("c");
  expect(sorted[2].incident_id).toBe("a");
});

it("inserts high severity leftmost", () => {
  const base = [
    makeIncident("a", "Medium", "2024-01-01T00:00:00Z"),
    makeIncident("b", "Low", "2024-01-01T00:00:01Z")
  ];
  const incoming = makeIncident("c", "High", "2024-01-01T00:00:02Z");
  const inserted = insertHighLeftmost(insertWithPriority(base, incoming), incoming);
  expect(inserted[0].incident_id).toBe("c");
});

it("merges queued incidents into priority order", () => {
  const queue = [makeIncident("a", "Low", "2024-01-01T00:00:00Z")];
  const queued = [
    makeIncident("b", "High", "2024-01-01T00:00:02Z"),
    makeIncident("c", "Medium", "2024-01-01T00:00:01Z")
  ];
  const merged = mergeQueued(queue, queued);
  expect(merged.map((i) => i.incident_id)).toEqual(["b", "c", "a"]);
});
