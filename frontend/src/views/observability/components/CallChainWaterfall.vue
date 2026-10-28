<template>
  <div class="ccw">
    <div class="ccw-header">
      <span class="ccw-title">调用链详情</span>
    </div>

    <!-- 时间轴刻度 -->
    <div class="ccw-timeline-axis" v-if="treeRows.length">
      <div class="ccw-label-spacer"></div>
      <div class="ccw-axis-track">
        <div
          v-for="(tick, idx) in axisTicks"
          :key="idx"
          class="ccw-axis-tick"
          :style="{ left: tick.pct + '%' }"
        >
          <span class="ccw-axis-label">{{ tick.label }}</span>
        </div>
      </div>
      <div class="ccw-status-spacer"></div>
    </div>

    <!-- 树形行列表 -->
    <div class="ccw-body" v-if="treeRows.length">
      <div v-for="(row, idx) in treeRows" :key="idx" class="ccw-row" :class="{ 'ccw-row-root': row.depth === 0, 'ccw-row-event': row.isEvent }">
        <!-- 左侧：树形标签 -->
        <div class="ccw-label-cell" :style="{ paddingLeft: (row.depth * 20 + 8) + 'px' }">
          <!-- 展开/折叠箭头 -->
          <span
            v-if="row.hasChildren"
            class="ccw-arrow"
            :class="{ 'ccw-arrow-open': row.expanded }"
            @click="toggleRow(row.id)"
          >▸</span>
          <span v-else class="ccw-arrow-placeholder"></span>
          <span class="ccw-label-text" :title="row.name">{{ row.name }}</span>
        </div>

        <!-- 中间：时间条 -->
        <div class="ccw-bar-cell" v-if="!row.isEvent">
          <div class="ccw-bar-track">
            <el-tooltip :content="barTooltip(row)" placement="top" :disabled="!row.duration">
              <div
                class="ccw-bar"
                :style="barStyle(row)"
              ></div>
            </el-tooltip>
            <!-- 网格线 -->
            <div
              v-for="(tick, ti) in axisTicks"
              :key="ti"
              class="ccw-grid-line"
              :style="{ left: tick.pct + '%' }"
            ></div>
          </div>
          <span class="ccw-bar-duration" v-if="row.duration">{{ formatDuration(row.duration) }}</span>
        </div>
        <div class="ccw-bar-cell ccw-event-cell" v-else>
          <span class="ccw-event-time">{{ row.time }}</span>
          <span class="ccw-event-desc">{{ row.desc }}</span>
        </div>

        <!-- 右侧：状态 -->
        <div class="ccw-status-cell" v-if="!row.isEvent">
          <span class="ccw-status-dot" :class="row.status === 'error' ? 'ccw-dot-error' : 'ccw-dot-ok'"></span>
        </div>
        <div class="ccw-status-cell" v-else></div>
      </div>
    </div>

    <div v-else class="ccw-empty">暂无调用链数据，请点击一键复测</div>

    <!-- 底部汇总 -->
    <div class="ccw-footer" v-if="treeRows.length">
      <span class="ccw-footer-total">总耗时: {{ formatDuration(totalDuration) }}</span>
      <span class="ccw-footer-ok">成功: {{ successCount }}</span>
      <span class="ccw-footer-err">失败: {{ errorCount }}</span>
    </div>
  </div>
</template>

