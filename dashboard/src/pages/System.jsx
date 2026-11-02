import React, { useState } from "react";
import DeviceSetup from "../components/DeviceSetup";
import { testAlert } from "../api/client";

export default function System() {
  const [testResult, setTestResult] = useState(null);

  const runTest = async (channel) => {
    setTestResult({ channel, status: "sending" });
    try {
      const res = await testAlert(channel);
      setTestResult({ channel, status: res.success ? "success" : "failed", error: res.error });
    } catch (e) {
      setTestResult({ channel, status: "failed", error: e.message });
    }
  };

  return (
    <div className="p-6 space-y-6 max-w-[1400px] mx-auto">
      <div>
        <h1 className="text-2xl font-semibold">System</h1>
        <p className="text-textMuted text-sm">Devices, connectivity, and alert configuration</p>
      </div>

      <DeviceSetup />

      <div className="rounded-xl border border-border bg-surface p-5">
        <h2 className="text-lg font-semibold mb-1">Alert Configuration Test</h2>
        <p className="text-sm text-textMuted mb-3">
          Send a harmless test message to confirm your Telegram bot and Gmail app password are wired up
          correctly in the backend's <code className="text-xs bg-base px-1 py-0.5 rounded">.env</code>.
        </p>
        <div className="flex gap-3">
          <button onClick={() => runTest("telegram")} className="rounded-lg bg-info px-3 py-1.5 text-sm text-white">
            Test Telegram
          </button>
          <button onClick={() => runTest("email")} className="rounded-lg bg-info px-3 py-1.5 text-sm text-white">
            Test Email
          </button>
        </div>
        {testResult && (
          <p className={`mt-3 text-sm ${testResult.status === "success" ? "text-safe" : testResult.status === "failed" ? "text-danger" : "text-textMuted"}`}>
            {testResult.channel}: {testResult.status}{testResult.error ? ` — ${testResult.error}` : ""}
          </p>
        )}
      </div>
    </div>
  );
}
