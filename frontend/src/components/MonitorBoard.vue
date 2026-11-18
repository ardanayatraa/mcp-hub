<script setup lang="ts">
// The live map, as a canvas: AI clients, the Hub with its four checks, and apps and models. Boxes can be
// dragged into place (remembered in this browser), the canvas pans and zooms, and Tidy puts everything back.
// Each new request travels the pipes as a drop of water; a check that refuses it closes its gate.
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from "vue";
import { useRouter } from "vue-router";

import type { GateKey, MonitorEvent, MonitorState, MonitoringBoard } from "@/services/hub";
import { clip, curvePath, route, textWidth, type Point, type Route, type Segment } from "@/utils/flow";
import { timeAgo } from "@/utils/format";
import { GATE_ORDER, GATES, STATE_LABEL, WINDOW_TEXT, stateText } from "@/utils/monitoring";

const props = defineProps<{ board: MonitoringBoard }>();
const router = useRouter();

// World layout, in canvas units. The automatic arrangement; saved positions override it per box.
const W = 1100;
const NODE_W = 228;
const NODE_H = 64;
const GAP = 12;
const HEAD = 30;
const PAD = 14;
const LEFT_X = 12;
const RIGHT_X = W - 12 - NODE_W;
const HUB_X0 = LEFT_X + NODE_W + 72;
const HUB_W = RIGHT_X - 72 - HUB_X0;
const GATE_OFF: Record<GateKey, number> = { key: 64, privacy: 156, permissions: 248, limits: 340 };
const BRANCH_OFF = HUB_W - 80;
const HUB_TOP = 148;
const HUB_H = 272;
const HUB_MIN = 300;
const MAX_CLIENTS = 10;
const MAX_APPS = 8;
const MAX_MODELS = 4;
const SNAP = 8;
const ZOOM_MIN = 0.25;
const ZOOM_MAX = 2.5;
const STORE = "hub_monitor_layout_v1";
// Animation: drops travel at an even speed; arrivals flash for a moment.
const SPEED = 0.5;
const FLASH_MS = 1400;
const BURST_MS = 700;

const C = {
  ink: "rgb(var(--ink))", subtle: "rgb(var(--subtle))", line: "rgb(var(--line))", surface: "rgb(var(--surface))",
  muted: "rgb(var(--muted))", water: "rgb(var(--chart-1))", ok: "rgb(var(--ok))", okSoft: "rgb(var(--ok-soft))",
  warn: "rgb(var(--warn))", warnSoft: "rgb(var(--warn-soft))", bad: "rgb(var(--bad))",
};
type Tone = "ok" | "warn" | "bad";
const TONE: Record<Tone, string> = { ok: C.ok, warn: C.warn, bad: C.bad };

interface BoardNode {
  id: string;
  kind: "client" | "app" | "model" | "more" | "empty";
  group: "clients" | "apps" | "models";
  x: number;
  y: number;
  title: string;
  sub: string;
  line: string;
  icon: string;
  state: MonitorState | null;
  reason: string | null;
  requests: number;
  to: string | null;
  detail: string[];
  side: "left" | "right";
}
interface Pipe { id: string; d: string; flow: "live" | "used" | "idle" | "off"; speed: number }

const windowText = computed(() => WINDOW_TEXT[props.board.window] ?? "this window");
const sentence = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);
const asOf = computed(() => Date.parse(props.board.as_of));
const isRecent = (iso: string | null) => !!iso && asOf.value - Date.parse(iso) <= props.board.live_seconds * 1000;
const plural = (count: number, word: string) => `${count.toLocaleString()} ${word}${count === 1 ? "" : "s"}`;
const speedFor = (requests: number) => (requests >= 20 ? 0.6 : requests >= 5 ? 0.9 : 1.3);
const flowFor = (state: MonitorState | null, requests: number): Pipe["flow"] =>
  state === "off" ? "off" : state === "live" ? "live" : requests > 0 ? "used" : "idle";

function fold<T extends { state: MonitorState }>(items: T[], max: number): { shown: T[]; rest: T[] } {
  // Ready parts first, switched-off ones last; otherwise keep the server's order so boxes do not jump around.
  const sorted = [...items.filter((item) => item.state !== "off"), ...items.filter((item) => item.state === "off")];
  if (sorted.length <= max) return { shown: sorted, rest: [] };
  return { shown: sorted.slice(0, max - 1), rest: sorted.slice(max - 1) };
}

function restState(rest: { state: MonitorState }[]): MonitorState {
  return rest.some((item) => item.state === "live") ? "live" : rest.some((item) => item.state !== "off") ? "on" : "off";
}

