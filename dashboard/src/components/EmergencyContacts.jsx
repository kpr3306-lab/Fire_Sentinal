import React, { useEffect, useState } from "react";
import { Phone, Flame, Shield, HeartPulse, User } from "lucide-react";
import { getContacts } from "../api/client";

const RELATION_ICON = {
  "Fire Department": Flame,
  Police: Shield,
  Ambulance: HeartPulse,
};

export default function EmergencyContacts() {
  const [contacts, setContacts] = useState([]);

  useEffect(() => {
    getContacts()
      .then(setContacts)
      .catch(() => setContacts([]));
  }, []);

  return (
    <div className="rounded-xl border border-danger/40 bg-surface p-4">
      <div className="flex items-center gap-2 mb-3">
        <Phone size={18} className="text-danger" />
        <span className="font-medium">Emergency Contacts</span>
      </div>

      {contacts.length === 0 && (
        <p className="text-sm text-textMuted">
          No contacts added yet — add them from Profile settings.
        </p>
      )}

      <div className="space-y-2">
        {contacts.map((c) => {
          const Icon = RELATION_ICON[c.relation] || User;
          return (
            <div key={c.id} className="flex items-center justify-between rounded-lg bg-base border border-border px-3 py-2">
              <div className="flex items-center gap-3">
                <Icon size={18} className="text-textMuted" />
                <div>
                  <p className="text-sm font-medium">{c.relation || c.name}</p>
                  <p className="text-xs text-textMuted">{c.phone}</p>
                </div>
              </div>
              <a
                href={`tel:${c.phone}`}
                className="rounded-lg bg-safe px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-600 transition-colors"
              >
                Call
              </a>
            </div>
          );
        })}
      </div>
    </div>
  );
}
