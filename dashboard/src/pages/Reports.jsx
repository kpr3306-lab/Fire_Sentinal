import React, { useEffect, useState } from "react";
import { Download } from "lucide-react";
import { getDevices, getReadingHistory, getEvents, getAlertHistory } from "../api/client";

const MAX_ROWS = 5000;

// RFC 4180: quote every field, double embedded quotes (window_json etc. contain commas and quotes).
export function toCsv(rows) {
  if (rows.length === 0) return "";
  const cols = Object.keys(rows[0]);
  const cell = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  return [cols.map(cell).join(","), ...rows.map((r) => cols.map((c) => cell(r[c])).join(","))].join("\r\n");
}

function download(filename, rows) {
  const blob = new Blob([toCsv(rows)], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

const stamp = () => new Date().toISOString().slice(0, 10);

export default function Reports() {
  const [devices, setDevices] = useState([]);
  const [deviceId, setDeviceId] = useState("");
  const [busy, setBusy] = useState(null);
  const [message, setMessage] = useState(null);

  useEffect(() => {
    getDevices().then((d) => {
      setDevices(d);
      if (d.length > 0) setDeviceId(d[0].device_id);
    }).catch(() => setDevices([]));
  }, []);

  const REPORTS = [
    {
      id: "readings",
      title: "Sensor readings",
      description: `Every stored reading for the selected device (latest ${MAX_ROWS.toLocaleString()}): temperature, humidity, gas, UV, flame, risk score, raw ADC counts.`,
      needsDevice: true,
      fetch: () => getReadingHistory(deviceId, MAX_ROWS),
      file: () => `ignis_readings_${deviceId}_${stamp()}.csv`,
    },
    {
      id: "events",
      title: "Incident / event log",
      description: "State changes (NORMAL → WARNING → ALERT…), snapshot captures and alerts, newest first.",
      needsDevice: true,
      fetch: () => getEvents({ device_id: deviceId }, MAX_ROWS),
      file: () => `ignis_events_${deviceId}_${stamp()}.csv`,
    },
    {
      id: "alerts",
      title: "Alert delivery log",
      description: "Every Telegram and email alert with severity and whether it was delivered. All devices.",
      needsDevice: false,
      fetch: () => getAlertHistory(MAX_ROWS),
      file: () => `ignis_alerts_${stamp()}.csv`,
    },
  ];

  const run = async (r) => {
    setBusy(r.id);
    setMessage(null);
    try {
      const rows = await r.fetch();
      if (rows.length === 0) setMessage(`${r.title}: no rows to export yet.`);
      else download(r.file(), rows);
    } catch (e) {
      setMessage(`${r.title}: export failed (${e.message}).`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="p-6 space-y-6 max-w-[1400px] mx-auto">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Reports</h1>
          <p className="text-textMuted text-sm">Export stored data as CSV (opens in Excel)</p>
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

      {message && (
        <div className="rounded-lg border border-warn/40 bg-warn/10 text-warn text-sm px-4 py-2">{message}</div>
      )}

      <div className="grid gap-4 md:grid-cols-3">
        {REPORTS.map((r) => {
          const disabled = busy != null || (r.needsDevice && !deviceId);
          return (
            <div key={r.id} className="rounded-xl border border-border bg-surface p-4 flex flex-col gap-3">
              <h2 className="font-medium">{r.title}</h2>
              <p className="text-textMuted text-sm flex-1">{r.description}</p>
              <button
                onClick={() => run(r)}
                disabled={disabled}
                className="inline-flex items-center justify-center gap-2 rounded-lg bg-info px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
              >
                <Download size={16} /> {busy === r.id ? "Exporting…" : "Download CSV"}
              </button>
            </div>
          );
        })}
      </div>
      <p className="text-textMuted text-xs">
        Timestamps are UTC as stored by the backend. Model training results are on the AI / ML page and in fire_cnn_results.xlsx / fire_yolo_results.xlsx.
      </p>
    </div>
  );
}
