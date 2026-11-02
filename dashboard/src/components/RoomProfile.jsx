import React, { useEffect, useState } from "react";
import { Plus, Trash2, Zap, Flame as FlameIcon } from "lucide-react";
import { getRooms, createRoom, deleteRoom, getAppliances, addAppliance, deleteAppliance } from "../api/client";

export default function RoomProfile() {
  const [rooms, setRooms] = useState([]);
  const [selectedRoom, setSelectedRoom] = useState(null);
  const [appliances, setAppliances] = useState([]);
  const [newRoomName, setNewRoomName] = useState("");
  const [newAppliance, setNewAppliance] = useState({ name: "", category: "electrical", notes: "" });

  const refreshRooms = () => getRooms().then(setRooms).catch(() => setRooms([]));

  useEffect(() => {
    refreshRooms();
  }, []);

  useEffect(() => {
    if (selectedRoom) {
      getAppliances(selectedRoom.id).then(setAppliances).catch(() => setAppliances([]));
    } else {
      setAppliances([]);
    }
  }, [selectedRoom]);

  const handleCreateRoom = async (e) => {
    e.preventDefault();
    if (!newRoomName.trim()) return;
    await createRoom(newRoomName.trim());
    setNewRoomName("");
    refreshRooms();
  };

  const handleDeleteRoom = async (roomId) => {
    await deleteRoom(roomId);
    if (selectedRoom?.id === roomId) setSelectedRoom(null);
    refreshRooms();
  };

  const handleAddAppliance = async (e) => {
    e.preventDefault();
    if (!newAppliance.name.trim() || !selectedRoom) return;
    await addAppliance(selectedRoom.id, newAppliance);
    setNewAppliance({ name: "", category: "electrical", notes: "" });
    getAppliances(selectedRoom.id).then(setAppliances);
  };

  const handleDeleteAppliance = async (id) => {
    await deleteAppliance(id);
    getAppliances(selectedRoom.id).then(setAppliances);
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      {/* Room list */}
      <div className="rounded-xl border border-border bg-surface p-4">
        <h3 className="font-medium mb-3">Rooms</h3>
        <form onSubmit={handleCreateRoom} className="flex gap-2 mb-3">
          <input
            value={newRoomName}
            onChange={(e) => setNewRoomName(e.target.value)}
            placeholder="e.g. Kitchen"
            className="flex-1 rounded-lg bg-base border border-border text-sm px-2 py-1.5"
          />
          <button type="submit" className="rounded-lg bg-info px-2.5 text-white">
            <Plus size={16} />
          </button>
        </form>
        <div className="space-y-1">
          {rooms.map((r) => (
            <div
              key={r.id}
              onClick={() => setSelectedRoom(r)}
              className={`flex items-center justify-between rounded-lg px-3 py-2 text-sm cursor-pointer transition-colors ${
                selectedRoom?.id === r.id ? "bg-info/20 text-info" : "hover:bg-base"
              }`}
            >
              {r.name}
              <button
                onClick={(e) => { e.stopPropagation(); handleDeleteRoom(r.id); }}
                className="text-textMuted hover:text-danger"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
          {rooms.length === 0 && <p className="text-sm text-textMuted">No rooms yet.</p>}
        </div>
      </div>

      {/* Appliances for selected room */}
      <div className="md:col-span-2 rounded-xl border border-border bg-surface p-4">
        {!selectedRoom ? (
          <p className="text-sm text-textMuted">Select a room to manage its declared equipment.</p>
        ) : (
          <>
            <h3 className="font-medium mb-1">{selectedRoom.name} — Equipment</h3>
            <p className="text-sm text-textMuted mb-3">
              Declaring gas or heavy electrical equipment here gives the risk model a little extra context
              and shows up as a possible contributing factor in incident reports — it never changes the
              detection logic on its own.
            </p>

            <form onSubmit={handleAddAppliance} className="flex flex-wrap gap-2 mb-4">
              <input
                value={newAppliance.name}
                onChange={(e) => setNewAppliance({ ...newAppliance, name: e.target.value })}
                placeholder="e.g. LPG stove"
                className="flex-1 min-w-[140px] rounded-lg bg-base border border-border text-sm px-2 py-1.5"
              />
              <select
                value={newAppliance.category}
                onChange={(e) => setNewAppliance({ ...newAppliance, category: e.target.value })}
                className="rounded-lg bg-base border border-border text-sm px-2 py-1.5"
              >
                <option value="electrical">Electrical</option>
                <option value="gas">Gas</option>
              </select>
              <button type="submit" className="rounded-lg bg-info px-3 py-1.5 text-sm text-white">Add</button>
            </form>

            <div className="space-y-2">
              {appliances.map((a) => (
                <div key={a.id} className="flex items-center justify-between rounded-lg bg-base border border-border px-3 py-2">
                  <div className="flex items-center gap-3">
                    {a.category === "gas" ? (
                      <FlameIcon size={16} className="text-warn" />
                    ) : (
                      <Zap size={16} className="text-info" />
                    )}
                    <div>
                      <p className="text-sm">{a.name}</p>
                      {a.notes && <p className="text-xs text-textMuted">{a.notes}</p>}
                    </div>
                  </div>
                  <button onClick={() => handleDeleteAppliance(a.id)} className="text-textMuted hover:text-danger">
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
              {appliances.length === 0 && <p className="text-sm text-textMuted">No equipment declared for this room yet.</p>}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
