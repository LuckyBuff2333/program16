<template>
  <div class="obs-conf-bar">
    <template v-if="conf != null">
      <el-progress
        :percentage="pct"
        :color="barColor"
        :stroke-width="8"
        :format="() => conf.toFixed(2)"
        style="width: 80px"
      />
      <span v-if="converged !== undefined" class="obs-conf-label" :class="converged ? 'is-ok' : 'is-warn'">
        {{ converged ? '已收敛' : '未收敛' }}
      </span>
    </template>
    <span v-else class="obs-conf-label" style="color: #909399">—</span>
  </div>
</template>

<script lang="ts">
export default {
  props: {
    conf: { type: Number, default: null },
    converged: { type: Boolean, default: undefined },
  },
  computed: {
    pct(): number {
      return Math.round(this.conf * 100)
    },
    barColor(): string {
      if (this.pct < 50) return '#f56c6c'
      if (this.pct < 75) return '#e6a23c'
      return '#67c23a'
    },
  },
}
</script>

<style scoped>
.obs-conf-bar { display: flex; align-items: center; gap: 8px; }
.obs-conf-label { font-size: 12px; }
.obs-conf-label.is-ok { color: #67c23a; }
.obs-conf-label.is-warn { color: #e6a23c; }
</style>
