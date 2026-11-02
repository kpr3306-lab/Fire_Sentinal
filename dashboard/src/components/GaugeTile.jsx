import React from "react";

/**
 * GaugeTile — analogue speedometer-style gauge + digital readout.
 *
 * 270° sweep, gap at the bottom (like a car's speedometer): angle 0 = top,
 * increasing clockwise, from -135° (min, lower-left) to +135° (max, lower-right).
 *
 * `zones` defines colored safe/warning/danger bands as cumulative fractions
 * of the range, e.g. [{ upTo: 0.6, color: '#10B981' }, { upTo: 0.85, color: '#F59E0B' },
 * { upTo: 1, color: '#EF4444' }] — 0-60% green, 60-85% amber, 85-100% red.
 */

const CX = 100;
const CY = 112;
const RADIUS = 82;
const START_ANGLE = -135;
const SWEEP = 270;

function pointOnCircle(r, angleDeg) {
  const rad = (angleDeg * Math.PI) / 180;
  return { x: CX + r * Math.sin(rad), y: CY - r * Math.cos(rad) };
}

function describeArc(r, startAngle, endAngle) {
  const start = pointOnCircle(r, startAngle);
  const end = pointOnCircle(r, endAngle);
  const largeArcFlag = endAngle - startAngle > 180 ? 1 : 0;
  return `M ${start.x.toFixed(2)} ${start.y.toFixed(2)} A ${r} ${r} 0 ${largeArcFlag} 1 ${end.x.toFixed(2)} ${end.y.toFixed(2)}`;
}

function currentZoneColor(fraction, zones) {
  for (const z of zones) {
    if (fraction <= z.upTo) return z.color;
  }
  return zones[zones.length - 1]?.color || "#3B82F6";
}

export default function GaugeTile({
  label,
  value,
  min = 0,
  max = 100,
  unit = "",
  decimals = 1,
  zones = [
    { upTo: 0.6, color: "#10B981" },
    { upTo: 0.85, color: "#F59E0B" },
    { upTo: 1, color: "#EF4444" },
  ],
  icon: Icon,
  subtext,
}) {
  const safeValue = Number.isFinite(value) ? value : min;
  const fraction = Math.min(1, Math.max(0, (safeValue - min) / (max - min || 1)));
  const needleAngle = START_ANGLE + fraction * SWEEP;
  const zoneColor = currentZoneColor(fraction, zones);

  const ticks = Array.from({ length: 11 }, (_, i) => i); // 0%..100% in 10% steps

  return (
    <div className="flex flex-col items-center rounded-xl border border-border bg-surface px-4 pt-4 pb-3">
      <div className="flex w-full items-center justify-between mb-1">
        <span className="text-sm font-medium text-textMuted">{label}</span>
        {Icon && <Icon size={16} className="text-textMuted" />}
      </div>

      <svg viewBox="0 0 200 190" className="w-full max-w-[180px]">
        {/* Background track */}
        <path
          d={describeArc(RADIUS, START_ANGLE, START_ANGLE + SWEEP)}
          fill="none"
          stroke="#1F2A3D"
          strokeWidth="10"
          strokeLinecap="round"
        />

        {/* Colored zone bands */}
        {zones.map((z, i) => {
          const fromFrac = i === 0 ? 0 : zones[i - 1].upTo;
          const fromAngle = START_ANGLE + fromFrac * SWEEP;
          const toAngle = START_ANGLE + z.upTo * SWEEP;
          return (
            <path
              key={i}
              d={describeArc(RADIUS, fromAngle, toAngle)}
              fill="none"
              stroke={z.color}
              strokeWidth="4"
              strokeLinecap="round"
              opacity="0.55"
            />
          );
        })}

        {/* Tick marks */}
        {ticks.map((i) => {
          const angle = START_ANGLE + (i / 10) * SWEEP;
          const isMajor = i === 0 || i === 5 || i === 10;
          const outer = pointOnCircle(RADIUS - 10, angle);
          const inner = pointOnCircle(RADIUS - (isMajor ? 20 : 16), angle);
          return (
            <line
              key={i}
              x1={outer.x}
              y1={outer.y}
              x2={inner.x}
              y2={inner.y}
              stroke={isMajor ? "#8B96A8" : "#3A4356"}
              strokeWidth={isMajor ? 2 : 1}
            />
          );
        })}

        {/* Min / max labels */}
        <text x={pointOnCircle(RADIUS - 32, START_ANGLE).x} y={pointOnCircle(RADIUS - 32, START_ANGLE).y}
              fill="#8B96A8" fontSize="9" textAnchor="middle">{min}</text>
        <text x={pointOnCircle(RADIUS - 32, START_ANGLE + SWEEP).x} y={pointOnCircle(RADIUS - 32, START_ANGLE + SWEEP).y}
              fill="#8B96A8" fontSize="9" textAnchor="middle">{max}</text>

        {/* Needle */}
        <g
          style={{
            transform: `rotate(${needleAngle}deg)`,
            transformOrigin: `${CX}px ${CY}px`,
            transition: "transform 0.7s cubic-bezier(0.34, 1.56, 0.64, 1)",
          }}
        >
          <polygon
            points={`${CX - 3},${CY} ${CX + 3},${CY} ${CX},${CY - RADIUS + 22}`}
            fill={zoneColor}
          />
        </g>
        <circle cx={CX} cy={CY} r="7" fill="#0A0F1A" stroke={zoneColor} strokeWidth="2.5" />

        {/* Digital readout, inside the gauge body */}
        <text
          x={CX}
          y={CY + 34}
          textAnchor="middle"
          fontFamily="'IBM Plex Mono', monospace"
          fontWeight="600"
          fontSize="26"
          fill={zoneColor}
          className="tabular-nums"
        >
          {safeValue.toFixed(decimals)}
        </text>
        <text x={CX} y={CY + 50} textAnchor="middle" fontSize="11" fill="#8B96A8">
          {unit}
        </text>
      </svg>

      {subtext && <span className="text-xs text-textMuted mt-1">{subtext}</span>}
    </div>
  );
}
