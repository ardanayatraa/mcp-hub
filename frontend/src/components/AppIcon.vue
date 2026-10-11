<script setup lang="ts">
// Small outline icon set (24px grid, stroke-based) so the UI needs no icon dependency.
const props = withDefaults(defineProps<{ name: string; size?: number }>(), { size: 18 });

const PATHS: Record<string, string> = {
  home: "M3 10.5 12 3l9 7.5M5 9v12h5v-6h4v6h5V9",
  apps: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
  tools: "M14.5 3.5a5 5 0 0 0-6 6.4L3 15.4V21h5.6l5.5-5.5a5 5 0 0 0 6.4-6l-3 3-3.3-.7-.7-3.3z",
  key: "M14 10a4 4 0 1 0-3.6-2.3L3 15v3h3v-2h2v-2h2l1.4-1.4A4 4 0 0 0 14 10zM16 6h.01",
  activity: "M3 12h4l3-8 4 16 3-8h4",
  settings: "M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1M15 4v4M9 10v4M17 16v4",
  plus: "M12 5v14M5 12h14",
  check: "M5 12.5l4.5 4.5L19 7.5",
  x: "M6 6l12 12M18 6 6 18",
  alert: "M12 4 2.5 20h19L12 4zM12 10v4.5M12 17.5h.01",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v5.5M12 7.5h.01",
  copy: "M8 8h11v12H8zM5 16H4V4h11v1",
  play: "M8 5.5v13l10.5-6.5z",
  refresh: "M20 11a8 8 0 0 0-14.6-4.5M4 4v3.5h3.5M4 13a8 8 0 0 0 14.6 4.5M20 20v-3.5h-3.5",
  trash: "M4 7h16M10 11v6M14 11v6M9 7V4h6v3M6 7l1 13h10l1-13",
  pencil: "M4 20h4L19.5 8.5l-4-4L4 16zM13.5 6.5l4 4",
  "chevron-right": "M9 6l6 6-6 6",
  "chevron-left": "M15 6l-6 6 6 6",
  "chevron-down": "M6 9l6 6 6-6",
  database: "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
  chart: "M4 20V11M10 20V5M16 20v-6M3 20h18",
  table: "M3 5h18v14H3zM3 10h18M3 15h18M9 10v9",
  logout: "M15 4h4v16h-4M10 8l-4 4 4 4M6 12h11",
  menu: "M4 6h16M4 12h16M4 18h16",
  lock: "M6 11h12v9H6zM8.5 11V8a3.5 3.5 0 0 1 7 0v3",
  pause: "M9 5v14M15 5v14",
  archive: "M3 4h18v4H3zM5 8v12h14V8M10 12h4",
  shield: "M12 3l8 3v6c0 4.6-3.4 8-8 9-4.6-1-8-4.4-8-9V6z",
  sparkles: "M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8zM19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z",
  external: "M14 4h6v6M20 4l-9 9M18 14v6H4V6h6",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM20 20l-4-4",
  eye: "M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  "eye-off": "M3 3l18 18M10.6 10.6a2 2 0 0 0 2.8 2.8M9.5 5.8A9.6 9.6 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a17 17 0 0 1-3 3.8M6.5 6.6C3.9 8.4 2.5 12 2.5 12S6 18.5 12 18.5a9 9 0 0 0 4.3-1.1",
  users: "M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM2 21v-1a6 6 0 0 1 12 0v1M16 3.5a4 4 0 0 1 0 7.5M22 21v-1a6 6 0 0 0-4-5.6",
  download: "M12 4v11M7 10l5 5 5-5M4 20h16",
  upload: "M12 20V9M7 14l5-5 5 5M4 4h16",
  plug: "M9 3v5M15 3v5M6 8h12v3a6 6 0 0 1-12 0zM12 17v4",
  bolt: "M13 2 4 14h7l-1 8 9-12h-7z",
  "panel-left": "M4 4h16v16H4zM9.5 4v16",
  book: "M5 5.5A2.5 2.5 0 0 1 7.5 3H19v14H7.5A2.5 2.5 0 0 0 5 19.5zM5 19.5A2.5 2.5 0 0 0 7.5 22H19v-5",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7.5V12l3 2",
  code: "M8.5 7 3.5 12l5 5M15.5 7l5 5-5 5M13.5 4.5l-3 15",
  file: "M14 3H6v18h12V7zM14 3v4h4M9 13h6M9 17h6",
  terminal: "M4 6l6 6-6 6M12 19h8",
  "chevrons-up-down": "M8 9l4-4 4 4M8 15l4 4 4-4",
  layers: "M12 3 2.5 8 12 13l9.5-5zM2.5 12 12 17l9.5-5M2.5 16 12 21l9.5-5",
  chat: "M4 5h16v11H9l-5 4zM8 9.5h8M8 12.5h5",
  send: "M4 12 20 4l-4 16-4-7zM12 13l8-9",
  power: "M12 3v8M7 6.3a7 7 0 1 0 10 0",
};

const d = () => PATHS[props.name] ?? PATHS.info;
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"
       stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class="shrink-0">
    <path :d="d()" />
  </svg>
</template>
