<template>
  <div class="sap">
    <!-- 标题栏 -->
    <div class="sap-header">
      <span class="sap-header-icon">🤖</span>
      <span class="sap-header-title">智能分析</span>
      <el-tag size="small" type="primary" effect="plain" style="margin-left: auto">
        AI Agent
      </el-tag>
    </div>

    <!-- 异常分析 -->
    <div class="sap-section">
      <div class="sap-section-title">
        <span class="sap-section-bar sap-bar-orange"></span>
        异常分析
      </div>
      <div class="sap-section-body" v-if="panel.anomaly_desc">
        <span class="sap-case-ref">{{ caseRefText }}</span>
        {{ panel.anomaly_desc }}
      </div>
      <div class="sap-empty" v-else>暂无异常描述</div>
    </div>

    <!-- 根因分析 -->
    <div class="sap-section">
      <div class="sap-section-title">
        <span class="sap-section-bar sap-bar-blue"></span>
        根因分析
      </div>

      <!-- 问题概述 -->
      <div class="sap-field">
        <div class="sap-field-label">【问题概述】</div>
        <div class="sap-field-value">{{ panel.problem_overview || '暂无数据' }}</div>
      </div>

      <!-- 问题定界 -->
      <div class="sap-field">
        <div class="sap-field-label">【问题定界】</div>
        <div class="sap-field-value">{{ panel.problem_boundary || '暂无定界信息' }}</div>
      </div>

      <!-- 证据链 -->
      <div class="sap-field">
        <div class="sap-field-label">【证据链】</div>
        <div class="sap-field-value" v-if="panel.evidence_chain && panel.evidence_chain.length">
          <div v-for="(ev, idx) in panel.evidence_chain" :key="idx" class="sap-evidence-item">
            <span class="sap-evidence-idx">{{ idx + 1 }}.</span>
            {{ ev }}
          </div>
        </div>
        <div class="sap-field-value" v-else>暂无证据链数据</div>
      </div>

      <!-- 可能原因 -->
      <div class="sap-field">
        <div class="sap-field-label">【可能原因】</div>
        <div class="sap-field-value" v-if="panel.possible_causes && panel.possible_causes.length">
          <div v-for="(cause, idx) in panel.possible_causes" :key="idx" class="sap-cause-item">
            {{ cause }}
          </div>
        </div>
        <div class="sap-field-value" v-else>暂无数据</div>
      </div>

      <!-- 处置建议 -->
      <div class="sap-field">
        <div class="sap-field-label">【处置建议】</div>
        <div class="sap-field-value" v-if="panel.disposition">
          {{ panel.disposition }}
        </div>
        <div class="sap-field-value sap-empty" v-else>暂无处置建议</div>
      </div>
    </div>
  </div>
</template>

<script lang="ts">
interface AnalysisPanel {
  anomaly_desc: string
  problem_overview: string
  problem_boundary: string
  evidence_chain: string[]
  possible_causes: string[]
  disposition: string
}

