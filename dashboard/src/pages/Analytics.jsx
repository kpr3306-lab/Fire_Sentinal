import React, { useEffect, useState, useCallback } from "react";
import TrendChart from "../components/TrendChart";
import { getDevices, getReadingHistory } from "../api/client";

const REFRESH_MS = 10000;

// SQLite CURRENT_TIMESTAMP is UTC "YYYY-MM-DD HH:MM:SS" with no zone marker.
export const parseDbTime = (s) => new Date(s.includes("T") ? s : `${s.replace(" ", "T")}Z`);

const CHARTS = [
  { key: "risk_score", label: "Risk score", unit: "", decimals: 0, color: "#EF4444" },
  { key: "temperature_c", label: "Temperature", unit: "°C", decimals: 1 },
  { key: "humidity_pct", label: "Humidity", unit: "%", decimals: 0 },
  { key: "pressure_hpa", label: "Pressure", unit: " hPa", decimals: 0 },
  { key: "mq2_ppm", label: "MQ-2 smoke / LPG (est. ppm)", unit: "", decimals: 0 },
  { key: "mq7_ppm", label: "MQ-7 CO (est. ppm)", unit: "", decimals: 0 },
  { key: "mq135_ppm", label: "MQ-135 air quality (est. ppm)", unit: "", decimals: 0 },
  { key: "uv_index", label: "UV index (est.)", unit: "", decimals: 1 },
];

export default function Analytics() {
  const [devices, setDevices] = useState([]);
  const [deviceId, setDeviceId] = useState("");
  const [limit, setLimit] = useState(200);
  const [rows, setRows] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    getDevices().then((d) => {
      setDevices(d);
      if (d.length > 0) setDeviceId(d[0].device_id);
    }).catch(() => setDevices([]));
  }, []);

  const load = useCallback(() => {
    if (!deviceId) return;
    getReadingHistory(deviceId, limit)
      .then((r) => { setRows(r); setError(null); })
      .catch(() => setError("Could not load sensor history."));
  }, [deviceId, limit]);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  return (
    <div className="p-6 space-y-6 max-w-[1400px] mx-auto">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Analytics</h1>
          <p className="text-textMuted text-sm">Sensor trends from stored readings. Refreshes every 10 s.</p>
        </div>
        <div className="flex gap-2">
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
          <select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="rounded-lg bg-surface border border-border px-3 py-2 text-sm"
            aria-label="Number of readings"
          >
            {[50, 200, 500, 1000].map((n) => <option key={n} value={n}>Last {n} readings</option>)}
          </select>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-warn/40 bg-warn/10 text-warn text-sm px-4 py-2">{error}</div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        {CHARTS.map((c) => (
          <TrendChart
            key={c.key}
            label={c.label}
            unit={c.unit}
            decimals={c.decimals}
            color={c.color}
            points={rows.map((r) => ({ t: parseDbTime(r.created_at), v: r[c.key] }))}
          />
        ))}
      </div>
      <p className="text-textMuted text-xs">
        Gas and UV values are placeholder linear estimates from the raw ADC counts, not calibrated ppm.
      </p>
    </div>
  );
}