/** The automatic arrangement: clients left, the Hub centred, apps and models right. */
const auto = computed(() => {
  const board = props.board;
  const clients = fold(board.clients, MAX_CLIENTS);
  const apps = fold(board.apps, MAX_APPS);
  const models = fold(board.models, MAX_MODELS);
  const leftRows = Math.max(1, clients.shown.length + (clients.rest.length ? 1 : 0));
  const appRows = Math.max(1, apps.shown.length + (apps.rest.length ? 1 : 0));
  const modelRows = models.shown.length + (models.rest.length ? 1 : 0);
  const block = (rows: number) => HEAD + rows * (NODE_H + GAP) - GAP;
  const leftH = block(leftRows);
  const rightH = block(appRows) + (modelRows ? GAP + block(modelRows) : 0);
  const contentH = Math.max(leftH, rightH, HUB_MIN);
  const trunkY = PAD + contentH / 2;
  const leftTop = PAD + (contentH - leftH) / 2;
  const rightTop = PAD + (contentH - rightH) / 2;
  const modelsTop = rightTop + block(appRows) + GAP;
  const row = (top: number, index: number) => top + HEAD + index * (NODE_H + GAP);

  const nodes: BoardNode[] = [];
  const members: Record<string, string> = {};

  clients.shown.forEach((client, index) => {
    const write = client.can_write ? "read + write" : "read only";
    nodes.push({
      id: `client:${client.id}`, kind: "client", group: "clients", x: LEFT_X, y: row(leftTop, index), title: client.name,
      icon: client.kind === "preview" ? "users" : "key",
      sub: client.kind === "key" ? `${client.app_name} · ${write}` : client.kind === "preview" ? "An admin trying the chat" : "Requests without a valid key",
      line: client.requests ? `${plural(client.requests, "request")} · ${client.blocked} stopped`
        : client.last_used_at ? `No requests · used ${timeAgo(client.last_used_at)}` : "Never used yet",
      state: client.state, reason: client.reason, requests: client.requests,
      to: client.kind === "key" && client.app ? `/apps/${client.app}?tab=keys` : client.kind === "preview" ? "/activity" : null,
      side: "left",
      detail: [client.app_name ? `App: ${client.app_name}` : "", client.kind === "key" ? (client.can_write ? "Can read and write" : "Read only") : "",
               client.profile ? `Access profile: ${client.profile}` : "",
               `${sentence(windowText.value)}: ${plural(client.requests, "request")}, ${client.blocked} stopped, ${client.failed} failed`,
               client.kind === "key" ? `Last used ${timeAgo(client.last_used_at)}` : ""].filter(Boolean),
    });
    members[`client:${client.id}`] = `client:${client.id}`;
  });
  if (clients.rest.length) {
    const rest = clients.rest;
    const requests = rest.reduce((sum, item) => sum + item.requests, 0);
    nodes.push({
      id: "client:more", kind: "more", group: "clients", x: LEFT_X, y: row(leftTop, clients.shown.length), title: `+${rest.length} more clients`,
      icon: "layers", sub: (["live", "on", "off"] as MonitorState[]).map((state) => `${rest.filter((item) => item.state === state).length} ${STATE_LABEL[state].toLowerCase()}`).join(" · "),
      line: plural(requests, "request"), state: restState(rest), reason: null, requests, to: "/access", side: "left",
      detail: rest.slice(0, 8).map((item) => `${item.name}: ${STATE_LABEL[item.state]}`),
    });
    rest.forEach((item) => { members[`client:${item.id}`] = "client:more"; });
  }
  if (!board.clients.length) {
    nodes.push({ id: "client:empty", kind: "empty", group: "clients", x: LEFT_X, y: row(leftTop, 0), title: "No client keys yet", icon: "key",
                 sub: "Create one under Access", line: "AI clients appear here", state: null, reason: null, requests: 0,
                 to: "/access", side: "left", detail: ["Each client key is one AI client on this board."] });
  }

  apps.shown.forEach((app, index) => {
    const latency = app.health?.latency_ms != null ? ` · ${app.health.latency_ms} ms` : "";
    nodes.push({
      id: `app:${app.id}`, kind: "app", group: "apps", x: RIGHT_X, y: row(rightTop, index), title: app.name, icon: "apps",
      sub: `${app.environment} · ${plural(app.tools, "tool")} · ${plural(app.sources, "source")}`,
      line: `${plural(app.requests, "request")}${app.failed ? ` · ${app.failed} failed` : ""}${latency}`,
      state: app.state, reason: app.reason, requests: app.requests, to: `/apps/${app.id}`, side: "right",
      detail: [`${app.app_key} · ${app.environment}`,
               app.health ? `Health check: ${app.health.status}${latency} · ${timeAgo(app.health.checked_at)}` : "Not checked yet",
               `${plural(app.tools, "live tool")} · ${plural(app.sources, "data source")} on`, app.chat ? "Chat is on" : "Chat is off",
               `${sentence(windowText.value)}: ${plural(app.requests, "request")}, ${app.failed} failed`],
    });
    members[`app:${app.id}`] = `app:${app.id}`;
  });
  if (apps.rest.length) {
    const rest = apps.rest;
    const requests = rest.reduce((sum, item) => sum + item.requests, 0);
    nodes.push({
      id: "app:more", kind: "more", group: "apps", x: RIGHT_X, y: row(rightTop, apps.shown.length), title: `+${rest.length} more apps`, icon: "layers",
      sub: `${rest.filter((item) => item.state !== "off").length} on · ${rest.filter((item) => item.state === "off").length} off`,
      line: plural(requests, "request"), state: restState(rest), reason: null, requests, to: "/apps", side: "right",
      detail: rest.slice(0, 8).map((item) => `${item.name}: ${STATE_LABEL[item.state]}`),
    });
    rest.forEach((item) => { members[`app:${item.id}`] = "app:more"; });
  }
  if (!board.apps.length) {
    nodes.push({ id: "app:empty", kind: "empty", group: "apps", x: RIGHT_X, y: row(rightTop, 0), title: "No apps connected", icon: "apps",
                 sub: "Connect one under Apps", line: "Requests go to your apps", state: null, reason: null, requests: 0,
                 to: "/apps/new", side: "right", detail: ["A connected app keeps its data and checks every user again."] });
  }

  models.shown.forEach((model, index) => {
    nodes.push({
      id: `model:${model.key}`, kind: "model", group: "models", x: RIGHT_X, y: row(modelsTop, index), title: model.name, icon: "sparkles",
      sub: "AI model for chat answers", line: `${plural(model.requests, "request")}${model.failed ? ` · ${model.failed} failed` : ""}`,
      state: model.state, reason: model.reason, requests: model.requests, to: "/providers", side: "right",
      detail: [`Provider key: ${model.key}`, `${sentence(windowText.value)}: ${plural(model.requests, "request")}, ${model.failed} failed`],
    });
    members[`model:${model.key}`] = `model:${model.key}`;
  });
  if (models.rest.length) {
    const rest = models.rest;
    const requests = rest.reduce((sum, item) => sum + item.requests, 0);
    nodes.push({
      id: "model:more", kind: "more", group: "models", x: RIGHT_X, y: row(modelsTop, models.shown.length), title: `+${rest.length} more models`,
      icon: "layers", sub: "AI model providers", line: plural(requests, "request"), state: restState(rest), reason: null, requests,
      to: "/providers", side: "right", detail: rest.map((item) => `${item.name}: ${STATE_LABEL[item.state]}`),
    });
    rest.forEach((item) => { members[`model:${item.key}`] = "model:more"; });
  }
  return { nodes, members, hub: { x: HUB_X0, y: trunkY } };
});

