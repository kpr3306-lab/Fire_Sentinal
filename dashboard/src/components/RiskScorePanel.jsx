import React from "react";
import { ShieldCheck, AlertTriangle, Flame, HelpCircle } from "lucide-react";
import GaugeTile from "./GaugeTile";

const STATE_META = {
  NORMAL: {
    label: "SYSTEM NORMAL",
    subtext: "No signs of fire or gas buildup",
    color: "#10B981",
    Icon: ShieldCheck,
  },
  PRECURSOR: {
    label: "GAS ANOMALY DETECTED",
    subtext: "Elevated readings — monitoring closely",
    color: "#F59E0B",
    Icon: AlertTriangle,
  },
  CONFIRMING: {
    label: "CONFIRMING FIRE SIGNATURE",
    subtext: "Sustained evidence — gathering visual confirmation",
    color: "#F97316",
    Icon: AlertTriangle,
  },
  FIRE_CONFIRMED: {
    label: "FIRE CONFIRMED",
    subtext: "Immediate attention required",
    color: "#EF4444",
    Icon: Flame,
  },
};

const CLASSIFICATION_META = {
  NO_FLAME: { label: "No Fire", subtext: "Scene is safe", color: "#10B981" },
  CONTROLLED_FLAME: { label: "Controlled Flame", subtext: "Contained source detected", color: "#F59E0B" },
  HAZARDOUS_FIRE: { label: "Hazardous Fire", subtext: "Uncontrolled — act now", color: "#EF4444" },
  PENDING_MODEL: { label: "Not yet classified", subtext: "Vision model pending training", color: "#8B96A8" },
};

export default function RiskScorePanel({ state = "NORMAL", riskScore = 0, classification = "PENDING_MODEL" }) {
  const stateMeta = STATE_META[state] || STATE_META.NORMAL;
  const StateIcon = stateMeta.Icon;
  const classMeta = CLASSIFICATION_META[classification] || CLASSIFICATION_META.PENDING_MODEL;

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      {/* System state */}
      <div className="rounded-xl border border-border bg-surface p-5 flex items-center gap-4">
        <div
          className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full"
          style={{ backgroundColor: `${stateMeta.color}22` }}
        >
          <StateIcon size={28} color={stateMeta.color} />
        </div>
        <div>
          <p className="text-lg font-semibold" style={{ color: stateMeta.color }}>{stateMeta.label}</p>
          <p className="text-sm text-textMuted">{stateMeta.subtext}</p>
        </div>
      </div>

      {/* Risk score gauge */}
      <GaugeTile
        label="Fire Risk Score"
        value={riskScore}
        min={0}
        max={100}
        unit="/ 100"
        decimals={0}
        zones={[
          { upTo: 0.3, color: "#10B981" },
          { upTo: 0.55, color: "#F59E0B" },
          { upTo: 0.75, color: "#F97316" },
          { upTo: 1, color: "#EF4444" },
        ]}
      />

      {/* Vision classification */}
      <div className="rounded-xl border border-border bg-surface p-5 flex items-center gap-4">
        <div
          className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full"
          style={{ backgroundColor: `${classMeta.color}22` }}
        >
          <HelpCircle size={28} color={classMeta.color} />
        </div>
        <div>
          <p className="text-sm text-textMuted mb-0.5">Current Classification</p>
          <p className="text-lg font-semibold" style={{ color: classMeta.color }}>{classMeta.label}</p>
          <p className="text-xs text-textMuted">{classMeta.subtext}</p>
        </div>
      </div>
    </div>
  );
}
