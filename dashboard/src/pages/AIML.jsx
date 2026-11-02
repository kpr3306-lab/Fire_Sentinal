import React, { useEffect, useState } from "react";
import { getModelInfo } from "../api/client";

// Static training results copied from fire_cnn_results.xlsx / fire_yolo_results.xlsx (18-Oct-2026).
// The INT8 CNN numbers come live from /api/model-info; these fill in what the manifest doesn't carry.
const CNN_FP32 = { accuracy: 0.9776, macro_f1: 0.9696, hazardous_recall: 0.9152, false_hazard_alarm_rate: 0.0078, size_kb: 1572.9, latency_ms: 0.5 };
const CNN_INT8_LATENCY_MS = 0.44;
const YOLO = {
  model: "YOLO11n", params: 2597051, gflops: 6.4, size_mb: 5.5, imgsz: 640, epochs: 50, train_hours: 0.731, t4_ms: 4.6,
  val: { images: 855, boxes: 734, precision: 0.798, recall: 0.599, f1: 0.684, map50: 0.685, map50_95: 0.346 },
  test: { images: 796, boxes: 591, precision: 0.764, recall: 0.569, f1: 0.652, map50: 0.633, map50_95: 0.374 },
};

const pct = (v) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);

function Stat({ label, value, note }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <p className="text-textMuted text-xs">{label}</p>
      <p className="text-2xl font-semibold font-mono mt-1">{value}</p>
      {note && <p className="text-textMuted text-xs mt-1">{note}</p>}
    </div>
  );
}

function Card({ title, subtitle, children }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4 space-y-3">
      <div>
        <h2 className="font-medium">{title}</h2>
        {subtitle && <p className="text-textMuted text-xs">{subtitle}</p>}
      </div>
      {children}
    </div>
  );
}

