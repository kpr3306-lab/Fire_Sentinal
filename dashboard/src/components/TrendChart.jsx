import React, { useState } from "react";

/**
 * TrendChart — single-series SVG line chart with a hover crosshair + tooltip.
 * One series per chart (small multiples), so no legend: the title names it.
 * `points` = [{ t: Date, v: number }] in chronological order.
 */

const W = 600;
const H = 160;
const PAD = { top: 10, right: 10, bottom: 20, left: 40 };

export default function TrendChart({ label, unit = "", points, decimals = 1, color = "#3B82F6" }) {
  const [hover, setHover] = useState(null);
  const pts = points.filter((p) => p.v != null && !Number.isNaN(p.v));

  if (pts.length < 2) {
    return (
      <div className="rounded-xl border border-border bg-surface p-4">
        <p className="text-sm font-medium">{label}</p>
        <p className="text-textMuted text-xs mt-6 mb-6 text-center">Not enough readings yet.</p>
      </div>
    );
  }

  let lo = Math.min(...pts.map((p) => p.v));
  let hi = Math.max(...pts.map((p) => p.v));
  if (hi === lo) { hi += 1; lo -= 1; }   // flat line: give it some vertical room
  const t0 = pts[0].t.getTime();
  const t1 = pts[pts.length - 1].t.getTime() || t0 + 1;
  const x = (t) => PAD.left + ((t.getTime() - t0) / (t1 - t0 || 1)) * (W - PAD.left - PAD.right);
  const y = (v) => PAD.top + (1 - (v - lo) / (hi - lo)) * (H - PAD.top - PAD.bottom);
  const path = pts.map((p, i) => `${i ? "L" : "M"}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
  const fmt = (v) => `${v.toFixed(decimals)}${unit}`;
  const last = pts[pts.length - 1];

  const onMove = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    const sx = ((e.clientX - r.left) / r.width) * W;
    let best = 0;
    pts.forEach((p, i) => { if (Math.abs(x(p.t) - sx) < Math.abs(x(pts[best].t) - sx)) best = i; });
    setHover(best);
  };

  const h = hover != null ? pts[hover] : null;

  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="flex items-baseline justify-between mb-2">
        <p className="text-sm font-medium">{label}</p>
        <p className="text-sm font-mono">{fmt(last.v)}</p>
      </div>
      <div className="relative">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="w-full h-auto"
          onMouseMove={onMove}
          onMouseLeave={() => setHover(null)}
          role="img"
          aria-label={`${label}: ${pts.length} readings, latest ${fmt(last.v)}, range ${fmt(lo)} to ${fmt(hi)}`}
        >
          {[lo, (lo + hi) / 2, hi].map((g) => (
            <g key={g}>
              <line x1={PAD.left} x2={W - PAD.right} y1={y(g)} y2={y(g)} stroke="#1F2A3D" strokeWidth="1" />
              <text x={PAD.left - 6} y={y(g) + 4} textAnchor="end" fontSize="11" fill="#8B96A8">{g.toFixed(decimals)}</text>
            </g>
          ))}
          <text x={PAD.left} y={H - 4} fontSize="11" fill="#8B96A8">{pts[0].t.toLocaleTimeString()}</text>
          <text x={W - PAD.right} y={H - 4} textAnchor="end" fontSize="11" fill="#8B96A8">{last.t.toLocaleTimeString()}</text>
          <path d={path} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
          {h && (
            <>
              <line x1={x(h.t)} x2={x(h.t)} y1={PAD.top} y2={H - PAD.bottom} stroke="#8B96A8" strokeWidth="1" strokeDasharray="3 3" />
              <circle cx={x(h.t)} cy={y(h.v)} r="4" fill={color} stroke="#111827" strokeWidth="2" />
            </>
          )}
        </svg>
        {h && (
          <div
            className="absolute top-0 pointer-events-none rounded-md border border-border bg-surfaceRaised px-2 py-1 text-xs whitespace-nowrap"
            style={{ left: `${(x(h.t) / W) * 100}%`, transform: x(h.t) > W / 2 ? "translateX(-110%)" : "translateX(10%)" }}
          >
            <span className="font-mono">{fmt(h.v)}</span>
            <span className="text-textMuted ml-2">{h.t.toLocaleTimeString()}</span>
          </div>
        )}
      </div>
    </div>
  );
}
