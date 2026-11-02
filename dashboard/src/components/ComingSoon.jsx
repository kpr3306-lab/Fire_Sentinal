import React from "react";
import { Construction } from "lucide-react";

export default function ComingSoon({ title, description }) {
  return (
    <div className="p-6 max-w-[1400px] mx-auto">
      <h1 className="text-2xl font-semibold mb-1">{title}</h1>
      <p className="text-textMuted text-sm mb-6">{description}</p>
      <div className="rounded-xl border border-dashed border-border bg-surface p-12 flex flex-col items-center gap-3 text-textMuted">
        <Construction size={28} />
        <p className="text-sm">This page is planned for a later build session.</p>
      </div>
    </div>
  );
}
