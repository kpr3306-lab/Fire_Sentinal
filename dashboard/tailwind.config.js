/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        base: "#0A0F1A",
        surface: "#111827",
        surfaceRaised: "#16213A",
        border: "#1F2A3D",
        textPrimary: "#E5E7EB",
        textMuted: "#8B96A8",
        safe: "#10B981",
        warn: "#F59E0B",
        danger: "#EF4444",
        info: "#3B82F6",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["'IBM Plex Mono'", "monospace"],
      },
    },
  },
  plugins: [],
};