<script lang="ts">
export default {
  props: {
    phases: { type: Array as () => any[], default: () => [] },
    rounds: { type: Array as () => any[], default: () => [] },
    total: { type: Number, default: 0 },
    status: { type: String, default: '' },
  },
  data() {
    return {
      expandedIds: new Set<string>(['root']),
    }
  },
  computed: {
    totalDuration(): number {
      if (this.total > 0) return this.total
      return (this.phases || []).reduce((s: number, p: any) => s + (p.duration_seconds || 0), 0)
    },
    /** 时间轴刻度 (5~7个) */
    axisTicks(): { pct: number; label: string }[] {
      const total = this.totalDuration
      if (total <= 0) return []
      const count = 6
      const ticks: { pct: number; label: string }[] = []
      for (let i = 0; i <= count; i++) {
        const sec = (total / count) * i
        ticks.push({
          pct: (sec / total) * 100,
          label: this.formatAxisTime(sec),
        })
      }
      return ticks
    },
    /** 构建树形行数据 */
    treeRows(): any[] {
      const phases = (this.phases || []).filter(Boolean)
      if (!phases.length) return []

      const rows: any[] = []
      const isRootExpanded = this.expandedIds.has('root')

      // 根节点
      rows.push({
        id: 'root',
        name: 'AI分析全链路',
        depth: 0,
        duration: this.totalDuration,
        offset: 0,
        status: this.status === '成功' ? 'ok' : (this.status ? 'error' : 'ok'),
        hasChildren: true,
        expanded: isRootExpanded,
        isEvent: false,
        color: '#409eff',
      })

      if (!isRootExpanded) return rows

      // 子节点：4 个阶段
      let cumOffset = 0
      const roundPhases = this.flattenRoundPhases()

      phases.forEach((p: any, idx: number) => {
        const dur = p.duration_seconds || 0
        const phaseId = `phase_${idx}`
        const isPhaseExpanded = this.expandedIds.has(phaseId)
        const events = roundPhases.get(p.phase_name || p.name || '') || []

        rows.push({
          id: phaseId,
          name: p.phase_name || p.name || `阶段${idx + 1}`,
          depth: 1,
          duration: dur,
          offset: cumOffset,
          status: 'ok',
          hasChildren: events.length > 0,
          expanded: isPhaseExpanded,
          isEvent: false,
          color: p.color || this.phaseColor(idx),
          percentage: p.percentage || 0,
        })

        cumOffset += dur

        // 展开的事件行
        if (isPhaseExpanded && events.length) {
          events.forEach((evt: any, ei: number) => {
            rows.push({
              id: `${phaseId}_evt_${ei}`,
              name: evt.desc || evt.text || '',
              depth: 2,
              duration: 0,
              offset: 0,
              time: evt.time || '',
              desc: evt.desc || evt.text || '',
              isEvent: true,
              hasChildren: false,
              expanded: false,
            })
          })
        }
      })

      return rows
    },
    successCount(): number {
      return (this.phases || []).filter((p: any) => p.status !== 'error').length
    },
    errorCount(): number {
      return (this.phases || []).filter((p: any) => p.status === 'error').length
    },
  },
  methods: {
    toggleRow(id: string) {
      if (this.expandedIds.has(id)) {
        this.expandedIds.delete(id)
      } else {
        this.expandedIds.add(id)
      }
      // Force reactivity
      this.expandedIds = new Set(this.expandedIds)
    },
    barStyle(row: any): Record<string, string> {
      const total = this.totalDuration
      if (total <= 0 || !row.duration) return { display: 'none' }
      const leftPct = (row.offset / total) * 100
      const widthPct = Math.max((row.duration / total) * 100, 1.5)
      return {
        left: leftPct + '%',
        width: widthPct + '%',
        backgroundColor: row.color || '#409eff',
      }
    },
    barTooltip(row: any): string {
      if (!row.duration) return row.name
      const pct = row.percentage || ((row.duration / this.totalDuration) * 100).toFixed(1)
      return `${row.name}: ${this.formatDuration(row.duration)} (${pct}%)`
    },
    formatDuration(sec: number): string {
      if (!sec || sec <= 0) return '0s'
      sec = Math.round(sec * 10) / 10
      if (sec >= 3600) {
        const h = Math.floor(sec / 3600)
        const m = Math.floor((sec % 3600) / 60)
        return m > 0 ? `${h}h${m}m` : `${h}h`
      }
      const m = Math.floor(sec / 60)
      const s = Math.round(sec % 60 * 10) / 10
      if (m > 0 && s > 0) return `${m}m${s}s`
      if (m > 0) return `${m}m`
      return `${s}s`
    },
    formatAxisTime(sec: number): string {
      sec = Math.round(sec)
      if (sec >= 3600) {
        const h = (sec / 3600).toFixed(1)
        return `${h}h`
      }
      if (sec >= 60) {
        const m = Math.floor(sec / 60)
        const s = sec % 60
        return s > 0 ? `${m}m${s}s` : `${m}m`
      }
      return `${sec}s`
    },
    phaseColor(idx: number): string {
      const colors = ['#409eff', '#67c23a', '#e6a23c', '#909399']
      return colors[idx % colors.length]
    },
    /** 从 timeline_rounds 提取各阶段的事件列表 */
    flattenRoundPhases(): Map<string, any[]> {
      const map = new Map<string, any[]>()
      const rounds = (this.rounds || []).filter(Boolean)
      rounds.forEach(r => {
        const phases = (r.phases || r.stages || [])
        phases.forEach((p: any) => {
          const name = p.phase_name || p.stage || ''
          const events = (p.events || []).map((e: any) => ({
            time: e.time || '',
            desc: e.desc || e.text || '',
          }))
          if (events.length) {
            const existing = map.get(name) || []
            map.set(name, [...existing, ...events])
          }
        })
      })
      return map
    },
  },
}
</script>

<style scoped>
.ccw {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  overflow: hidden;
  background: #fff;
}