export default {
  props: {
    detail: { type: Object, default: () => ({}) },
  },
  computed: {
    panel(): AnalysisPanel {
      // 优先使用后端组装的 analysis_panel
      const ap = (this.detail as any).analysis_panel
      if (ap && typeof ap === 'object') {
        return {
          anomaly_desc: ap.anomaly_desc || '',
          problem_overview: ap.problem_overview || '',
          problem_boundary: ap.problem_boundary || '',
          evidence_chain: ap.evidence_chain || [],
          possible_causes: ap.possible_causes || [],
          disposition: ap.disposition || '',
        }
      }
      // 前端回退：从 detail 字段组装
      const d = this.detail as any
      const rootCause = d.root_cause || d.rootcause || ''
      return {
        anomaly_desc: (d.description || rootCause || '').slice(0, 200),
        problem_overview: rootCause,
        problem_boundary: this.inferBoundary(d),
        evidence_chain: this.inferEvidence(d),
        possible_causes: this.inferCauses(d),
        disposition: d.error_type
          ? `建议排查 ${d.error_type} 相关问题`
          : '建议结合日志进一步分析',
      }
    },
    caseRefText(): string {
      const d = this.detail as any
      const caseId = d.case_id || ''
      if (!caseId) return ''
      return `在分析 ${caseId} 时，`
    },
  },
  methods: {
    inferBoundary(d: any): string {
      const parts: string[] = []
      if (d.ai_module) parts.push(`AI识别模块: ${d.ai_module}`)
      if (d.actual_module) parts.push(`实际模块: ${d.actual_module}`)
      if (d.case_type) parts.push(`任务类型: ${d.case_type}`)
      if (parts.length) return parts.join('，')
      // 从 root_cause 中尝试提取模块名
      const rc = d.root_cause || ''
      const moduleMatch = rc.match(/([\w-]+(?:模块|服务|组件|system|service|module))/i)
      if (moduleMatch) return `涉及: ${moduleMatch[1]}`
      return ''
    },
    inferEvidence(d: any): string[] {
      const items: string[] = []
      // 从 timeline_rounds 的事件提取
      const dc = d.decision_chain
      if (dc && typeof dc === 'object') {
        const rounds = dc.timeline_rounds || []
        rounds.forEach((r: any) => {
          (r.phases || r.stages || []).forEach((p: any) => {
            (p.events || []).slice(0, 3).forEach((e: any) => {
              const desc = (e.desc || e.text || '').slice(0, 100)
              if (desc) items.push(desc)
            })
          })
        })
      }
      // 从 hypothesis_table 的 evidence 补充
      const ht = d.hypothesis_table
      if (Array.isArray(ht)) {
        ht.forEach((h: any) => {
          const ev = (h.evidence || '').trim()
          if (ev && ev !== '根因子论点' && ev !== '根因子节点' && !items.includes(ev)) {
            items.push(ev)
          }
        })
      }
      return items.slice(0, 5)
    },
    inferCauses(d: any): string[] {
      const causes: string[] = []
      const ht = d.hypothesis_table
      if (Array.isArray(ht)) {
        ht.forEach((h: any) => {
          if (h.verdict === 'confirmed' && h.hypothesis) {
            causes.push(h.hypothesis)
          }
        })
      }
      if (!causes.length && d.root_cause) {
        causes.push(d.root_cause)
      }
      return causes
    },
  },
}
</script>

<style scoped>
.sap {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  overflow: hidden;
  background: #fff;
}

/* Header */
.sap-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  border-bottom: 1px solid #ebeef5;
  background: #fafafa;
}
.sap-header-icon {
  font-size: 18px;
}
.sap-header-title {
  font-weight: 600;
  font-size: 15px;
  color: #303133;
}

/* Section */
.sap-section {
  padding: 16px;
  border-bottom: 1px solid #f5f5f5;
}
.sap-section:last-child {
  border-bottom: none;
}
.sap-section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 14px;
  color: #303133;
  margin-bottom: 12px;
}
.sap-section-bar {
  display: inline-block;
  width: 4px;
  height: 16px;
  border-radius: 2px;
  flex-shrink: 0;
}
.sap-bar-orange {
  background: #e6a23c;
}
.sap-bar-blue {
  background: #409eff;
}
.sap-section-body {
  font-size: 13px;
  color: #303133;
  line-height: 1.8;
  padding-left: 12px;
}
.sap-case-ref {
  color: #409eff;
  font-weight: 500;
}

/* Fields */
.sap-field {
  margin-bottom: 14px;
  padding-left: 12px;
}
.sap-field:last-child {
  margin-bottom: 0;
}
.sap-field-label {
  font-size: 13px;
  font-weight: 600;
  color: #606266;
  margin-bottom: 4px;
}
.sap-field-value {
  font-size: 13px;
  color: #303133;
  line-height: 1.7;
  word-break: break-word;
}

/* Evidence items */
.sap-evidence-item {
  padding: 2px 0;
  line-height: 1.6;
}
.sap-evidence-idx {
  color: #909399;
  margin-right: 4px;
}

/* Cause items */
.sap-cause-item {
  padding: 4px 0;
  border-left: 3px solid #e6a23c;
  padding-left: 10px;
  margin-bottom: 6px;
  background: #fdf6ec;
  border-radius: 0 4px 4px 0;
}

/* Empty */
.sap-empty {
  color: #c0c4cc;
  font-size: 12px;
  font-style: italic;
}
</style>
