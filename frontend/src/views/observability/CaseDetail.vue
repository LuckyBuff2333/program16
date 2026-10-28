<template>
  <div class="obs-case" v-loading="loading">
    <!-- ═══ 顶部操作栏 ═══ -->
    <div class="obs-toolbar">
      <el-button text @click="$emit('navigate', { page: 'obs_dashboard' })">← 返回台账</el-button>
      <div class="obs-toolbar-actions">
        <el-button size="small" @click="handleDownloadReport">
          📄 下载报告
        </el-button>
        <el-button type="primary" size="small" @click="handleRetest"
          :loading="retesting" :disabled="retesting">
          {{ retesting ? `复测中 ${retestProgress}%` : '一键复测' }}
        </el-button>
      </div>
    </div>

    <!-- 进度条 -->
    <el-progress v-if="retesting"
      :percentage="retestProgress"
      :status="retestProgressStatus"
      :stroke-width="4" style="margin: -8px 0" />

    <!-- ═══ 概览卡片：Case ID + 关键信息网格 ═══ -->
    <div class="card">
      <div class="card-top">
        <div class="card-top-left">
          <span class="case-id">{{ detail.case_id }}</span>
          <el-tag v-if="detail.ai_module || detail.actual_module" size="small" type="warning" effect="plain">
            {{ detail.ai_module || detail.actual_module }}
          </el-tag>
          <el-tag v-if="detail.error_type" size="small" type="danger" effect="plain">
            {{ detail.error_type }}
          </el-tag>
          <el-tag v-if="detail.analysis_result" size="small" :type="detail.analysis_result === '成功' ? 'success' : 'info'" effect="plain">
            {{ detail.analysis_result }}
          </el-tag>
        </div>
      </div>
      <div class="info-grid">
        <div class="info-item" v-if="detail.vcu_number">
          <span class="info-label">任务编号</span>
          <span class="info-value">{{ detail.vcu_number }}</span>
        </div>
        <div class="info-item" v-if="detail.problem_time">
          <span class="info-label">发生时间</span>
          <span class="info-value">{{ detail.problem_time }}</span>
        </div>
        <div class="info-item" v-if="detail.trigger_source">
          <span class="info-label">任务类型</span>
          <span class="info-value">{{ detail.trigger_source }}</span>
        </div>
        <div class="info-item" v-if="detail.version">
          <span class="info-label">软件版本</span>
          <span class="info-value">{{ detail.version }}</span>
        </div>
        <div class="info-item" v-if="detail.analysis_date">
          <span class="info-label">分析日期</span>
          <span class="info-value">{{ detail.analysis_date }}</span>
        </div>
        <div class="info-item" v-if="formatDuration(detail.total_seconds)">
          <span class="info-label">分析耗时</span>
          <span class="info-value">{{ formatDuration(detail.total_seconds) }}</span>
        </div>
        <div class="info-item" v-if="detail.confidence">
          <span class="info-label">置信度</span>
          <span class="info-value">{{ detail.confidence.toFixed(2) }}</span>
        </div>
        <div class="info-item" v-if="detail.actual_module">
          <span class="info-label">实际模块</span>
          <span class="info-value">{{ detail.actual_module }}</span>
        </div>
      </div>
    </div>

    <!-- ═══ 问题描述 ═══ -->
    <div class="card" v-if="jiraSummary">
      <div class="card-header">问题描述</div>
      <div class="card-body desc-text">{{ jiraSummary }}</div>
    </div>

    <!-- ═══ 根因分析 ═══ -->
    <div class="card" v-if="rootCause">
      <div class="card-header">根因分析</div>
      <div class="card-body">
        <div class="root-cause-text">{{ rootCause }}</div>
        <!-- 证据链 -->
        <div class="evidence-section" v-if="evidenceChain.length">
          <div class="sub-label">证据链</div>
          <div v-for="(ev, idx) in evidenceChain" :key="idx" class="evidence-item">
            <span class="ev-num">{{ idx + 1 }}</span>
            <span class="ev-text">{{ ev }}</span>
          </div>
        </div>
        <!-- 处置建议 -->
        <div class="disposition" v-if="panel.disposition">
          <div class="sub-label">处置建议</div>
          <div class="disposition-text">{{ panel.disposition }}</div>
        </div>
      </div>
    </div>

    <!-- ═══ 推理过程（可折叠）═══ -->
    <div class="card" v-if="reasoningRounds.length">
      <div class="card-header">
        推理过程
        <el-tag size="small" type="info" effect="plain" style="margin-left: 8px">
          {{ reasoningRounds.length }} 轮
        </el-tag>
      </div>
      <div class="card-body" style="padding: 0">
        <el-collapse accordion>
          <el-collapse-item v-for="round in reasoningRounds" :key="round.round">
            <template #title>
              <div class="round-title">
                <span class="round-badge">R{{ round.round }}</span>
                <span class="round-summary">{{ round.summary }}</span>
                <span v-if="round.time_range" class="round-time">{{ round.time_range }}</span>
              </div>
            </template>
            <div class="round-content">
              <div class="round-block" v-if="round.llm_text">
                <div class="block-label">AI 推理</div>
                <div class="block-text">{{ round.llm_text }}</div>
              </div>
              <div class="round-block conclusion" v-if="round.conclusion">
                <div class="block-label">本轮结论</div>
                <div class="block-text">{{ round.conclusion }}</div>
              </div>
              <div class="round-block" v-if="round.knowledge && round.knowledge.length">
                <div class="block-label">知识库引用</div>
                <div class="kb-tags">
                  <el-tag v-for="(kb, ki) in round.knowledge" :key="ki" size="small" effect="plain">{{ kb }}</el-tag>
                </div>
              </div>
              <div class="round-block" v-if="round.tool_results && round.tool_results.length">
                <div class="block-label">工具执行结果</div>
                <div v-for="(tool, ti) in round.tool_results" :key="ti" class="tool-output">
                  <pre>{{ truncateTool(tool) }}</pre>
                </div>
              </div>
            </div>
          </el-collapse-item>
        </el-collapse>
      </div>
    </div>

    <!-- ═══ 日志路径 ═══ -->
    <div class="card log-card" v-if="detail.log_path">
      <div class="card-header">日志路径</div>
      <div class="card-body">
        <code class="log-path" @click="copyText(detail.log_path)">{{ detail.log_path }}</code>
      </div>
    </div>


  </div>