// --- Saved positions (per browser) ------------------------------------------------------------------

function readSaved(): Record<string, Point> {
  try {
    const value = JSON.parse(localStorage.getItem(STORE) ?? "{}");
    return value && typeof value === "object" ? value : {};
  } catch { return {}; }
}
const saved = ref<Record<string, Point>>(readSaved());
function persist() {
  try { localStorage.setItem(STORE, JSON.stringify(saved.value)); } catch { /* not remembered in this browser */ }
}
const at = (id: string, fallback: Point): Point => {
  const point = saved.value[id];
  return point && Number.isFinite(point.x) && Number.isFinite(point.y) ? point : fallback;
};

/** The arrangement on screen: the automatic one with every moved box where it was dropped. */
const layout = computed(() => {
  const board = props.board;
  const nodes = auto.value.nodes.map((node) => ({ ...node, ...at(node.id, { x: node.x, y: node.y }) }));
  const byId = Object.fromEntries(nodes.map((node) => [node.id, node]));
  const hubPos = at("hub", auto.value.hub);
  const hub = { x0: hubPos.x, x1: hubPos.x + HUB_W, y: hubPos.y };
  const gates = Object.fromEntries(GATE_ORDER.map((gate) => [gate, hub.x0 + GATE_OFF[gate]])) as Record<GateKey, number>;
  const branch = hub.x0 + BRANCH_OFF;
  const answer = { x: branch - 75, y: hub.y + 58, w: 150, h: 46 };
  const hubIn: Point = { x: hub.x0, y: hub.y };
  const hubOut: Point = { x: hub.x1, y: hub.y };
  const center = (node: BoardNode) => node.y + NODE_H / 2;

  // A group's header rides above its topmost box, wherever that box was dropped.
  const live = board.clients.filter((item) => item.state === "live").length;
  const on = board.clients.filter((item) => item.state === "on").length;
  const off = board.clients.filter((item) => item.state === "off").length;
  const titles = {
    clients: { text: `AI clients · ${board.clients.length}`, sub: `${live} live · ${on} on · ${off} off` },
    apps: { text: `Connected apps · ${board.apps.length}`, sub: "" },
    models: { text: "AI models", sub: "" },
  };
  const headers = (Object.keys(titles) as (keyof typeof titles)[]).flatMap((group) => {
    const top = nodes.filter((node) => node.group === group).sort((a, b) => a.y - b.y)[0];
    return top ? [{ ...titles[group], x: top.x, y: top.y - HEAD }] : [];
  });

  const pipes: Pipe[] = [];
  for (const node of nodes) {
    if (node.kind === "empty") continue;
    const d = node.side === "left" ? curvePath({ x: node.x + NODE_W, y: center(node) }, hubIn)
      : curvePath(hubOut, { x: node.x, y: center(node) });
    pipes.push({ id: node.id, d, flow: flowFor(node.state, node.requests), speed: speedFor(node.requests) });
  }
  const anyLive = board.clients.some((item) => item.state === "live");
  pipes.push({ id: "trunk", d: `M${hubIn.x} ${hub.y}H${hubOut.x}`, flow: anyLive ? "live" : board.totals.requests ? "used" : "idle",
               speed: speedFor(board.totals.requests) });
  const hubLive = board.events.some((event) => event.destination === "hub" && !event.stopped_at && isRecent(event.at));
  pipes.push({ id: "answer", d: `M${branch} ${hub.y}V${answer.y}`, flow: hubLive ? "live" : board.hub.answered ? "used" : "idle",
               speed: speedFor(board.hub.answered) });

  const xs = [...nodes.flatMap((node) => [node.x, node.x + NODE_W]), hub.x0, hub.x1];
  const ys = [...nodes.flatMap((node) => [node.y - HEAD, node.y + NODE_H]), hub.y - HUB_TOP, hub.y - HUB_TOP + HUB_H];
  const bounds = { x: Math.min(...xs), y: Math.min(...ys), w: Math.max(...xs) - Math.min(...xs), h: Math.max(...ys) - Math.min(...ys) };
  return { nodes, byId, hub, gates, branch, answer, hubIn, hubOut, center, headers, pipes, bounds };
});
const moved = computed(() => Object.keys(saved.value).length > 0);

// --- Pan, zoom and drag ------------------------------------------------------------------------------

