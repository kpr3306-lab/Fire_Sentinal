import React, { useEffect, useState, useCallback } from "react";
import { Thermometer, Droplets, Wind, Sun, Flame as FlameIcon } from "lucide-react";
import GaugeTile from "../components/GaugeTile";
import RiskScorePanel from "../components/RiskScorePanel";
import CameraPanel from "../components/CameraPanel";
import EmergencyContacts from "../components/EmergencyContacts";
import SnapshotGallery from "../components/SnapshotGallery";
import DetectionTimeline from "../components/DetectionTimeline";
import { getRooms, getDevices, getLatestReading, getSnapshots } from "../api/client";

const POLL_INTERVAL_MS = 3000;

export default function Dashboard() {
  const [rooms, setRooms] = useState([]);
  const [devices, setDevices] = useState([]);
  const [selectedRoomId, setSelectedRoomId] = useState(null);
  const [reading, setReading] = useState(null);
  const [latestClassification, setLatestClassification] = useState("PENDING_MODEL");
  const [error, setError] = useState(null);

  useEffect(() => {
    getRooms().then((r) => {
      setRooms(r);
      if (r.length > 0) setSelectedRoomId(r[0].id);
    }).catch(() => setRooms([]));
    getDevices().then(setDevices).catch(() => setDevices([]));
  }, []);

  // No rooms yet: show the most recently seen device (the backend lists devices newest first).
  const deviceForRoom = selectedRoomId ? devices.find((d) => d.room_id === selectedRoomId) : devices[0];

  const pollReading = useCallback(() => {
    const params = selectedRoomId ? { room_id: selectedRoomId } : deviceForRoom ? { device_id: deviceForRoom.device_id } : null;
    if (!params) return;
    getLatestReading(params)
      .then((r) => { setReading(r); setError(null); })
      .catch(() => setError("No readings for this room yet."));
  }, [selectedRoomId, deviceForRoom]);

  useEffect(() => {
    pollReading();
    const interval = setInterval(pollReading, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [pollReading]);

  useEffect(() => {
    if (!deviceForRoom) return;
    getSnapshots({ device_id: deviceForRoom.device_id }, 1)
      .then((snaps) => setLatestClassification(snaps[0]?.classification || "PENDING_MODEL"))
      .catch(() => {});
  }, [deviceForRoom, reading]);

  return (
    <div className="p-6 space-y-6 max-w-[1400px] mx-auto">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Dashboard</h1>
          <p className="text-textMuted text-sm">Live status of your fire detection system</p>
        </div>
        <select
          value={selectedRoomId || ""}
          onChange={(e) => setSelectedRoomId(Number(e.target.value))}
          className="rounded-lg bg-surface border border-border px-3 py-2 text-sm"
        >
          {rooms.map((r) => (
            <option key={r.id} value={r.id}>{r.name}</option>
          ))}
          {rooms.length === 0 && <option>No rooms yet</option>}
        </select>
      </div>

      {error && (
        <div className="rounded-lg border border-warn/40 bg-warn/10 text-warn text-sm px-4 py-2">{error}</div>
      )}

      {/* Risk overview row */}
      <RiskScorePanel
        state={reading?.state || "NORMAL"}
        riskScore={reading?.risk_score || 0}
        classification={latestClassification}
      />

      {/* Gauge grid + side panel */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        <div className="lg:col-span-3 grid grid-cols-2 sm:grid-cols-3 gap-4">
          <GaugeTile
            label="Temperature" icon={Thermometer}
            value={reading?.temperature_c} min={-10} max={60} unit="°C"
            zones={[{ upTo: 0.55, color: "#10B981" }, { upTo: 0.75, color: "#F59E0B" }, { upTo: 1, color: "#EF4444" }]}
          />
          <GaugeTile
            label="Humidity" icon={Droplets}
            value={reading?.humidity_pct} min={0} max={100} unit="%" decimals={0}
            zones={[{ upTo: 1, color: "#3B82F6" }]}
          />
          <GaugeTile
            label="MQ-2 (LPG/Smoke)" icon={Wind}
            value={reading?.mq2_ppm} min={0} max={500} unit="ppm" decimals={0}
            zones={[{ upTo: 0.4, color: "#10B981" }, { upTo: 0.7, color: "#F59E0B" }, { upTo: 1, color: "#EF4444" }]}
          />
          <GaugeTile
            label="MQ-7 (CO)" icon={Wind}
            value={reading?.mq7_ppm} min={0} max={200} unit="ppm" decimals={0}
            zones={[{ upTo: 0.4, color: "#10B981" }, { upTo: 0.7, color: "#F59E0B" }, { upTo: 1, color: "#EF4444" }]}
          />
          <GaugeTile
            label="MQ-135 (Air Quality)" icon={Wind}
            value={reading?.mq135_ppm} min={0} max={300} unit="ppm" decimals={0}
            zones={[{ upTo: 0.4, color: "#10B981" }, { upTo: 0.7, color: "#F59E0B" }, { upTo: 1, color: "#EF4444" }]}
          />
          <GaugeTile
            label="UV Index" icon={Sun}
            value={reading?.uv_index} min={0} max={15} unit="index" decimals={1}
            zones={[{ upTo: 0.5, color: "#10B981" }, { upTo: 0.8, color: "#F59E0B" }, { upTo: 1, color: "#EF4444" }]}
          />
        </div>

        <div className="flex flex-col gap-4">
          <div className={`rounded-xl border p-4 flex items-center gap-3 ${reading?.flame_detected ? "border-danger bg-danger/10" : "border-border bg-surface"}`}>
            <FlameIcon size={22} className={reading?.flame_detected ? "text-danger" : "text-textMuted"} />
            <div>
              <p className="text-sm font-medium">{reading?.flame_detected ? "Flame Detected" : "No Flame"}</p>
              <p className="text-xs text-textMuted">B35 IR flame sensor</p>
            </div>
          </div>
          <CameraPanel deviceId={deviceForRoom?.device_id} />
        </div>
      </div>

      {/* Gas source hint */}
      {reading?.gas_source_hint && (
        <div className="rounded-xl border border-border bg-surface p-4 text-sm">
          <span className="text-textMuted">Gas source hint: </span>
          <span>{reading.gas_source_hint}</span>
        </div>
      )}

      {/* Timeline + snapshots + contacts */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <DetectionTimeline roomId={selectedRoomId} />
        <div className="lg:col-span-2">
          <SnapshotGallery roomId={selectedRoomId} />
        </div>
      </div>

      <EmergencyContacts />
    </div>
  );
}