</template>

<script lang="ts">
import { ElMessage } from 'element-plus'

const API_BASE = ''

interface CaseDetailData {
  case_id: string; vcu_number: string; description: string
  total_duration: string; confidence: number; converged: boolean
  reflow_status: string; case_type: string; root_cause: string
  phases: any[]; decision_chain: any; hypothesis_table: any[]
  analysis_result: string; trigger_source: string; version: string
  problem_time: string; analysis_date: string; error_type: string
  error_message: string; total_seconds: number | null
  analysis_seconds: number | null; ai_module: string; actual_module: string
  manual_review: string; analysis_panel: any; rootcause: string
  reasoning_rounds: any[]; log_path: string
  jira_summary: string; jira_description: string

}

const emptyDetail: CaseDetailData = {
  case_id: '', vcu_number: '', description: '', total_duration: '',
  confidence: 0, converged: false, reflow_status: '', case_type: '',
  root_cause: '', phases: [], decision_chain: null, hypothesis_table: [],
  analysis_result: '', trigger_source: '', version: '', problem_time: '',
  analysis_date: '', error_type: '', error_message: '',
  total_seconds: null, analysis_seconds: null, ai_module: '', actual_module: '',
  manual_review: '', analysis_panel: null, rootcause: '',
  reasoning_rounds: [], log_path: '',
  jira_summary: '', jira_description: '',
}

