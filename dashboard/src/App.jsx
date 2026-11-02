import React from "react";
import { Routes, Route, NavLink } from "react-router-dom";
import { Flame, LayoutDashboard, DoorOpen, Bell, ClipboardList, BarChart3, Cpu, FileText, Settings } from "lucide-react";

import Dashboard from "./pages/Dashboard";
import Rooms from "./pages/Rooms";
import Alerts from "./pages/Alerts";
import Incidents from "./pages/Incidents";
import Analytics from "./pages/Analytics";
import AIML from "./pages/AIML";
import Reports from "./pages/Reports";
import System from "./pages/System";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/rooms", label: "Rooms", icon: DoorOpen },
  { to: "/alerts", label: "Alerts", icon: Bell },
  { to: "/incidents", label: "Incidents", icon: ClipboardList },
  { to: "/analytics", label: "Analytics", icon: BarChart3 },
  { to: "/ai-ml", label: "AI / ML", icon: Cpu },
  { to: "/reports", label: "Reports", icon: FileText },
  { to: "/system", label: "System", icon: Settings },
];

export default function App() {
  return (
    <div className="flex min-h-screen bg-base">
      <aside className="w-60 shrink-0 border-r border-border bg-surface flex flex-col">
        <div className="flex items-center gap-2 px-5 py-5 border-b border-border">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-danger/20">
            <Flame size={20} className="text-danger" />
          </div>
          <div>
            <p className="font-semibold leading-tight">Fire Sentinel</p>
            <p className="text-xs text-textMuted leading-tight">Smart Fire Detection</p>
          </div>
        </div>

        <nav className="flex-1 px-3 py-4 space-y-1">
          {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
                  isActive ? "bg-info/15 text-info" : "text-textMuted hover:bg-base hover:text-textPrimary"
                }`
              }
            >
              <Icon size={18} />
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>

      <main className="flex-1 overflow-y-auto">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/rooms" element={<Rooms />} />
          <Route path="/alerts" element={<Alerts />} />
          <Route path="/incidents" element={<Incidents />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/ai-ml" element={<AIML />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/system" element={<System />} />
        </Routes>
      </main>
    </div>
  );
}
