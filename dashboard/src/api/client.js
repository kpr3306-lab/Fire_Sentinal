/**
 * api/client.js — Ignis dashboard
 *
 * Thin wrappers around fetch(). Vite's dev proxy (vite.config.js) forwards
 * /api/* to the Flask backend, so these paths work unchanged in dev and
 * production (once served behind the same origin, or with VITE_API_BASE set).
 */

const BASE = import.meta.env.VITE_API_BASE || "";

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.error || detail;
    } catch {
      /* response wasn't JSON, keep statusText */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  const contentType = res.headers.get("content-type") || "";
  if (contentType.includes("application/json")) return res.json();
  return res;
}

// --- Devices ---
export const getDevices = () => request("/api/devices");
export const getDevice = (deviceId) => request(`/api/devices/${deviceId}`);
export const assignRoom = (deviceId, roomId) =>
  request(`/api/devices/${deviceId}/room`, { method: "PUT", body: JSON.stringify({ room_id: roomId }) });
export const setDeviceOverride = (deviceId, { ip, port, use_override }) =>
  request(`/api/devices/${deviceId}/override`, { method: "PUT", body: JSON.stringify({ ip, port, use_override }) });

// --- Sensor data ---
export const getLatestReading = (params) => {
  const qs = new URLSearchParams(params).toString();
  return request(`/api/sensor-data/latest?${qs}`);
};
export const getReadingHistory = (deviceId, limit = 50) =>
  request(`/api/sensor-data/history?device_id=${deviceId}&limit=${limit}`);

// --- Camera / snapshots ---
export const captureProxyUrl = (deviceId) => `${BASE}/api/camera/capture-proxy?device_id=${deviceId}`;
export const getSnapshots = (params, limit = 50) => {
  const qs = new URLSearchParams({ ...params, limit }).toString();
  return request(`/api/camera/snapshots?${qs}`);
};
export const snapshotFileUrl = (snapshotId) => `${BASE}/api/camera/snapshots/${snapshotId}/file`;

// --- Events ---
export const getEvents = (params, limit = 50) => {
  const qs = new URLSearchParams({ ...params, limit }).toString();
  return request(`/api/events?${qs}`);
};
export const getRecentEvents = (limit = 10) => request(`/api/events/recent?limit=${limit}`);

// --- Profile: rooms, appliances, contacts ---
export const getRooms = () => request("/api/rooms");
export const createRoom = (name) => request("/api/rooms", { method: "POST", body: JSON.stringify({ name }) });
export const deleteRoom = (roomId) => request(`/api/rooms/${roomId}`, { method: "DELETE" });

export const getAppliances = (roomId) => request(`/api/rooms/${roomId}/appliances`);
export const addAppliance = (roomId, appliance) =>
  request(`/api/rooms/${roomId}/appliances`, { method: "POST", body: JSON.stringify(appliance) });
export const deleteAppliance = (applianceId) => request(`/api/appliances/${applianceId}`, { method: "DELETE" });

export const getContacts = () => request("/api/contacts");
export const addContact = (contact) => request("/api/contacts", { method: "POST", body: JSON.stringify(contact) });
export const deleteContact = (contactId) => request(`/api/contacts/${contactId}`, { method: "DELETE" });

// --- Alerts / model ---
export const getAlertHistory = (limit = 50) => request(`/api/alerts/history?limit=${limit}`);
export const testAlert = (channel) => request("/api/alerts/test", { method: "POST", body: JSON.stringify({ channel }) });
export const getModelInfo = () => request("/api/model-info");
