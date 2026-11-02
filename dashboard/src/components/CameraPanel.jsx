import React, { useState } from "react";
import { Video, Loader2, AlertCircle } from "lucide-react";
import { captureProxyUrl } from "../api/client";

export default function CameraPanel({ deviceId }) {
  const [imageUrl, setImageUrl] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [capturedAt, setCapturedAt] = useState(null);

  const handleTurnOn = async () => {
    if (!deviceId) {
      setError("No device assigned to this room yet.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(captureProxyUrl(deviceId));
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error || `Camera returned ${res.status}`);
      }
      const blob = await res.blob();
      setImageUrl(URL.createObjectURL(blob));
      setCapturedAt(new Date());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="rounded-xl border border-border bg-surface p-4 flex flex-col h-full">
      <div className="flex items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-2 min-w-0">
          <Video size={18} className="text-textMuted shrink-0" />
          <span className="font-medium">Camera</span>
          <span className="text-xs text-textMuted truncate">(On Demand)</span>
        </div>
        <button
          onClick={handleTurnOn}
          disabled={loading}
          className="shrink-0 whitespace-nowrap rounded-lg bg-info px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-600 disabled:opacity-50 transition-colors"
        >
          {loading ? "Capturing..." : "Turn On"}
        </button>
      </div>

      <div className="flex-1 flex items-center justify-center rounded-lg bg-base border border-border overflow-hidden min-h-[180px]">
        {loading && <Loader2 className="animate-spin text-textMuted" size={28} />}
        {!loading && error && (
          <div className="flex flex-col items-center gap-2 text-danger text-sm px-4 text-center">
            <AlertCircle size={22} />
            {error}
          </div>
        )}
        {!loading && !error && imageUrl && (
          <img src={imageUrl} alt="Latest camera capture" className="w-full h-full object-cover" />
        )}
        {!loading && !error && !imageUrl && (
          <span className="text-textMuted text-sm">No capture yet — tap Turn On</span>
        )}
      </div>

      {capturedAt && (
        <p className="text-xs text-textMuted mt-2">
          Last capture: {capturedAt.toLocaleTimeString()}
        </p>
      )}
    </div>
  );
}
