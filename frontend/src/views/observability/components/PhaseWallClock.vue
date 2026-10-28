<template>
  <div class="obs-pwc">
    <!-- 横向拼接进度条 -->
    <div v-if="normalizedPhases.length" class="obs-phase-bar">
      <div
        v-for="(p, idx) in normalizedPhases"
        :key="idx"
        class="obs-phase-segment"
        :style="{ width: p.width + '%', backgroundColor: p.color }"
      >
        <el-tooltip
          :content="`${p.phase_name}：${formatDuration(p.duration_seconds)}`"
          placement="top"
        >
          <span class="obs-phase-inner">{{ p.width > 8 ? p.phase_name : '' }}</span>
        </el-tooltip>
      </div>
    </div>
    <div v-else class="obs-pwc-empty">暂无阶段数据</div>

    <!-- 图例 -->
    <div v-if="normalizedPhases.length" class="obs-phase-legend">
      <div v-for="(p, idx) in normalizedPhases" :key="idx" class="obs-phase-legend-item">
        <span class="obs-phase-dot" :style="{ backgroundColor: p.color }"></span>
        <span class="obs-legend-name">{{ p.phase_name }}</span>
        <span class="obs-legend-dur">{{ formatDuration(p.duration_seconds) }}</span>
      </div>
    </div>
  </div>
</template>

<script lang="ts">
/**
 * PhaseWallClock — 阶段墙钟（横向拼接进度条）
 *
 * 兼容两种数据格式：
 * - 新格式 (dict 产出): [{phase_name, duration_seconds, percentage, color}]
 * - 旧格式 (list 产出): [{phase_name, duration_seconds, color}]  （无 percentage，自动按秒数比例算）
 */
export default {
  props: {
    phases: { type: Array as () => any[], default: () => [] },
  },
  computed: {
    normalizedPhases(): any[] {
      const list = (this.phases || []).filter(Boolean)
      if (!list.length) return []

      // 如果所有 phase 都有 percentage 且总和 > 0，直接用 percentage
      const totalPct = list.reduce((s, p) => s + (p.percentage || 0), 0)
      if (totalPct > 0) {
        return list.map(p => ({
          ...p,
          phase_name: p.phase_name || p.name || '',
          duration_seconds: p.duration_seconds ?? 0,
          width: p.percentage || 0,
          color: p.color || '#409eff',
        }))
      }

      // 兜底：按 duration_seconds 比例计算宽度
      const totalSec = list.reduce((s, p) => s + (p.duration_seconds || 0), 0)
      if (totalSec <= 0) {
        // 全部等宽
        const eq = 100 / list.length
        return list.map(p => ({
          ...p,
          phase_name: p.phase_name || p.name || '',
          duration_seconds: p.duration_seconds ?? 0,
          width: eq,
          color: p.color || '#409eff',
        }))
      }
      return list.map(p => ({
        ...p,
        phase_name: p.phase_name || p.name || '',
        duration_seconds: p.duration_seconds ?? 0,
        width: ((p.duration_seconds || 0) / totalSec) * 100,
        color: p.color || '#409eff',
      }))
    },
  },
  methods: {
    formatDuration(sec: number): string {
      if (!sec || sec <= 0) return '0s'
      sec = Math.round(sec * 10) / 10  // 修复浮点精度
      const m = Math.floor(sec / 60)
      const s = Math.round(sec % 60 * 10) / 10
      if (m > 0 && s > 0) return `${m}m${s}s`
      if (m > 0) return `${m}m`
      return `${s}s`
    },
  },
}
</script>

<style scoped>
.obs-pwc { }
.obs-phase-bar {
  display: flex;
  border-radius: 6px;
  overflow: hidden;
  height: 34px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}
.obs-phase-segment {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 12px;
  font-weight: 500;
  min-width: 6px;
  transition: filter .2s ease;
  cursor: default;
}
.obs-phase-segment:hover { filter: brightness(0.88); }
.obs-phase-inner {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  padding: 0 6px;
}
.obs-phase-legend {
  display: flex;
  gap: 18px;
  flex-wrap: wrap;
  margin-top: 10px;
}
.obs-phase-legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #606266;
}
.obs-phase-dot {
  display: inline-block;
  width: 12px;
  height: 12px;
  border-radius: 3px;
  flex-shrink: 0;
}
.obs-legend-name { font-weight: 500; }
.obs-legend-dur { color: #909399; }
.obs-pwc-empty {
  color: #909399;
  font-size: 13px;
  padding: 12px 0;
  text-align: center;
}
</style>
