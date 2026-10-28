<template>
  <div class="obs-dt">
    <el-collapse v-if="normalizedRounds.length" v-model="activeNames">
      <el-collapse-item
        v-for="round in normalizedRounds"
        :key="round.round"
        :name="String(round.round)"
      >
        <template #title>
          <span class="obs-dt-round-title">
            第 {{ round.round }} 轮
            <el-tag size="small" type="primary" style="margin-left: 8px">
              {{ round.phases.length }} 个阶段
            </el-tag>
          </span>
        </template>

        <div v-for="phase in round.phases" :key="phase.phase_name" class="obs-dt-phase">
          <div class="obs-dt-phase-header">
            <el-tag type="primary" effect="plain" size="small">{{ phase.phase_name }}</el-tag>
            <span v-if="phase.duration" class="obs-dt-phase-duration">
              ⏱ {{ phase.duration }}
            </span>
          </div>
          <el-timeline>
            <el-timeline-item
              v-for="(evt, idx) in phase.events"
              :key="idx"
              :timestamp="evt.time"
              placement="top"
            >
              {{ evt.desc || evt.text }}
            </el-timeline-item>
          </el-timeline>
        </div>
      </el-collapse-item>
    </el-collapse>

    <div v-else class="obs-dt-empty">
      暂无决策流程数据，请点击一键复测
    </div>
  </div>
</template>

<script lang="ts">
/**
 * DecisionTimeline — 决策时间轴（折叠面板 + 时间线）
 *
 * 兼容两种数据格式：
 * - 新格式: [{round, phases: [{phase_name, duration, events: [{time, desc}]}]}]
 * - 旧格式: [{round, stages: [{stage, duration, events: [{time, text}]}]}]
 */
export default {
  props: {
    rounds: { type: Array as () => any[], default: () => [] },
  },
  data() {
    return {
      activeNames: ['1'] as string[],
    }
  },
  computed: {
    normalizedRounds(): any[] {
      const raw = (this.rounds || []).filter(Boolean)
      if (!raw.length) return []
      return raw.map(r => {
        // 兼容: 新格式用 phases，旧格式用 stages
        const phases = (r.phases || r.stages || []).map((p: any) => ({
          phase_name: p.phase_name || p.stage || '',
          duration: p.duration || '',
          events: (p.events || []).map((e: any) => ({
            time: e.time || '',
            desc: e.desc || e.text || '',
          })),
        }))
        return {
          round: r.round || 1,
          phases,
        }
      })
    },
  },
}
</script>

<style scoped>
.obs-dt { }
.obs-dt-round-title { font-weight: 600; font-size: 14px; }
.obs-dt-phase { margin-bottom: 18px; }
.obs-dt-phase:last-child { margin-bottom: 0; }
.obs-dt-phase-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  padding-bottom: 6px;
  border-bottom: 1px dashed #ebeef5;
}
.obs-dt-phase-duration {
  font-size: 12px;
  color: #909399;
  font-family: 'Menlo', 'Consolas', monospace;
}
.obs-dt-empty {
  color: #909399;
  font-size: 13px;
  padding: 20px 0;
  text-align: center;
}
</style>
