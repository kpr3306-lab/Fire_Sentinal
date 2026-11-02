import React, { useEffect, useState } from "react";
import { CheckCircle2, XCircle } from "lucide-react";
import { getAlertHistory } from "../api/client";

const SEVERITY_COLOR = { info: "#3B82F6", warning: "#F59E0B", critical: "#EF4444" };

export default function Alerts() {
  const [alerts, setAlerts] = useState([]);

  useEffect(() => {
    getAlertHistory(100).then(setAlerts).catch(() => setAlerts([]));
  }, []);

  return (
    <div className="p-6 space-y-6 max-w-[1400px] mx-auto">
      <div>
        <h1 className="text-2xl font-semibold">Alerts</h1>
        <p className="text-textMuted text-sm">Telegram and email alerts sent by the system</p>
      </div>

      <div className="rounded-xl border border-border bg-surface overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-textMuted text-left">
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium">Channel</th>
              <th className="px-4 py-3 font-medium">Severity</th>
              <th className="px-4 py-3 font-medium">Device</th>
              <th className="px-4 py-3 font-medium">Message</th>
              <th className="px-4 py-3 font-medium">Sent</th>
            </tr>
          </thead>
          <tbody>
            {alerts.map((a) => (
              <tr key={a.id} className="border-b border-border last:border-0">
                <td className="px-4 py-3">
                  {a.success ? <CheckCircle2 size={16} className="text-safe" /> : <XCircle size={16} className="text-danger" />}
                </td>
                <td className="px-4 py-3 capitalize">{a.channel}</td>
                <td className="px-4 py-3">
                  <span style={{ color: SEVERITY_COLOR[a.severity] }}>{a.severity}</span>
                </td>
                <td className="px-4 py-3 font-mono text-xs text-textMuted">{a.device_id}</td>
                <td className="px-4 py-3 text-textMuted max-w-xs truncate">{a.message}</td>
                <td className="px-4 py-3 text-textMuted whitespace-nowrap">{new Date(a.sent_at).toLocaleString()}</td>
              </tr>
            ))}
            {alerts.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-6 text-center text-textMuted">No alerts sent yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
