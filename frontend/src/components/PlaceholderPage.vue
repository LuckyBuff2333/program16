<template>
  <section class="module-placeholder">
    <div class="placeholder-mark">{{ mark }}</div>
    <el-tag type="info" effect="plain">待接入</el-tag>
    <h2>{{ title }}</h2>
    <p>{{ description }}</p>
    <div class="placeholder-scope">
      <span v-for="tag in tags" :key="tag">{{ tag }}</span>
    </div>
  </section>
</template>

<script lang="ts">
export default {
  name: 'PlaceholderPage',
  props: {
    mark: { type: String, required: true },
    title: { type: String, required: true },
    description: { type: String, required: true },
    tags: { type: Array as () => string[], default: () => [] },
  },
};
</script>
