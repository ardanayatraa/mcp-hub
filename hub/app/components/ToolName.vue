<script setup lang="ts">
import { computed } from "vue";

import type { ToolCard } from "@/services/hub";
import { kindStyle } from "@/utils/toolKinds";

// A tool as people read it: an icon for what it does, its name, and where it lives. The raw key stays available.
const props = withDefaults(defineProps<{ card?: ToolCard | null; fallback?: string | null; size?: "sm" | "md"; showKey?: boolean }>(),
  { card: null, fallback: null, size: "md", showKey: false });
const style = computed(() => kindStyle(props.card?.kind));
const where = computed(() => props.card
  ? (props.card.app_name ? [props.card.app_name, props.card.module_name].filter(Boolean).join(" · ") : style.value.label)
  : "");
const link = computed(() => props.card?.tool_id ? `/tools/${props.card.tool_id}` : null);
</script>

<template>
  <component :is="link ? 'RouterLink' : 'span'" :to="link ?? undefined"
             class="group inline-flex min-w-0 max-w-full items-center gap-2.5 text-left" :title="card?.mcp_name ?? fallback ?? ''">
    <span class="grid shrink-0 place-items-center rounded-md" :class="[style.tile, size === 'sm' ? 'h-6 w-6' : 'h-8 w-8']">
      <AppIcon :name="card ? style.icon : 'tools'" :size="size === 'sm' ? 13 : 15" />
    </span>
    <span class="min-w-0">
      <span class="block truncate font-medium text-ink" :class="[size === 'sm' ? 'text-xs' : 'text-sm', link ? 'group-hover:underline' : '']">
        {{ card?.title ?? fallback ?? "Unknown tool" }}</span>
      <span v-if="where || showKey || !card" class="block truncate text-xs text-subtle">
        <template v-if="where">{{ where }}</template>
        <template v-if="(showKey || !card) && (card?.mcp_name || fallback)"><template v-if="where"> · </template>
          <span class="font-mono">{{ card?.mcp_name ?? fallback }}</span></template>
      </span>
    </span>
  </component>
</template>