const stage = ref<HTMLElement | null>(null);
const shell = ref<HTMLElement | null>(null);
const view = ref({ x: 0, y: 0, k: 1 });
const size = ref({ width: 0, height: 0 });
// Until someone pans, zooms or drags, the board keeps fitting itself to the canvas.
const touched = ref(false);
const fullscreen = ref(false);
let observer: ResizeObserver | undefined;

function fit() {
  const { width, height } = size.value;
  if (!width || !height) return;
  const box = layout.value.bounds;
  const k = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, Math.min((width - 48) / box.w, (height - 72) / box.h, 1.4)));
  view.value = { k, x: (width - box.w * k) / 2 - box.x * k, y: (height - box.h * k) / 2 - box.y * k + 12 };
}
function fitNow() {
  touched.value = false;
  fit();
}
function tidy() {
  saved.value = {};
  persist();
  fitNow();
}
function zoomAt(factor: number, cx = size.value.width / 2, cy = size.value.height / 2) {
  const { x, y, k } = view.value;
  const next = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, k * factor));
  const ratio = next / k;
  view.value = { k: next, x: cx - (cx - x) * ratio, y: cy - (cy - y) * ratio };
  touched.value = true;
  hovered.value = null;
}
function wheel(event: WheelEvent) {
  const rect = stage.value!.getBoundingClientRect();
  zoomAt(Math.exp(-event.deltaY * 0.0015), event.clientX - rect.left, event.clientY - rect.top);
}
// Full screen always covers the window; the browser's own full screen is added when it allows it.
async function toggleFullscreen() {
  const entering = !fullscreen.value;
  fullscreen.value = entering;
  try {
    if (entering && !document.fullscreenElement) await shell.value?.requestFullscreen();
    else if (!entering && document.fullscreenElement) await document.exitFullscreen();
  } catch { /* refused: the canvas still covers the window */ }
}
// Leaving the browser's full screen (Esc) leaves the canvas full screen too.
const onFullscreen = () => { if (!document.fullscreenElement) fullscreen.value = false; };
const onKey = (event: KeyboardEvent) => { if (event.key === "Escape" && fullscreen.value && !document.fullscreenElement) fullscreen.value = false; };

onMounted(() => {
  observer = new ResizeObserver(([entry]) => {
    size.value = { width: entry.contentRect.width, height: entry.contentRect.height };
    if (!touched.value) fit();
  });
  if (stage.value) observer.observe(stage.value);
  document.addEventListener("fullscreenchange", onFullscreen);
  document.addEventListener("keydown", onKey);
});
watch(() => layout.value.bounds, () => { if (!touched.value) fit(); });

interface Gesture { pointer: number; startX: number; startY: number; origin: Point; moved: boolean; id: string | null; node?: BoardNode }
let gesture: Gesture | null = null;
const dragging = ref<string | null>(null);
const panning = ref(false);

function down(event: PointerEvent, id: string | null = null, node?: BoardNode) {
  if (event.button !== 0 || gesture) return;
  const L = layout.value;
  const origin = id === "hub" ? { x: L.hub.x0, y: L.hub.y } : node ? { x: node.x, y: node.y } : { x: view.value.x, y: view.value.y };
  gesture = { pointer: event.pointerId, startX: event.clientX, startY: event.clientY, origin, moved: false, id, node };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
  window.addEventListener("pointercancel", up);
}
function move(event: PointerEvent) {
  if (!gesture || event.pointerId !== gesture.pointer) return;
  const dx = event.clientX - gesture.startX;
  const dy = event.clientY - gesture.startY;
  if (!gesture.moved && Math.hypot(dx, dy) < 4) return;
  if (!gesture.moved) {
    gesture.moved = true;
    hovered.value = null;
    touched.value = true;
    if (gesture.id) dragging.value = gesture.id;
    else panning.value = true;
  }
  if (gesture.id) {
    const k = view.value.k;
    saved.value = { ...saved.value, [gesture.id]: { x: gesture.origin.x + dx / k, y: gesture.origin.y + dy / k } };
  } else {
    view.value = { ...view.value, x: gesture.origin.x + dx, y: gesture.origin.y + dy };
  }
}
function up(event: PointerEvent) {
  if (!gesture || event.pointerId !== gesture.pointer) return;
  const { id, node } = gesture;
  if (gesture.moved && id) {
    // Dropped boxes snap to a small grid, so rows line up without effort.
    const point = saved.value[id];
    saved.value = { ...saved.value, [id]: { x: Math.round(point.x / SNAP) * SNAP, y: Math.round(point.y / SNAP) * SNAP } };
    persist();
  } else if (!gesture.moved && node && event.type === "pointerup") {
    open(node);
  }
  gesture = null;
  dragging.value = null;
  panning.value = false;
  window.removeEventListener("pointermove", move);
  window.removeEventListener("pointerup", up);
  window.removeEventListener("pointercancel", up);
}
function nudge(event: KeyboardEvent, id: string, origin: Point) {
  const step = event.shiftKey ? SNAP * 5 : SNAP;
  const moves: Record<string, [number, number]> = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
  const delta = moves[event.key];
  if (!delta) return;
  event.preventDefault();
  saved.value = { ...saved.value, [id]: { x: origin.x + delta[0], y: origin.y + delta[1] } };
  touched.value = true;
  persist();
}

onBeforeUnmount(() => {
  observer?.disconnect();
  document.removeEventListener("fullscreenchange", onFullscreen);
  document.removeEventListener("keydown", onKey);
  window.removeEventListener("pointermove", move);
  window.removeEventListener("pointerup", up);
  window.removeEventListener("pointercancel", up);
});

