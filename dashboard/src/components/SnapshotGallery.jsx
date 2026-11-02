import React, { useEffect, useState } from "react";
import { Image as ImageIcon, X } from "lucide-react";
import { getSnapshots, snapshotFileUrl } from "../api/client";

const REASON_LABEL = {
  precursor: "Precursor",
  confirming: "Confirming",
  fire_confirmed: "Fire Confirmed",
  on_demand: "On Demand",
};

export default function SnapshotGallery({ roomId, deviceId, limit = 12 }) {
  const [snapshots, setSnapshots] = useState([]);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const params = deviceId ? { device_id: deviceId } : roomId ? { room_id: roomId } : {};
    const refresh = () =>
      getSnapshots(params, limit)
        .then((data) => !cancelled && setSnapshots(data))
        .catch(() => {}) // keep the last good list through a failed poll
        .finally(() => !cancelled && setLoading(false));
    refresh();
    const interval = setInterval(refresh, 10000); // new captures show up without a page reload
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [roomId, deviceId, limit]);

  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <ImageIcon size={18} className="text-textMuted" />
          <span className="font-medium">Snapshot History</span>
        </div>
        <span className="text-xs text-textMuted">{snapshots.length} captures</span>
      </div>

      {loading && <p className="text-sm text-textMuted">Loading snapshots...</p>}
      {!loading && snapshots.length === 0 && (
        <p className="text-sm text-textMuted">No snapshots yet — they'll appear here any time the camera fires.</p>
      )}

      {!loading && snapshots.length > 0 && (
        <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 gap-2">
          {snapshots.map((s) => (
            <button
              key={s.id}
              onClick={() => setSelected(s)}
              className="group relative aspect-square rounded-lg overflow-hidden border border-border hover:border-info transition-colors"
            >
              <img src={snapshotFileUrl(s.id)} alt={s.reason} className="w-full h-full object-cover" />
              <span className="absolute bottom-0 left-0 right-0 bg-black/70 text-[10px] px-1 py-0.5 text-white truncate">
                {REASON_LABEL[s.reason] || s.reason}
              </span>
            </button>
          ))}
        </div>
      )}

      {selected && (
        <div
          className="fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-6"
          onClick={() => setSelected(null)}
        >
          <div className="max-w-2xl w-full bg-surfaceRaised rounded-xl overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-3 border-b border-border">
              <div>
                <p className="text-sm font-medium">{REASON_LABEL[selected.reason] || selected.reason}</p>
                <p className="text-xs text-textMuted">{new Date(selected.created_at).toLocaleString()}</p>
              </div>
              <button onClick={() => setSelected(null)} className="text-textMuted hover:text-textPrimary">
                <X size={20} />
              </button>
            </div>
            <img src={snapshotFileUrl(selected.id)} alt={selected.reason} className="w-full max-h-[70vh] object-contain bg-black" />
            <div className="p-3 text-sm text-textMuted">
              Classification: <span className="text-textPrimary">{selected.classification}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