export default {
  props: { caseId: { type: String, default: '' } },
  emits: ['navigate'],
  data() {
    return {
      detail: { ...emptyDetail } as CaseDetailData,
      loading: false,
      retesting: false, retestProgress: 0, retestMessage: '',
      retestProgressStatus: '' as '' | 'success' | 'warning' | 'exception',
      _pollTimer: null as ReturnType<typeof setInterval> | null,

    }
  },
  computed: {
    jiraSummary(): string {
      return (this.detail.jira_summary || '').trim()
    },
    problemDesc(): string {
      const d = this.detail
      return (d.description || d.rootcause || d.root_cause || '').trim()
    },
    rootCause(): string {
      return (this.detail.root_cause || this.detail.rootcause || '').trim()
    },
    reasoningRounds(): any[] {
      const rr = this.detail.reasoning_rounds
      return Array.isArray(rr) ? rr : []
    },
    panel(): any {
      const ap = this.detail.analysis_panel
      return (ap && typeof ap === 'object') ? ap : {}
    },
    evidenceChain(): string[] {
      return Array.isArray(this.panel.evidence_chain) ? this.panel.evidence_chain : []
    },

  },
  watch: {
    caseId: { immediate: true, handler(val: string) { if (val) this.loadDetail(val) } },
  },
  methods: {
    async loadDetail(id: string) {
      this.loading = true
      try {
        const res = await fetch(`${API_BASE}/api/v1/observability/cases/${encodeURIComponent(id)}`)
        const json = await res.json()
        if (json.ok && json.data) {
          this.detail = json.data as CaseDetailData
          if (json.data._report_fetched) ElMessage.success('已自动获取报告')
        } else {
          ElMessage.warning(json.message || 'Case 不存在')
          this.detail = { ...emptyDetail, case_id: id }
        }
      } catch (e: any) {
        ElMessage.error('加载失败: ' + e.message)
        this.detail = { ...emptyDetail, case_id: id }
      } finally { this.loading = false }
    },
    handleDownloadReport() {
      const caseId = this.detail.case_id
      if (!caseId) { ElMessage.warning('无有效 Case'); return }
      window.open(`${API_BASE}/api/v1/observability/cases/${encodeURIComponent(caseId)}/report_download`, '_blank')
    },
    handleRetest() {
      if (this.retesting) return
      const caseId = this.detail.case_id
      if (!caseId) { ElMessage.warning('无有效 Case'); return }
      this.retesting = true; this.retestProgress = 0; this.retestProgressStatus = ''
      fetch(`${API_BASE}/api/v1/observability/cases/${encodeURIComponent(caseId)}/retest`, { method: 'POST' })
        .then(r => r.json())
        .then(json => {
          if (!json.ok) { ElMessage.error(json.message); this.retesting = false; return }
          ElMessage.info('复测任务已提交'); this.startPoll(json.data.task_id)
        })
        .catch(e => { ElMessage.error('复测失败: ' + e.message); this.retesting = false })
    },
    startPoll(taskId: string) {
      if (this._pollTimer) clearInterval(this._pollTimer)
      this._pollTimer = setInterval(async () => {
        try {
          const res = await fetch(`${API_BASE}/api/v1/observability/tasks/${taskId}`)
          const json = await res.json()
          if (!json.ok) { this.stopPoll(); ElMessage.error(json.message); return }
          const t = json.data; this.retestProgress = t.progress || 0
          if (t.status === 'success') {
            this.retestProgressStatus = 'success'; this.stopPoll()
            ElMessage.success('复测完成'); setTimeout(() => { this.loadDetail(this.detail.case_id); this.retesting = false }, 1200)
          } else if (t.status === 'failed') {
            this.retestProgressStatus = 'exception'; this.stopPoll()
            ElMessage.error(t.message || '复测失败'); setTimeout(() => { this.retesting = false }, 3000)
          }
        } catch (e: any) { this.stopPoll(); ElMessage.error(e.message); this.retesting = false }
      }, 2000)
    },
    stopPoll() { if (this._pollTimer) { clearInterval(this._pollTimer); this._pollTimer = null } },
    formatDuration(sec: number | null): string {
      if (!sec || sec <= 0) return ''
      if (sec < 60) return `${sec.toFixed(1)}s`
      if (sec < 3600) return `${(sec / 60).toFixed(1)} min`
      const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60)
      return `${h}h ${m}m`
    },
    truncateTool(text: string): string {
      if (!text) return ''
      return text.length > 2000 ? text.slice(0, 2000) + `\n... (截断 ${text.length - 2000} 字符)` : text
    },

    copyText(text: string) {
      if (!text) return
      navigator.clipboard.writeText(text).then(() => ElMessage.success('已复制')).catch(() => ElMessage.warning('复制失败'))
    },
  },
  beforeUnmount() { this.stopPoll() },
}
</script>

<style scoped>
.obs-case { display: flex; flex-direction: column; gap: 16px; max-width: 1200px; }

/* ── 工具栏 ── */
.obs-toolbar {
  display: flex; align-items: center; justify-content: space-between;
}
.obs-toolbar-actions { display: flex; gap: 8px; align-items: center; }