// --- Requests in motion ----------------------------------------------------------------------------

interface Particle { id: string; path: Route; start: number; duration: number; end: Tone; gate?: GateKey; target?: string }
interface Burst { id: string; at: Point; start: number; tone: Tone }
const particles = shallowRef<Particle[]>([]);
const bursts = shallowRef<Burst[]>([]);
const gateFlash = ref<Partial<Record<GateKey, number>>>({});
const nodeFlash = ref<Record<string, { at: number; tone: Tone }>>({});
const now = ref(performance.now());
const reduced = typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
let frame = 0;
let timers: ReturnType<typeof setTimeout>[] = [];

function plan(event: MonitorEvent): Omit<Particle, "id" | "start" | "duration"> | null {
  const L = layout.value;
  const from = L.byId[auto.value.members[`client:${event.client}`] ?? ""];
  if (!from) return null;
  const segments: Segment[] = [{ kind: "curve", a: { x: from.x + NODE_W, y: L.center(from) }, b: L.hubIn }];
  const stop = event.stopped_at;
  if (stop === "key" || stop === "privacy" || stop === "permissions" || stop === "limits") {
    segments.push({ kind: "line", a: L.hubIn, b: { x: L.gates[stop] - 7, y: L.hub.y } });
    return { path: route(segments), end: "bad", gate: stop };
  }
  if (event.destination === "hub" || stop === "hub") {
    const branch = { x: L.branch, y: L.hub.y };
    segments.push({ kind: "line", a: L.hubIn, b: branch });
    if (stop === "hub") return { path: route(segments), end: "warn", target: "hub" };
    segments.push({ kind: "line", a: branch, b: { x: L.branch, y: L.answer.y } });
    return { path: route(segments), end: "ok", target: "hub" };
  }
  const key = event.destination === "app" ? `app:${event.app ?? ""}` : `model:${event.model ?? ""}`;
  const target = L.byId[auto.value.members[key] ?? ""];
  segments.push({ kind: "line", a: L.hubIn, b: L.hubOut });
  if (target) segments.push({ kind: "curve", a: L.hubOut, b: { x: target.x, y: L.center(target) } });
  return { path: route(segments), end: stop ? "warn" : "ok", target: target?.id };
}

function arrive(item: Omit<Particle, "id" | "start" | "duration">, time: number) {
  if (item.gate) gateFlash.value = { ...gateFlash.value, [item.gate]: time };
  if (item.target) nodeFlash.value = { ...nodeFlash.value, [item.target]: { at: time, tone: item.end } };
  if (!reduced) bursts.value = [...bursts.value, { id: `${time}-${Math.random()}`, at: item.path.at(1), start: time, tone: item.end }];
}

function tick(time: number) {
  now.value = time;
  const done = particles.value.filter((item) => time >= item.start + item.duration);
  if (done.length) {
    done.forEach((item) => arrive(item, time));
    particles.value = particles.value.filter((item) => time < item.start + item.duration);
  }
  if (bursts.value.some((item) => time - item.start >= BURST_MS)) {
    bursts.value = bursts.value.filter((item) => time - item.start < BURST_MS);
  }
  const flashing = Object.values(gateFlash.value).some((stamp) => stamp !== undefined && time - stamp < FLASH_MS)
    || Object.values(nodeFlash.value).some((flash) => time - flash.at < FLASH_MS);
  frame = particles.value.length || bursts.value.length || flashing ? requestAnimationFrame(tick) : 0;
}
function run() {
  if (!frame) frame = requestAnimationFrame(tick);
}

function launch(event: MonitorEvent, delay: number) {
  const item = plan(event);
  if (!item) return;
  if (reduced) {
    // No moving drops: the gate or the destination simply lights up when the request lands.
    timers.push(setTimeout(() => { arrive(item, performance.now()); run(); }, delay));
    return;
  }
  const duration = Math.min(2600, Math.max(1200, item.path.length / SPEED));
  particles.value = [...particles.value, { ...item, id: event.id, start: performance.now() + delay, duration }];
  run();
}

// Only requests newer than anything already shown are animated, so changing the window never replays history.
let mark = 0;
let seen = new Set<string>();
watch(() => props.board, (board) => {
  const times = board.events.map((event) => Date.parse(event.at));
  if (!mark) mark = Date.parse(board.as_of) - 20_000;
  const fresh = board.events.filter((event, index) => times[index] >= mark && !seen.has(event.id))
    .sort((a, b) => Date.parse(a.at) - Date.parse(b.at)).slice(-16);
  mark = Math.max(mark, ...times);
  seen = new Set(board.events.filter((_event, index) => times[index] >= mark - 5000).map((event) => event.id));
  const spacing = fresh.length > 1 ? Math.min(450, 3200 / fresh.length) : 0;
  fresh.forEach((event, index) => launch(event, index * spacing));
}, { immediate: true });

onBeforeUnmount(() => {
  if (frame) cancelAnimationFrame(frame);
  timers.forEach(clearTimeout);
  timers = [];
});

function drop(item: Particle, lag = 0): Point | null {
  const progress = (now.value - item.start) / item.duration - lag;
  return progress < 0 ? null : item.path.at(progress);
}
function fade(stamp: number | undefined): number {
  if (stamp === undefined) return 0;
  const age = now.value - stamp;
  return age < 0 || age >= FLASH_MS ? 0 : 1 - age / FLASH_MS;
}

// --- Look and details ---------------------------------------------------------------------------------

