<script setup lang="ts">
import { ref } from "vue";

// Password field with a show/hide toggle. Other attributes (id, placeholder, minlength, ...) go to the input.
defineOptions({ inheritAttrs: false });
const model = defineModel<string>({ required: true });
const shown = ref(false);
</script>

<template>
  <div class="relative min-w-0" :class="$attrs.class">
    <input v-bind="{ ...$attrs, class: undefined }" v-model="model" class="input pr-10 font-mono placeholder:font-sans" :type="shown ? 'text' : 'password'"
           autocomplete="new-password" spellcheck="false" />
    <button type="button" class="absolute inset-y-0 right-0 grid w-9 place-items-center rounded-r-lg text-subtle hover:text-ink"
            :aria-label="shown ? 'Hide value' : 'Show value'" :aria-pressed="shown" @click="shown = !shown">
      <AppIcon :name="shown ? 'eye-off' : 'eye'" :size="16" />
    </button>
  </div>
</template>