/* ── 通用卡片 ── */
.card {
  background: #fff; border: 1px solid #e8e8e8; border-radius: 8px;
  overflow: hidden;
}
.card-top {
  padding: 16px 20px; border-bottom: 1px solid #f0f0f0;
  display: flex; align-items: center; justify-content: space-between;
}
.card-top-left { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.case-id {
  font-size: 18px; font-weight: 700; color: #1a1a1a;
  font-family: 'Consolas', 'Menlo', monospace;
}
.card-header {
  padding: 14px 20px; font-size: 15px; font-weight: 600; color: #1a1a1a;
  border-bottom: 1px solid #f0f0f0; display: flex; align-items: center;
  background: #fafafa;
}
.card-body { padding: 16px 20px; }

/* ── 信息网格 ── */
.info-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px 24px; padding: 16px 20px;
}
.info-item { display: flex; flex-direction: column; gap: 2px; }
.info-label { font-size: 12px; color: #999; }
.info-value { font-size: 13px; color: #333; word-break: break-all; }

/* ── 描述文本 ── */
.desc-text {
  font-size: 14px; color: #333; line-height: 1.8; word-break: break-word;
}

/* ── 根因 ── */
.root-cause-text {
  font-size: 14px; color: #333; line-height: 1.8; word-break: break-word;
  padding: 12px 16px; background: #fff7e6; border-left: 3px solid #fa8c16;
  border-radius: 0 4px 4px 0; margin-bottom: 16px;
}
.sub-label {
  font-size: 13px; font-weight: 600; color: #555; margin-bottom: 8px;
}
.evidence-section { margin-bottom: 16px; }
.evidence-item {
  display: flex; gap: 8px; padding: 6px 0; font-size: 13px; color: #444;
  line-height: 1.6;
}
.ev-num {
  display: inline-flex; align-items: center; justify-content: center;
  width: 20px; height: 20px; border-radius: 50%; flex-shrink: 0;
  background: #e6f7ff; color: #1890ff; font-size: 11px; font-weight: 600;
  margin-top: 2px;
}
.disposition-text { font-size: 13px; color: #444; line-height: 1.6; }

/* ── 推理轮次 ── */
.card :deep(.el-collapse) { border: none; }
.card :deep(.el-collapse-item__header) {
  height: auto; min-height: 44px; padding: 10px 20px; line-height: 1.5;
  font-size: 13px; background: #fafafa; border-bottom: 1px solid #f0f0f0;
}
.card :deep(.el-collapse-item__wrap) { background: #fff; }
.card :deep(.el-collapse-item__content) { padding: 0; }
.card :deep(.el-collapse-item) { border-bottom: 1px solid #f5f5f5; }
.card :deep(.el-collapse-item:last-child) { border-bottom: none; }

.round-title {
  display: flex; align-items: center; gap: 10px; width: 100%; min-width: 0;
}
.round-badge {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 28px; height: 22px; border-radius: 4px; flex-shrink: 0;
  background: #1890ff; color: #fff; font-size: 11px; font-weight: 700;
  padding: 0 6px;
}
.round-summary {
  font-size: 13px; color: #444; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0;
}
.round-time {
  font-size: 11px; color: #999; white-space: nowrap; flex-shrink: 0;
  font-family: 'Consolas', monospace;
}

.round-content { display: flex; flex-direction: column; gap: 12px; padding: 16px 20px; }
.round-block {
  border-left: 3px solid #d9d9d9; padding: 10px 14px;
  background: #f9f9f9; border-radius: 0 6px 6px 0;
}
.round-block.conclusion {
  border-left-color: #fa8c16; background: #fff7e6;
}
.block-label {
  font-size: 12px; font-weight: 600; color: #888; margin-bottom: 4px;
  text-transform: uppercase; letter-spacing: 0.5px;
}
.block-text { font-size: 13px; color: #333; line-height: 1.7; word-break: break-word; white-space: pre-wrap; }
.kb-tags { display: flex; flex-wrap: wrap; gap: 4px; }
.tool-output {
  max-height: 280px; overflow-y: auto; border-radius: 4px;
  background: #f5f5f5; border: 1px solid #eee;
}
.tool-output pre {
  margin: 0; padding: 10px 14px; font-size: 12px; line-height: 1.5;
  font-family: 'Consolas', monospace; white-space: pre-wrap; word-break: break-all;
  color: #555;
}

/* ── 日志路径 ── */
.log-card .card-body { padding: 12px 20px; }
.log-path {
  font-size: 13px; color: #1890ff; cursor: pointer;
  font-family: 'Consolas', monospace; word-break: break-all;
}
.log-path:hover { text-decoration: underline; }


</style>
