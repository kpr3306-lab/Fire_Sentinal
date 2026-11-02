import React, { useEffect, useState } from "react";
import { Flame, ShieldCheck, Camera, Siren, AlertTriangle, ChevronDown, ChevronRight } from "lucide-react";
import { getDevices, getEvents, getSnapshots, snapshotFileUrl, getAppliances } from "../api/client";
import { parseDbTime } from "./Analytics";

const EVENT_LIMIT = 1000;
const STATE_RANK = { NORMAL: 0, PRECURSOR: 1, CONFIRMING: 2, FIRE_CONFIRMED: 3 };
const STATE_COLOR = { NORMAL: "#10B981", PRECURSOR: "#F59E0B", CONFIRMING: "#F97316", FIRE_CONFIRMED: "#EF4444" };
const HAZARD_COLOR = { NONE: "#10B981", CONTROLLED: "#F59E0B", HAZARDOUS: "#EF4444", UNKNOWN: "#8B96A8" };

/**
 * An incident runs from the first STATE_CHANGE away from NORMAL until the next
 * STATE_CHANGE back to NORMAL. Events outside an incident (e.g. on-demand
 * snapshots while NORMAL) are not part of any incident. Returns newest first.
 */
export function groupIncidents(events) {
  const sorted = [...events].sort((a, b) => parseDbTime(a.created_at) - parseDbTime(b.created_at) || a.id - b.id);
  const incidents = [];
  let open = null;
  for (const e of sorted) {
    const isChange = e.event_type === "STATE_CHANGE";
    if (!open) {
      if (isChange && e.to_state !== "NORMAL") {
        open = { id: e.id, start: e.created_at, end: null, events: [e], peakState: e.to_state, peakRisk: e.risk_score ?? 0, roomId: e.room_id };
      }
      continue;
    }
    open.events.push(e);
    if ((STATE_RANK[e.to_state] ?? 0) > (STATE_RANK[open.peakState] ?? 0)) open.peakState = e.to_state;
    if ((e.risk_score ?? 0) > open.peakRisk) open.peakRisk = e.risk_score;
    if (isChange && e.to_state === "NORMAL") {
      open.end = e.created_at;
      incidents.push(open);
      open = null;
    }
  }
  if (open) incidents.push(open);   // still ongoing
  return incidents.reverse();
}

const fmtTime = (s) => parseDbTime(s).toLocaleString();
function fmtDuration(start, end) {
  const sec = Math.round(((end ? parseDbTime(end) : new Date()) - parseDbTime(start)) / 1000);
  return sec < 60 ? `${sec} s` : sec < 3600 ? `${Math.floor(sec / 60)} min ${sec % 60} s` : `${(sec / 3600).toFixed(1)} h`;
}
function parseList(json) {
  try { const v = JSON.parse(json || "[]"); return Array.isArray(v) ? v : []; } catch { return []; }
}

function StateBadge({ state }) {
  return (
    <span className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium border"
      style={{ color: STATE_COLOR[state] || "#8B96A8", borderColor: `${STATE_COLOR[state] || "#8B96A8"}66` }}>
      {state === "FIRE_CONFIRMED" ? <Flame size={12} /> : <AlertTriangle size={12} />}
      {state?.replace("_", " ")}
    </span>
  );
}

function eventIcon(e) {
  if (e.event_type === "SNAPSHOT_CAPTURED") return Camera;
  if (e.event_type === "ALERT_SENT") return Siren;
  if (e.to_state === "NORMAL") return ShieldCheck;
  return e.to_state === "FIRE_CONFIRMED" ? Flame : AlertTriangle;
}

