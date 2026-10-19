<script setup lang="ts">
import GuidePage from "@/components/GuidePage.vue";
import { GUIDE, SECTIONS, kitFiles } from "@/docs/laravelGuide";
import { useSession } from "@/stores/session";

const session = useSession();
const kit = {
  fileName: "mcp-hub-laravel-starter.zip",
  title: "Starter kit",
  description: "Complete files sit at their Laravel paths, snippets/ holds lines you add to existing files, and the guide is included as Markdown.",
  files: kitFiles,
};
</script>

<template>
  <GuidePage :guide="GUIDE" :sections="SECTIONS" markdown-name="MCP_HUB_LARAVEL_GUIDE.md" :kit="kit">
    <template #footer>
      <section class="card mb-6 p-6">
        <h2 class="card-title">Ready to connect?</h2>
        <p class="card-description mt-1.5">Add the app, check the connection, then give your AI client a key.</p>
        <div class="mt-4 flex flex-wrap gap-2">
          <RouterLink v-if="session.canWrite" to="/apps/new" class="btn-primary"><AppIcon name="plus" :size="16" /> Connect app</RouterLink>
          <RouterLink to="/docs/guide" class="btn-secondary">User guide</RouterLink>
          <RouterLink to="/access" class="btn-ghost">Client keys</RouterLink>
        </div>
      </section>
    </template>
  </GuidePage>
</template>
