import React, { useEffect, useState } from "react";
import { Activity, Flame, AlertTriangle, ShieldCheck, Camera, ChevronDown, ChevronRight } from "lucide-react";
import { getEvents } from "../api/client";

const EVENT_META = {
  STATE_CHANGE: { icon: AlertTriangle, color: "#F59E0B" },
  SNAPSHOT_CAPTURED: { icon: Camera, color: "#3B82F6" },
};

const STATE_COLOR = {
  NORMAL: "#10B981",
  PRECURSOR: "#F59E0B",
  CONFIRMING: "#F97316",
  FIRE_CONFIRMED: "#EF4444",
};

function iconFor(event) {
  if (event.event_type === "STATE_CHANGE" && event.to_state === "NORMAL") return ShieldCheck;
  if (event.event_type === "STATE_CHANGE" && event.to_state === "FIRE_CONFIRMED") return Flame;
  return EVENT_META[event.event_type]?.icon || Activity;
}

export default function DetectionTimeline({ roomId, limit = 10 }) {
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const params = roomId ? { room_id: roomId } : {};
    getEvents(params, limit)
      .then((data) => !cancelled && setEvents(data))
      .catch(() => !cancelled && setEvents([]))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [roomId, limit]);

  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <button
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="w-full flex items-center gap-2 text-left"
      >
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        <Activity size={18} className="text-textMuted" />
        <span className="font-medium">Detection Timeline</span>
        {!loading && <span className="text-xs text-textMuted">({events.length})</span>}
      </button>

      {open && (
      <div className="mt-3 max-h-80 overflow-y-auto pr-1">
      {loading && <p className="text-sm text-textMuted">Loading...</p>}
      {!loading && events.length === 0 && <p className="text-sm text-textMuted">No events logged yet.</p>}

      <div className="relative">
        {events.map((event, idx) => {
          const Icon = iconFor(event);
          const color = STATE_COLOR[event.to_state] || "#3B82F6";
          return (
            <div key={event.id} className="flex gap-3 pb-4 last:pb-0">
              <div className="flex flex-col items-center">
                <div
                  className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full"
                  style={{ backgroundColor: `${color}22` }}
                >
                  <Icon size={14} color={color} />
                </div>
                {idx < events.length - 1 && <div className="w-px flex-1 bg-border mt-1" />}
              </div>
              <div className="pb-1">
                <p className="text-sm font-medium">{event.message}</p>
                <p className="text-xs text-textMuted">{new Date(event.created_at).toLocaleTimeString()}</p>
              </div>
            </div>
          );
        })}
      </div>
      </div>
      )}
    </div>
  );
}