const hovered = ref<{ node?: BoardNode; gate?: GateKey } | null>(null);
const gateStats = computed(() => Object.fromEntries(props.board.gates.map((gate) => [gate.key, gate])) as
  Record<GateKey, MonitoringBoard["gates"][number]>);

function badge(state: MonitorState) {
  const text = STATE_LABEL[state];
  const width = textWidth(text, 11) + 24;
  const fill = { live: C.okSoft, on: C.muted, off: C.muted, warn: C.warnSoft }[state];
  const ink = { live: C.ok, on: C.ink, off: C.subtle, warn: C.warn }[state];
  const dot = { live: C.ok, on: C.ok, off: "none", warn: C.warn }[state];
  return { text, width, fill, ink, dot };
}
function titleRoom(node: BoardNode) {
  const room = NODE_W - 36 - (node.state ? badge(node.state).width + 10 : 0) - 10;
  return Math.max(6, Math.floor(room / (13 * 0.58)));
}
const LINE_CHARS = Math.floor((NODE_W - 36 - 10) / (11 * 0.56));
function nodeStroke(node: BoardNode) {
  if (dragging.value === node.id || hovered.value?.node?.id === node.id) return C.ink;
  if (node.state === "warn") return C.warn;
  if (node.state === "live") return C.ok;
  return C.line;
}
function open(node: BoardNode) {
  if (node.to) void router.push(node.to);
}
function label(node: BoardNode) {
  return [node.title, node.state ? stateText(node.state, node.reason) : "", node.sub, node.line,
          "Arrow keys move it, Enter opens it"].filter(Boolean).join(". ");
}

const tooltip = computed(() => {
  const target = hovered.value;
  if (!target || dragging.value || panning.value) return null;
  const L = layout.value;
  const { x: vx, y: vy, k } = view.value;
  const screen = (x: number, y: number) => ({ x: x * k + vx, y: y * k + vy });
  const place = (point: Point, align: "left" | "right" | "center", above: boolean) => ({
    left: `${point.x}px`, top: `${point.y}px`,
    transform: `translate(${{ left: "0", right: "-100%", center: "-50%" }[align]}, ${above ? "-100%" : "0"})`,
  });
  if (target.gate) {
    const gate = gateStats.value[target.gate];
    const codes = gate?.codes.slice(0, 4).map((item) => `${item.code}: ${item.count}`) ?? [];
    return { style: place(screen(L.gates[target.gate], L.hub.y + 34), "center", false), title: `${GATES[target.gate].name} check`,
             state: `${gate?.stopped ?? 0} stopped in the ${windowText.value}`, lines: [GATES[target.gate].help, ...codes] };
  }
  const node = L.byId[target.node!.id] ?? target.node!;
  const top = screen(node.x, node.y);
  const bottom = screen(node.x, node.y + NODE_H);
  const right = screen(node.x + NODE_W, node.y).x;
  const above = (top.y + bottom.y) / 2 > size.value.height / 2;
  const alignRight = right > size.value.width * 0.6;
  const anchor = { x: alignRight ? right : top.x, y: above ? top.y - 8 : bottom.y + 8 };
  return { style: place(anchor, alignRight ? "right" : "left", above), title: node.title,
           state: node.state ? stateText(node.state, node.reason) : "",
           lines: [...node.detail, node.to ? "Drag to move · click to open" : "Drag to move"] };
});

const summary = computed(() => {
  const totals = props.board.totals;
  return `${props.board.clients.length} AI clients and ${props.board.apps.length} connected apps. In the ${windowText.value}: `
    + `${totals.requests} requests, ${totals.passed} passed, ${totals.blocked} stopped by a check, ${totals.failed} failed.`;
});
const hubHot = computed(() => dragging.value === "hub");
</script>

