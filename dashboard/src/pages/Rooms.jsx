import React from "react";
import RoomProfile from "../components/RoomProfile";

export default function Rooms() {
  return (
    <div className="p-6 space-y-6 max-w-[1400px] mx-auto">
      <div>
        <h1 className="text-2xl font-semibold">Rooms</h1>
        <p className="text-textMuted text-sm">Manage rooms and the equipment declared in each</p>
      </div>
      <RoomProfile />
    </div>
  );
}