function ConfusionMatrix({ matrix, labels }) {
  const max = Math.max(...matrix.flat());
  return (
    <div className="overflow-x-auto">
      <table className="text-sm">
        <thead>
          <tr className="text-textMuted">
            <th className="px-3 py-2 text-left font-medium">True ↓ / Predicted →</th>
            {labels.map((l) => <th key={l} className="px-3 py-2 font-medium">{l}</th>)}
            <th className="px-3 py-2 font-medium">Recall</th>
          </tr>
        </thead>
        <tbody>
          {matrix.map((row, i) => {
            const total = row.reduce((a, b) => a + b, 0);
            return (
              <tr key={labels[i]}>
                <th className="px-3 py-2 text-left font-medium text-textMuted">{labels[i]}</th>
                {row.map((n, j) => (
                  <td
                    key={j}
                    title={`${labels[i]} predicted as ${labels[j]}: ${n}`}
                    className="px-3 py-2 text-center font-mono border-2 border-surface rounded"
                    style={{ background: `rgba(59,130,246,${(0.08 + 0.72 * (n / max)).toFixed(2)})` }}
                  >
                    {n}
                  </td>
                ))}
                <td className="px-3 py-2 text-center font-mono">{pct(total ? row[i] / total : null)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function AIML() {
  const [info, setInfo] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    getModelInfo().then(setInfo).catch(() => setError("Could not load /api/model-info."));
  }, []);

  const trained = info?.status === "trained";
  const t = info?.test || {};

  return (
    <div className="p-6 space-y-6 max-w-[1400px] mx-auto">
      <div>
        <h1 className="text-2xl font-semibold">AI / ML</h1>
        <p className="text-textMuted text-sm">Models running in Fire Sentinel and their test-set results</p>
      </div>

      {error && <div className="rounded-lg border border-warn/40 bg-warn/10 text-warn text-sm px-4 py-2">{error}</div>}
      {info && !trained && (
        <div className="rounded-lg border border-warn/40 bg-warn/10 text-warn text-sm px-4 py-2">{info.message}</div>
      )}

      {trained && (
        <>
          <Card
            title={`Snapshot CNN — ${info.backbone} (v${info.version})`}
            subtitle={`INT8 TFLite, input ${info.input?.shape?.join("×")}, trained ${new Date(info.trained_at).toLocaleDateString()} · test split of ${t.n} images never seen in training`}
          >
            <div className="grid gap-3 grid-cols-2 lg:grid-cols-5">
              <Stat label="Accuracy" value={pct(t.accuracy)} />
              <Stat label="Macro F1" value={pct(t.macro_f1)} />
              <Stat label="Hazardous recall" value={pct(t.hazardous_recall)} note="real hazardous fires flagged" />
              <Stat label="False hazard alarms" value={pct(t.false_hazard_alarm_rate)} note="harmless scene → hazardous" />
              <Stat label="Model size" value={`${(info.size_bytes / 1024).toFixed(0)} KB`} note={`${(info.fp32_size_bytes / info.size_bytes).toFixed(1)}× smaller than FP32`} />
            </div>
            {t.confusion_matrix && <ConfusionMatrix matrix={t.confusion_matrix} labels={info.output.labels} />}
            {info.train_counts && (
              <p className="text-textMuted text-xs">
                Training images: {Object.entries(info.train_counts).map(([k, v]) => `${k} ${v.toLocaleString()}`).join(" · ")}
              </p>
            )}
          </Card>

          <Card title="Quantization: FP32 vs INT8" subtitle="From fire_cnn_results.xlsx. Latency is laptop CPU, not the ESP32.">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-textMuted text-left">
                    <th className="px-3 py-2 font-medium">Metric</th>
                    <th className="px-3 py-2 font-medium">FP32</th>
                    <th className="px-3 py-2 font-medium">INT8 (deployed)</th>
                  </tr>
                </thead>
                <tbody className="font-mono">
                  {[
                    ["Accuracy", pct(CNN_FP32.accuracy), pct(t.accuracy)],
                    ["Macro F1", pct(CNN_FP32.macro_f1), pct(t.macro_f1)],
                    ["Hazardous recall", pct(CNN_FP32.hazardous_recall), pct(t.hazardous_recall)],
                    ["False hazard alarm rate", pct(CNN_FP32.false_hazard_alarm_rate), pct(t.false_hazard_alarm_rate)],
                    ["Size (KB)", CNN_FP32.size_kb.toFixed(1), (info.size_bytes / 1024).toFixed(1)],
                    ["Host latency (ms)", CNN_FP32.latency_ms.toFixed(2), CNN_INT8_LATENCY_MS.toFixed(2)],
                  ].map(([m, a, b]) => (
                    <tr key={m} className="border-b border-border last:border-0">
                      <td className="px-3 py-2 font-sans">{m}</td><td className="px-3 py-2">{a}</td><td className="px-3 py-2">{b}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}

      <Card
        title={`Flame detector — ${YOLO.model}`}
        subtitle={`Single class "fire" · ${YOLO.params.toLocaleString()} params · ${YOLO.gflops} GFLOPs · ${YOLO.size_mb} MB · ${YOLO.imgsz} px · ${YOLO.epochs} epochs (${YOLO.train_hours} h on Colab T4, ${YOLO.t4_ms} ms/image). From fire_yolo_results.xlsx.`}
      >
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-textMuted text-left">
                <th className="px-3 py-2 font-medium">Split</th>
                <th className="px-3 py-2 font-medium">Images</th>
                <th className="px-3 py-2 font-medium">Flame boxes</th>
                <th className="px-3 py-2 font-medium">Precision</th>
                <th className="px-3 py-2 font-medium">Recall</th>
                <th className="px-3 py-2 font-medium">F1</th>
                <th className="px-3 py-2 font-medium">mAP50</th>
                <th className="px-3 py-2 font-medium">mAP50-95</th>
              </tr>
            </thead>
            <tbody className="font-mono">
              {[["Validation", YOLO.val], ["Test", YOLO.test]].map(([name, s]) => (
                <tr key={name} className="border-b border-border last:border-0">
                  <td className="px-3 py-2 font-sans">{name}</td>
                  <td className="px-3 py-2">{s.images}</td><td className="px-3 py-2">{s.boxes}</td>
                  <td className="px-3 py-2">{pct(s.precision)}</td><td className="px-3 py-2">{pct(s.recall)}</td>
                  <td className="px-3 py-2">{pct(s.f1)}</td><td className="px-3 py-2">{pct(s.map50)}</td>
                  <td className="px-3 py-2">{pct(s.map50_95)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-textMuted text-xs">
          Recall is the weak number (~57% of flame boxes found on test); small, distant stove flames are the likely cause.
          The CNN is the more reliable "is there fire" signal; YOLO supplies flame location and area.
        </p>
      </Card>

      <Card title="On-device sensor classifier" subtitle="ml/sensor — runs on the ESP32 over 30 s sensor windows">
        <p className="text-textMuted text-sm">Not trained yet: no artifacts in ml/sensor/artifacts. Results will appear here after train_sensor.py runs.</p>
      </Card>
    </div>
  );
}