<template>
  <div ref="shell" class="bg-surface" :class="fullscreen ? 'fixed inset-0 z-50' : 'relative'">
    <div ref="stage" class="relative h-[calc(100dvh-12.5rem)] min-h-[440px] touch-none overflow-hidden"
         :class="[fullscreen ? '!h-full' : '', panning ? 'cursor-grabbing' : 'cursor-grab']" @mouseleave="hovered = null">
      <svg class="block h-full w-full select-none" role="group" :aria-label="summary" font-size="12"
           @pointerdown="down($event)" @wheel.prevent="wheel">
        <defs>
          <pattern id="monitor-grid" width="24" height="24" patternUnits="userSpaceOnUse">
            <circle cx="1" cy="1" r="1.1" :fill="C.line" />
          </pattern>
        </defs>
        <g :transform="`translate(${view.x} ${view.y}) scale(${view.k})`">
          <rect x="-20000" y="-20000" width="40000" height="40000" fill="url(#monitor-grid)" />

          <!-- The Hub: its frame goes under the pipes, its checks over them. Drag either part to move it. -->
          <g :transform="`translate(${layout.hub.x0} ${layout.hub.y})`" class="cursor-move" @pointerdown.stop="down($event, 'hub')">
            <rect :y="-HUB_TOP" :width="HUB_W" :height="HUB_H" rx="16" :fill="C.muted" fill-opacity="0.55"
                  :stroke="hubHot ? C.ink : C.line" :stroke-width="hubHot ? 2 : 1" />
            <text x="18" :y="-HUB_TOP + 28" font-size="15" font-weight="600" :fill="C.ink">MCP Hub</text>
            <text x="18" :y="-HUB_TOP + 46" font-size="11.5" :fill="C.subtle">Checks every request, then sends it on</text>
            <g transform="translate(18 72)" font-size="11" :fill="C.subtle">
              <circle cx="5" cy="-4" r="4.5" :fill="C.water" :stroke="C.surface" stroke-width="1.5" />
              <text x="16" y="0">A request on its way</text>
              <rect x="1" y="11" width="8" height="14" rx="2" :fill="C.bad" />
              <text x="16" y="22">A check refused it</text>
            </g>
          </g>

          <!-- Pipes: a wide channel, with water moving in it while there is traffic. -->
          <g fill="none" stroke-linecap="round" pointer-events="none">
            <path v-for="pipe in layout.pipes" :key="`base-${pipe.id}`" :d="pipe.d" :stroke="C.line" stroke-width="8"
                  :opacity="pipe.flow === 'off' ? 0.5 : 1" />
            <template v-for="pipe in layout.pipes" :key="`water-${pipe.id}`">
              <path v-if="pipe.flow === 'live'" :d="pipe.d" :stroke="C.water" stroke-width="3" class="monitor-flow"
                    :style="{ '--flow-speed': `${pipe.speed}s` }" />
              <path v-else-if="pipe.flow === 'used'" :d="pipe.d" :stroke="C.water" stroke-width="3" opacity="0.35" />
            </template>
          </g>

          <g :transform="`translate(${layout.hub.x0} ${layout.hub.y})`" class="cursor-move" @pointerdown.stop="down($event, 'hub')">
            <g v-for="gate in GATE_ORDER" :key="gate" :transform="`translate(${GATE_OFF[gate]} 0)`" tabindex="0" class="outline-none"
               :aria-label="`${GATES[gate].name} check: ${gateStats[gate]?.stopped ?? 0} stopped. ${GATES[gate].help}`"
               @mouseenter="hovered = { gate }" @focus="hovered = { gate }" @blur="hovered = null">
              <rect x="-44" y="-96" width="88" height="128" rx="10" fill="transparent" :stroke="hovered?.gate === gate ? C.ink : 'none'" stroke-width="1.5" />
              <g transform="translate(-8 -86)" :style="{ color: hovered?.gate === gate ? C.ink : C.subtle }">
                <AppIcon :name="GATES[gate].icon" :size="16" />
              </g>
              <text y="-52" text-anchor="middle" font-size="11.5" font-weight="600" :fill="C.ink">{{ GATES[gate].name }}</text>
              <text y="-37" text-anchor="middle" font-size="11" :fill="C.subtle">{{ (gateStats[gate]?.stopped ?? 0).toLocaleString() }} stopped</text>
              <circle v-if="gateStats[gate]?.stopped" :cx="-textWidth(`${gateStats[gate].stopped} stopped`, 11) / 2 - 7" cy="-41" r="3" :fill="C.bad" />
              <rect x="-6" y="-26" width="12" height="16" rx="3" :fill="hovered?.gate === gate ? C.ink : C.subtle" />
              <rect x="-6" y="10" width="12" height="16" rx="3" :fill="hovered?.gate === gate ? C.ink : C.subtle" />
              <rect v-if="fade(gateFlash[gate])" x="-6" y="-11" width="12" height="22" rx="2" :fill="C.bad" :opacity="fade(gateFlash[gate])" />
            </g>
            <!-- Requests the Hub answers itself: the data source list, memory and skills. -->
            <g :transform="`translate(${BRANCH_OFF - 75} 58)`">
              <rect :width="layout.answer.w" :height="layout.answer.h" rx="10" :fill="C.surface" :stroke="C.line" />
              <rect v-if="fade(nodeFlash.hub?.at)" x="-3" y="-3" :width="layout.answer.w + 6" :height="layout.answer.h + 6" rx="13" fill="none"
                    :stroke="TONE[nodeFlash.hub?.tone ?? 'ok']" stroke-width="2" :opacity="fade(nodeFlash.hub?.at)" />
              <text x="12" y="19" font-size="11.5" font-weight="600" :fill="C.ink">Answered in the Hub</text>
              <text x="12" y="35" font-size="10.5" :fill="C.subtle">{{ plural(board.hub.answered, "request") }} · lists, memory</text>
            </g>
          </g>

          <!-- Group headers ride above each group's topmost box. -->
          <g v-for="header in layout.headers" :key="header.text" :transform="`translate(${header.x} ${header.y})`" pointer-events="none">
            <text x="2" y="18" font-size="12.5" font-weight="600" :fill="C.ink">{{ header.text }}</text>
            <text v-if="header.sub" :x="NODE_W - 2" y="18" text-anchor="end" font-size="10.5" :fill="C.subtle">{{ header.sub }}</text>
          </g>

          <!-- Clients, apps and models: drag to move, click to open. -->
          <g v-for="node in layout.nodes" :key="node.id" :transform="`translate(${node.x} ${node.y})`" class="outline-none"
             :class="dragging === node.id ? 'cursor-grabbing' : 'cursor-pointer'" tabindex="0" :role="node.to ? 'link' : 'img'"
             :aria-label="label(node)" @pointerdown.stop="down($event, node.id, node)" @mouseenter="hovered = { node }"
             @focus="hovered = { node }" @blur="hovered = null" @keydown.enter.prevent="open(node)"
             @keydown="nudge($event, node.id, { x: node.x, y: node.y })">
            <rect v-if="dragging === node.id" x="4" y="6" :width="NODE_W" :height="NODE_H" rx="10" :fill="C.ink" opacity="0.12" />
            <rect :width="NODE_W" :height="NODE_H" rx="10" :fill="C.surface" :stroke="nodeStroke(node)"
                  :stroke-width="dragging === node.id || hovered?.node?.id === node.id ? 2 : 1.25"
                  :stroke-dasharray="node.kind === 'empty' ? '5 4' : undefined" />
            <rect v-if="fade(nodeFlash[node.id]?.at)" x="-3" y="-3" :width="NODE_W + 6" :height="NODE_H + 6" rx="13" fill="none"
                  :stroke="TONE[nodeFlash[node.id]?.tone ?? 'ok']" stroke-width="2" :opacity="fade(nodeFlash[node.id]?.at)" />
            <g transform="translate(12 10)" :style="{ color: node.state === 'off' ? C.subtle : C.ink }" :opacity="node.state === 'off' ? 0.7 : 1">
              <AppIcon :name="node.icon" :size="16" />
            </g>
            <text x="36" y="23" font-size="13" font-weight="600" :fill="node.state === 'off' ? C.subtle : C.ink">
              {{ clip(node.title, titleRoom(node)) }}<title>{{ node.title }}</title>
            </text>
            <text x="36" y="40" font-size="11" :fill="C.subtle">{{ clip(node.sub, LINE_CHARS) }}</text>
            <text x="36" y="55" font-size="11" :fill="C.subtle">{{ clip(node.line, LINE_CHARS) }}</text>
            <g v-if="node.state" :transform="`translate(${NODE_W - 10 - badge(node.state).width} 9)`">
              <rect :width="badge(node.state).width" height="18" rx="9" :fill="badge(node.state).fill" />
              <circle v-if="node.state === 'live'" cx="10" cy="9" r="3.5" :fill="C.ok" class="monitor-pulse" />
              <circle cx="10" cy="9" r="3.5" :fill="badge(node.state).dot" :stroke="node.state === 'off' ? C.subtle : 'none'" stroke-width="1.25" />
              <text x="18" y="12.5" font-size="11" font-weight="500" :fill="badge(node.state).ink">{{ badge(node.state).text }}</text>
            </g>
          </g>

          <!-- Arrivals ripple; drops carry a short tail. -->
          <g pointer-events="none">
            <circle v-for="burst in bursts" :key="burst.id" :cx="burst.at.x" :cy="burst.at.y" :r="5 + 18 * Math.min(1, (now - burst.start) / BURST_MS)"
                    fill="none" :stroke="TONE[burst.tone]" stroke-width="2" :opacity="Math.max(0, 1 - (now - burst.start) / BURST_MS)" />
            <template v-for="item in particles" :key="item.id">
              <template v-if="drop(item)">
                <circle v-if="drop(item, 0.05)" :cx="drop(item, 0.05)!.x" :cy="drop(item, 0.05)!.y" r="2.5" :fill="C.water" opacity="0.3" />
                <circle v-if="drop(item, 0.025)" :cx="drop(item, 0.025)!.x" :cy="drop(item, 0.025)!.y" r="3.5" :fill="C.water" opacity="0.55" />
                <circle :cx="drop(item)!.x" :cy="drop(item)!.y" r="5.5" :fill="C.water" :stroke="C.surface" stroke-width="2" />
              </template>
            </template>
          </g>
        </g>
      </svg>

      <!-- Canvas controls. -->
      <div class="absolute right-3 top-3 flex items-center gap-1 rounded-lg border border-line bg-surface/95 p-1 shadow-card backdrop-blur"
           role="toolbar" aria-label="Canvas" @pointerdown.stop>
        <button type="button" class="btn-ghost btn-icon h-8 w-8" title="Zoom out" aria-label="Zoom out" @click="zoomAt(1 / 1.2)">
          <AppIcon name="minus" :size="16" /></button>
        <button type="button" class="h-8 min-w-[3.25rem] rounded-md px-1 text-xs font-medium tabular-nums text-subtle hover:bg-muted hover:text-ink"
                title="Fit to screen" @click="fitNow">{{ Math.round(view.k * 100) }}%</button>
        <button type="button" class="btn-ghost btn-icon h-8 w-8" title="Zoom in" aria-label="Zoom in" @click="zoomAt(1.2)">
          <AppIcon name="plus" :size="16" /></button>
        <span class="mx-0.5 h-5 w-px bg-line" aria-hidden="true" />
        <button type="button" class="btn-ghost btn-icon h-8 w-8" title="Fit to screen" aria-label="Fit to screen" @click="fitNow">
          <AppIcon name="fit" :size="16" /></button>
        <button type="button" class="btn-ghost btn-sm h-8 gap-1.5 px-2" :disabled="!moved" title="Put every box back in place" @click="tidy">
          <AppIcon name="tidy" :size="15" /><span class="hidden sm:inline">Tidy up</span></button>
        <button type="button" class="btn-ghost btn-icon h-8 w-8" :title="fullscreen ? 'Exit full screen' : 'Full screen'"
                :aria-label="fullscreen ? 'Exit full screen' : 'Full screen'" @click="toggleFullscreen">
          <AppIcon :name="fullscreen ? 'minimize' : 'maximize'" :size="16" /></button>
      </div>
      <slot name="corner" />
    </div>

    <div v-if="tooltip" class="pointer-events-none absolute z-20 w-64 rounded-lg border border-line bg-surface p-3 text-xs shadow-pop"
         :style="tooltip.style" role="tooltip">
      <p class="text-sm font-semibold text-ink">{{ tooltip.title }}</p>
      <p v-if="tooltip.state" class="mt-0.5 text-subtle">{{ tooltip.state }}</p>
      <ul class="mt-2 space-y-1 text-ink">
        <li v-for="line in tooltip.lines" :key="line">{{ line }}</li>
      </ul>
    </div>
  </div>
</template>