/* Header */
.ccw-header {
  padding: 12px 16px;
  border-bottom: 1px solid #ebeef5;
  background: #fafafa;
}
.ccw-title {
  font-weight: 600;
  font-size: 15px;
  color: #303133;
}

/* Time axis */
.ccw-timeline-axis {
  display: flex;
  align-items: center;
  height: 28px;
  border-bottom: 1px solid #ebeef5;
  background: #fafbfc;
  font-size: 11px;
  color: #909399;
}
.ccw-label-spacer {
  width: 220px;
  min-width: 220px;
  flex-shrink: 0;
  border-right: 1px solid #ebeef5;
}
.ccw-axis-track {
  flex: 1;
  position: relative;
  height: 100%;
  display: flex;
  align-items: flex-end;
}
.ccw-axis-tick {
  position: absolute;
  transform: translateX(-50%);
  bottom: 2px;
}
.ccw-axis-label {
  font-size: 11px;
  color: #909399;
  white-space: nowrap;
}
.ccw-status-spacer {
  width: 40px;
  min-width: 40px;
  flex-shrink: 0;
  border-left: 1px solid #ebeef5;
}

/* Body rows */
.ccw-body {
  max-height: 500px;
  overflow-y: auto;
}
.ccw-row {
  display: flex;
  align-items: center;
  height: 36px;
  border-bottom: 1px solid #f5f5f5;
  transition: background 0.15s;
}
.ccw-row:hover {
  background: #f5f7fa;
}
.ccw-row-root {
  background: #f0f2f5;
  font-weight: 600;
}
.ccw-row-root:hover {
  background: #e8eaed;
}
.ccw-row-event {
  height: 30px;
  background: #fafafa;
}
.ccw-row-event:hover {
  background: #f0f2f5;
}

/* Left label cell */
.ccw-label-cell {
  width: 220px;
  min-width: 220px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 4px;
  overflow: hidden;
  border-right: 1px solid #ebeef5;
  height: 100%;
  padding-right: 8px;
  box-sizing: border-box;
}
.ccw-arrow {
  cursor: pointer;
  font-size: 10px;
  color: #909399;
  transition: transform 0.2s;
  display: inline-block;
  width: 14px;
  text-align: center;
  flex-shrink: 0;
  user-select: none;
}
.ccw-arrow-open {
  transform: rotate(90deg);
}
.ccw-arrow-placeholder {
  width: 14px;
  flex-shrink: 0;
}
.ccw-label-text {
  font-size: 13px;
  color: #303133;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ccw-row-event .ccw-label-text {
  font-size: 12px;
  color: #606266;
}

/* Middle bar cell */
.ccw-bar-cell {
  flex: 1;
  display: flex;
  align-items: center;
  padding: 0 8px;
  height: 100%;
  min-width: 0;
}
.ccw-bar-track {
  flex: 1;
  position: relative;
  height: 18px;
  background: transparent;
}
.ccw-bar {
  position: absolute;
  top: 2px;
  height: 14px;
  border-radius: 3px;
  min-width: 4px;
  cursor: default;
  transition: filter 0.15s;
}
.ccw-bar:hover {
  filter: brightness(0.85);
}
.ccw-bar-duration {
  font-size: 12px;
  color: #606266;
  white-space: nowrap;
  margin-left: 8px;
  flex-shrink: 0;
  font-family: 'Consolas', 'Menlo', monospace;
}
.ccw-grid-line {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 1px;
  background: #f0f0f0;
  pointer-events: none;
}

/* Event cell */
.ccw-event-cell {
  gap: 8px;
}
.ccw-event-time {
  font-size: 11px;
  color: #909399;
  font-family: 'Consolas', 'Menlo', monospace;
  white-space: nowrap;
  flex-shrink: 0;
}
.ccw-event-desc {
  font-size: 12px;
  color: #606266;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Status cell */
.ccw-status-cell {
  width: 40px;
  min-width: 40px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-left: 1px solid #ebeef5;
  height: 100%;
}
.ccw-status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.ccw-dot-ok {
  background: #67c23a;
}
.ccw-dot-error {
  background: #f56c6c;
}

/* Footer */
.ccw-footer {
  display: flex;
  gap: 16px;
  padding: 10px 16px;
  border-top: 1px solid #ebeef5;
  background: #fafbfc;
  font-size: 12px;
}
.ccw-footer-total {
  color: #303133;
  font-weight: 500;
}
.ccw-footer-ok {
  color: #67c23a;
}
.ccw-footer-err {
  color: #f56c6c;
}

/* Empty */
.ccw-empty {
  padding: 40px 0;
  text-align: center;
  color: #909399;
  font-size: 13px;
}
</style>
