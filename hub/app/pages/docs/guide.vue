<script setup lang="ts">
import GuidePage from "@/components/GuidePage.vue";
import { USER_GUIDE, USER_SECTIONS } from "@/docs/userGuide";
import { useSession } from "@/stores/session";

const session = useSession();
</script>

<template>
  <GuidePage :guide="USER_GUIDE" :sections="USER_SECTIONS" markdown-name="MCP_HUB_USER_GUIDE.md">
    <template #footer>
      <section class="card mb-6 p-6">
        <h2 class="card-title">Start now</h2>
        <p class="card-description mt-1.5">Connect an app, or see exactly what an AI client gets from the apps you already have.</p>
        <div class="mt-4 flex flex-wrap gap-2">
          <RouterLink v-if="session.canWrite" to="/apps/new" class="btn-primary"><AppIcon name="plus" :size="16" /> Connect app</RouterLink>
          <RouterLink to="/tools?tab=agent" class="btn-secondary">What the agent sees</RouterLink>
          <RouterLink to="/docs/laravel" class="btn-ghost"><AppIcon name="code" :size="16" /> Laravel guide</RouterLink>
        </div>
      </section>
    </template>
    <template #aside>
      <div class="card mt-6 p-4">
        <p class="text-sm font-medium">Building the app side?</p>
        <p class="mt-1 text-xs text-subtle">The Laravel guide has every file your app needs, as a starter kit.</p>
        <RouterLink to="/docs/laravel" class="btn-secondary btn-sm mt-3 w-full">Laravel guide</RouterLink>
      </div>
    </template>
  </GuidePage>
</template>
