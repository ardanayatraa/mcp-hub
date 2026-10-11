<script setup lang="ts">
// How a request travels: AI client -> Hub -> connected app. Theme tokens keep it legible in light and dark mode.
const ink = "rgb(var(--ink))";
const quiet = "rgb(var(--subtle))";
const edge = "rgb(var(--subtle))";
const accent = "rgb(var(--brand))";
const W = 180;
const y0 = 56;
const H = 160;
const lineY = 136;
const left = 16;
const hub = 290;
const app = 564;
</script>

<template>
  <figure class="card mt-5 overflow-hidden p-4">
    <!-- Scrolls sideways on phones rather than shrinking the words below a readable size. -->
    <div class="overflow-x-auto">
    <svg viewBox="0 0 760 236" role="img" aria-label="Every AI request passes the Hub's checks before your app sees it" class="h-auto w-full min-w-[600px]" font-size="13">
      <defs>
        <marker id="flow-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M0 0L10 5L0 10z" :fill="edge" />
        </marker>
      </defs>
      <text x="16" y="28" font-size="15" font-weight="600" :fill="ink">Every AI request passes the Hub's checks before your app sees it</text>

      <g fill="none" :stroke="edge" stroke-width="1.25">
        <path :d="`M${left + W} ${lineY}H${hub}`" marker-start="url(#flow-arrow)" marker-end="url(#flow-arrow)" />
        <path :d="`M${hub + W} ${lineY}H${app}`" marker-start="url(#flow-arrow)" marker-end="url(#flow-arrow)" />
      </g>
      <text :x="(left + W + hub) / 2" :y="lineY - 10" text-anchor="middle" font-size="11.5" :fill="quiet">MCP call + key</text>
      <text :x="(left + W + hub) / 2" :y="lineY + 20" text-anchor="middle" font-size="11.5" :fill="quiet">+ user token</text>
      <text :x="(hub + W + app) / 2" :y="lineY - 10" text-anchor="middle" font-size="11.5" :fill="quiet">reviewed route</text>
      <text :x="(hub + W + app) / 2" :y="lineY + 20" text-anchor="middle" font-size="11.5" :fill="quiet">+ API key</text>

      <g>
        <rect :x="left" :y="y0" :width="W" :height="H" rx="8" fill="none" :stroke="edge" stroke-width="1.25" />
        <text :x="left + 16" :y="y0 + 28" font-size="15" font-weight="600" :fill="ink">AI clients</text>
        <text :x="left + 16" :y="y0 + 56" :fill="quiet">Claude, Cursor or</text>
        <text :x="left + 16" :y="y0 + 76" :fill="quiet">your app's assistant</text>
        <text :x="left + 16" :y="y0 + 96" :fill="quiet">ask in plain words</text>
      </g>
      <g>
        <rect :x="hub" :y="y0" :width="W" :height="H" rx="8" :fill="accent" fill-opacity="0.06" :stroke="accent" stroke-width="2" />
        <text :x="hub + 16" :y="y0 + 28" font-size="15" font-weight="600" :fill="ink">MCP Hub</text>
        <text :x="hub + 16" :y="y0 + 56" :fill="ink">checks the client key</text>
        <text :x="hub + 16" :y="y0 + 76" :fill="ink">tools, skills, memory</text>
        <text :x="hub + 16" :y="y0 + 96" :fill="ink">hides private fields</text>
        <text :x="hub + 16" :y="y0 + 116" :fill="ink">logs every call</text>
      </g>
      <g>
        <rect :x="app" :y="y0" :width="W" :height="H" rx="8" fill="none" :stroke="edge" stroke-width="1.25" />
        <text :x="app + 16" :y="y0 + 28" font-size="15" font-weight="600" :fill="ink">Your app</text>
        <text :x="app + 16" :y="y0 + 56" :fill="quiet">checks its API key</text>
        <text :x="app + 16" :y="y0 + 76" :fill="quiet">re-checks the user</text>
        <text :x="app + 16" :y="y0 + 96" :fill="quiet">keeps all its data</text>
      </g>
    </svg>
    </div>
    <figcaption v-if="$slots.default" class="mt-2 px-1 text-sm text-subtle"><slot /></figcaption>
  </figure>
</template>
