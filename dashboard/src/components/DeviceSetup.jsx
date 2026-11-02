import React, { useEffect, useState } from "react";
import { Wifi, WifiOff, Settings2, Check } from "lucide-react";
import { getDevices, getRooms, assignRoom, setDeviceOverride } from "../api/client";

function timeAgo(isoString) {
  if (!isoString) return "never";
  const seconds = Math.floor((Date.now() - new Date(isoString + "Z")) / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ago`;
}

export default function DeviceSetup() {
  const [devices, setDevices] = useState([]);
  const [rooms, setRooms] = useState([]);
  const [editingOverride, setEditingOverride] = useState(null); // device_id currently being edited
  const [overrideForm, setOverrideForm] = useState({ ip: "", port: 80 });

  const refresh = () => {
    getDevices().then(setDevices).catch(() => setDevices([]));
    getRooms().then(setRooms).catch(() => setRooms([]));
  };

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 10000); // devices re-announce every 60s; poll a bit faster
    return () => clearInterval(interval);
  }, []);

  const handleRoomChange = async (deviceId, roomId) => {
    await assignRoom(deviceId, roomId ? Number(roomId) : null);
    refresh();
  };

  const startOverride = (device) => {
    setEditingOverride(device.device_id);
    setOverrideForm({ ip: device.ip_override || device.ip || "", port: device.port_override || device.port || 80 });
  };

  const saveOverride = async (deviceId) => {
    await setDeviceOverride(deviceId, { ip: overrideForm.ip, port: Number(overrideForm.port), use_override: true });
    setEditingOverride(null);
    refresh();
  };

  const clearOverride = async (deviceId) => {
    await setDeviceOverride(deviceId, { use_override: false });
    refresh();
  };

  return (
    <div className="rounded-xl border border-border bg-surface p-5">
      <div className="mb-4">
        <h2 className="text-lg font-semibold">Devices</h2>
        <p className="text-sm text-textMuted">
          Devices announce their own address on boot — nothing to configure by hand. Assign a room below,
          or pin a manual address if you need to bypass auto-discovery.
        </p>
      </div>

      {devices.length === 0 && (
        <p className="text-sm text-textMuted">No devices have registered yet. Power on your ESP32-S3 and check its Serial output.</p>
      )}

      <div className="space-y-3">
        {devices.map((d) => {
          const online = d.last_seen_at && Date.now() - new Date(d.last_seen_at + "Z").getTime() < 90000;
          const activeIp = d.use_override ? d.ip_override : d.ip;
          const activePort = d.use_override ? d.port_override : d.port;

          return (
            <div key={d.device_id} className="rounded-lg border border-border bg-base p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  {online ? <Wifi size={18} className="text-safe" /> : <WifiOff size={18} className="text-textMuted" />}
                  <div>
                    <p className="text-sm font-medium">{d.device_name || d.device_id}</p>
                    <p className="text-xs text-textMuted font-mono">{d.device_id}</p>
                  </div>
                </div>

                <div className="flex items-center gap-4 text-xs text-textMuted">
                  <span className="font-mono">
                    {activeIp || "—"}:{activePort || "—"} {d.use_override && "(manual)"}
                  </span>
                  <span>Last seen {timeAgo(d.last_seen_at)}</span>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-3 mt-3">
                <select
                  value={d.room_id || ""}
                  onChange={(e) => handleRoomChange(d.device_id, e.target.value)}
                  className="rounded-lg bg-surface border border-border text-sm px-2 py-1.5 text-textPrimary"
                >
                  <option value="">Unassigned</option>
                  {rooms.map((r) => (
                    <option key={r.id} value={r.id}>{r.name}</option>
                  ))}
                </select>

                {editingOverride !== d.device_id ? (
                  <button
                    onClick={() => startOverride(d)}
                    className="flex items-center gap-1 text-xs text-textMuted hover:text-textPrimary"
                  >
                    <Settings2 size={14} /> {d.use_override ? "Edit override" : "Set manual override"}
                  </button>
                ) : (
                  <div className="flex items-center gap-2">
                    <input
                      value={overrideForm.ip}
                      onChange={(e) => setOverrideForm({ ...overrideForm, ip: e.target.value })}
                      placeholder="192.168.1.50"
                      className="w-32 rounded-lg bg-surface border border-border text-xs px-2 py-1.5 font-mono"
                    />
                    <input
                      value={overrideForm.port}
                      onChange={(e) => setOverrideForm({ ...overrideForm, port: e.target.value })}
                      placeholder="80"
                      className="w-16 rounded-lg bg-surface border border-border text-xs px-2 py-1.5 font-mono"
                    />
                    <button onClick={() => saveOverride(d.device_id)} className="text-safe hover:text-emerald-400">
                      <Check size={16} />
                    </button>
                  </div>
                )}

                {d.use_override && editingOverride !== d.device_id && (
                  <button onClick={() => clearOverride(d.device_id)} className="text-xs text-textMuted hover:text-danger">
                    Clear override
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