function IncidentDetail({ incident, snapshotsById }) {
  const [appliances, setAppliances] = useState([]);
  useEffect(() => {
    if (!incident.roomId) return;
    getAppliances(incident.roomId).then(setAppliances).catch(() => setAppliances([]));
  }, [incident.roomId]);

  const snaps = incident.events.filter((e) => e.snapshot_id).map((e) => snapshotsById[e.snapshot_id]).filter(Boolean);

  return (
    <div className="border-t border-border p-4 grid gap-6 lg:grid-cols-2">
      <div>
        <p className="text-sm font-medium mb-2">Timeline</p>
        <ol className="space-y-2">
          {incident.events.map((e) => {
            const Icon = eventIcon(e);
            return (
              <li key={e.id} className="flex gap-3 text-sm">
                <Icon size={16} className="mt-0.5 shrink-0" style={{ color: STATE_COLOR[e.to_state] || "#3B82F6" }} />
                <div>
                  <p>{e.message}</p>
                  <p className="text-textMuted text-xs">{fmtTime(e.created_at)}</p>
                </div>
              </li>
            );
          })}
        </ol>
      </div>

      <div className="space-y-4">
        <div>
          <p className="text-sm font-medium mb-2">Camera evidence ({snaps.length})</p>
          {snaps.length === 0 && <p className="text-textMuted text-sm">No snapshots were captured during this incident.</p>}
          <div className="space-y-3">
            {snaps.map((s) => {
              const reasons = parseList(s.hazard_reasons);
              return (
                <div key={s.id} className="flex gap-3">
                  <a href={snapshotFileUrl(s.id)} target="_blank" rel="noreferrer" className="shrink-0">
                    <img src={snapshotFileUrl(s.id)} alt={`Snapshot ${s.reason}`} className="w-28 h-28 object-cover rounded-lg border border-border" />
                  </a>
                  <div className="text-sm space-y-1">
                    <p>
                      Hazard: <span style={{ color: HAZARD_COLOR[s.hazard_level] || "#8B96A8" }}>{s.hazard_level || "—"}</span>
                      <span className="text-textMuted"> · {s.reason}</span>
                    </p>
                    <p className="text-textMuted text-xs">
                      CNN: {s.classification}{s.confidence != null && ` (${(s.confidence * 100).toFixed(0)}%)`}
                      {s.detector_status === "ok" && ` · YOLO: ${s.flame_count} flame(s), ${(s.flame_area_ratio * 100).toFixed(1)}% of frame`}
                      {s.flame_growth != null && ` · growth ×${s.flame_growth.toFixed(2)}`}
                    </p>
                    {reasons.length > 0 && (
                      <ul className="text-textMuted text-xs list-disc ml-4">{reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div>
          <p className="text-sm font-medium mb-1">Possible contributing factors</p>
          <p className="text-textMuted text-xs mb-2">Appliances declared for this room. A hint for investigation, not a diagnosis.</p>
          {!incident.roomId && <p className="text-textMuted text-sm">Device was not assigned to a room.</p>}
          {incident.roomId && appliances.length === 0 && <p className="text-textMuted text-sm">No appliances declared for this room.</p>}
          <ul className="text-sm space-y-1">
            {appliances.map((a) => (
              <li key={a.id}>{a.name} <span className="text-textMuted text-xs">({a.category}{a.notes ? ` · ${a.notes}` : ""})</span></li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

export default function Incidents() {
  const [devices, setDevices] = useState([]);
  const [deviceId, setDeviceId] = useState("");
  const [incidents, setIncidents] = useState([]);
  const [snapshotsById, setSnapshotsById] = useState({});
  const [expanded, setExpanded] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    getDevices().then((d) => {
      setDevices(d);
      if (d.length > 0) setDeviceId(d[0].device_id);
    }).catch(() => setDevices([]));
  }, []);

  useEffect(() => {
    if (!deviceId) return;
    let cancelled = false;
    setLoading(true);
    Promise.all([getEvents({ device_id: deviceId }, EVENT_LIMIT), getSnapshots({ device_id: deviceId }, EVENT_LIMIT)])
      .then(([events, snaps]) => {
        if (cancelled) return;
        const inc = groupIncidents(events);
        setIncidents(inc);
        setSnapshotsById(Object.fromEntries(snaps.map((s) => [s.id, s])));
        setExpanded(inc[0]?.id ?? null);
        setError(null);
      })
      .catch(() => !cancelled && setError("Could not load incidents."))
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, [deviceId]);

  return (
    <div className="p-6 space-y-6 max-w-[1400px] mx-auto">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Incidents</h1>
          <p className="text-textMuted text-sm">Each incident runs from the first departure from NORMAL until the device returns to NORMAL</p>
        </div>
        <select
          value={deviceId}
          onChange={(e) => setDeviceId(e.target.value)}
          className="rounded-lg bg-surface border border-border px-3 py-2 text-sm"
          aria-label="Device"
        >
          {devices.map((d) => (
            <option key={d.device_id} value={d.device_id}>{d.device_name || d.device_id}</option>
          ))}
          {devices.length === 0 && <option value="">No devices yet</option>}
        </select>
      </div>

      {error && <div className="rounded-lg border border-warn/40 bg-warn/10 text-warn text-sm px-4 py-2">{error}</div>}
      {loading && <p className="text-sm text-textMuted">Loading incidents...</p>}
      {!loading && !error && incidents.length === 0 && (
        <div className="rounded-xl border border-border bg-surface p-8 text-center text-textMuted text-sm">
          No incidents recorded — this device has stayed NORMAL.
        </div>
      )}

      <div className="space-y-3">
        {incidents.map((inc) => {
          const isOpen = expanded === inc.id;
          const snapCount = inc.events.filter((e) => e.snapshot_id).length;
          const dispatched = inc.events.some((e) => e.event_type === "ALERT_SENT");
          return (
            <div key={inc.id} className="rounded-xl border border-border bg-surface overflow-hidden">
              <button
                onClick={() => setExpanded(isOpen ? null : inc.id)}
                aria-expanded={isOpen}
                className="w-full flex flex-wrap items-center gap-x-4 gap-y-2 p-4 text-left hover:bg-surfaceRaised"
              >
                {isOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                <StateBadge state={inc.peakState} />
                <span className="text-sm">{fmtTime(inc.start)}</span>
                <span className="text-sm text-textMuted">
                  {inc.end ? fmtDuration(inc.start, inc.end) : <span className="text-danger">ongoing · {fmtDuration(inc.start, null)}</span>}
                </span>
                <span className="text-sm text-textMuted ml-auto">
                  peak risk <span className="font-mono text-textPrimary">{inc.peakRisk}</span>
                  {" · "}{snapCount} snapshot{snapCount === 1 ? "" : "s"}
                  {dispatched && " · dispatch (simulated)"}
                </span>
              </button>
              {isOpen && <IncidentDetail incident={inc} snapshotsById={snapshotsById} />}
            </div>
          );
        })}
      </div>
      {incidents.length > 0 && (
        <p className="text-textMuted text-xs">Built from the latest {EVENT_LIMIT} events for this device; older incidents are not shown.</p>
      )}
    </div>
  );
}
