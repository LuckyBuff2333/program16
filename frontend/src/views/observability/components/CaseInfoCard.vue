<template>
  <div class="cic">
    <!-- ═══ 顶部信息条：Case ID + 标签 + 关键元数据 ═══ -->
    <div class="cic-header">
      <div class="cic-header-left">
        <span class="cic-case-id">{{ caseId }}</span>
        <span v-if="moduleTag" class="cic-tag cic-tag-module">{{ moduleTag }}</span>
        <span v-if="errorTag" class="cic-tag cic-tag-error">{{ errorTag }}</span>
      </div>
      <div class="cic-header-right">
        <span v-if="taskNumber" class="cic-meta-item">
          <span class="cic-meta-label">任务编号:</span> {{ taskNumber }}
        </span>
        <span v-if="occurrenceTime" class="cic-meta-item">
          <span class="cic-meta-label">发生时间:</span> {{ occurrenceTime }}
        </span>
        <span v-if="version" class="cic-meta-item">
          <span class="cic-meta-label">软件版本:</span> {{ version }}
        </span>
      </div>
    </div>

    <!-- ═══ 扩展元数据条（原基础信息卡片的独有字段）═══ -->
    <div class="cic-meta-bar" v-if="hasMetaFields">
      <span v-if="triggerSource" class="cic-meta-pill">
        <span class="cic-meta-k">任务类型</span> {{ triggerSource }}
      </span>
      <span v-if="totalDuration" class="cic-meta-pill">
        <span class="cic-meta-k">分析耗时</span> {{ totalDuration }}
      </span>
      <span v-if="actualModule" class="cic-meta-pill">
        <span class="cic-meta-k">实际模块</span> {{ actualModule }}
      </span>
      <span v-if="analysisDate" class="cic-meta-pill">
        <span class="cic-meta-k">分析日期</span> {{ analysisDate }}
      </span>
      <span v-if="manualReview" class="cic-meta-pill">
        <span class="cic-meta-k">误漏检</span> {{ manualReview }}
      </span>
      <span v-if="converged !== null" class="cic-meta-pill">
        <span class="cic-meta-k">收敛</span> {{ converged ? '是' : '否' }}
      </span>
      <span v-if="confidence" class="cic-meta-pill">
        <span class="cic-meta-k">置信度</span> {{ confidence }}
      </span>
    </div>

    <!-- ═══ 问题描述 ═══ -->
    <div class="cic-section cic-desc-section">
      <div class="cic-section-label">
        问题描述
        <span class="cic-copy-btn" title="复制" @click="copyText(description)">📋</span>
      </div>
      <div class="cic-desc-content">{{ description || '暂无描述信息' }}</div>
    </div>

    <!-- ═══ 推理过程（可折叠）═══ -->
    <div class="cic-section cic-reasoning-section" v-if="reasoningRounds.length > 0">
      <div class="cic-section-label">
        推理过程
        <el-tag size="small" type="info" effect="plain">{{ reasoningRounds.length }} 轮</el-tag>
      </div>
      <el-collapse accordion>
        <el-collapse-item
          v-for="round in reasoningRounds"
          :key="round.round"
        >
          <template #title>
            <div class="cic-round-header">
              <span class="cic-round-num">第 {{ round.round }} 轮</span>
              <span class="cic-round-summary">{{ round.summary }}</span>
              <span v-if="round.time_range" class="cic-round-time">{{ round.time_range }}</span>
              <span v-if="round.knowledge && round.knowledge.length" class="cic-round-kb">
                📚 {{ round.knowledge.length }}
              </span>
            </div>
          </template>
          <div class="cic-round-body">
            <!-- LLM 推理 -->
            <div class="cic-round-block" v-if="round.llm_text">
              <div class="cic-round-block-title">🧠 AI 推理</div>
              <div class="cic-round-block-content cic-llm-text">{{ round.llm_text }}</div>
            </div>
            <!-- 本轮结论 -->
            <div class="cic-round-block cic-conclusion-block" v-if="round.conclusion">
              <div class="cic-round-block-title">📌 本轮结论</div>
              <div class="cic-round-block-content">{{ round.conclusion }}</div>
            </div>
            <!-- 知识库引用 -->
            <div class="cic-round-block" v-if="round.knowledge && round.knowledge.length">
              <div class="cic-round-block-title">📚 知识库引用</div>
              <div class="cic-round-block-content">
                <el-tag
                  v-for="(kb, ki) in round.knowledge"
                  :key="ki"
                  size="small"
                  effect="plain"
                  style="margin: 2px 4px 2px 0"
                >{{ kb }}</el-tag>
              </div>
            </div>
            <!-- 工具执行结果 -->
            <div class="cic-round-block" v-if="round.tool_results && round.tool_results.length">
              <div class="cic-round-block-title">🔧 工具执行结果</div>
              <div
                v-for="(tool, ti) in round.tool_results"
                :key="ti"
                class="cic-round-block-content cic-tool-result"
              >
                <pre class="cic-tool-pre">{{ truncateTool(tool) }}</pre>
              </div>
            </div>
          </div>
        </el-collapse-item>
      </el-collapse>
    </div>

    <!-- ═══ 发生事件列表（回退：无推理轮次时显示）═══ -->
    <div class="cic-section cic-events-section" v-else>
      <div class="cic-section-label">发生事件</div>
      <div v-if="events.length > 0" class="cic-event-list">
        <div v-for="(evt, idx) in events" :key="idx" class="cic-event-card">
          <div class="cic-event-header">
            <span class="cic-event-name">{{ evt.name }}</span>
          </div>
          <div class="cic-event-meta">
            <span v-if="evt.time" class="cic-event-time">{{ evt.time }}</span>
            <span v-if="evt.module" class="cic-event-module-tag">{{ evt.module }}</span>
          </div>
          <div class="cic-event-desc">{{ evt.desc }}</div>
        </div>
      </div>
      <div v-else class="cic-empty">暂无事件数据</div>

    </div>

    <!-- ═══ 日志路径（如果存在）═══ -->
    <div v-if="logPath" class="cic-section cic-log-section">
      <div class="cic-section-label">
        日志路径
        <span class="cic-copy-btn" title="复制" @click="copyText(logPath)">📋</span>
      </div>
      <div class="cic-log-path">
        <span class="cic-log-icon">📂</span>
        <span class="cic-log-text" :title="logPath">{{ logPath }}</span>
      </div>
    </div>
  </div>
</template>

<script lang="ts">
import { ElMessage } from 'element-plus'

export default {
  props: {
    detail: { type: Object, default: () => ({}) },
  },
  computed: {
    caseId(): string {
      return (this.detail as any).case_id || ''
    },
    /** 模块标签 */
    moduleTag(): string {
      const d = this.detail as any
      return d.ai_module || d.actual_module || ''
    },
    /** 错误标签 */
    errorTag(): string {
      const d = this.detail as any
      if (d.error_type) return d.error_type
      // 从分析结果构造标签
      if (d.analysis_result && d.analysis_result !== '成功') {
        return d.analysis_result
      }
      return ''
    },
    /** 任务编号 */
    taskNumber(): string {
      const d = this.detail as any
      return d.vcu_number || ''
    },
    /** 发生时间 */
    occurrenceTime(): string {
      const d = this.detail as any
      return d.problem_time || d.finish_time || ''
    },
    /** 软件版本 */
    version(): string {
      return (this.detail as any).version || ''
    },
    /** ── 扩展元数据（原基础信息卡片独有字段）── */
    triggerSource(): string {
      return (this.detail as any).trigger_source || ''
    },
    totalDuration(): string {
      const d = this.detail as any
      const sec = d.total_seconds
      if (sec != null && sec > 0) return this.formatDuration(sec)
      return d.total_duration || ''
    },
    actualModule(): string {
      return (this.detail as any).actual_module || ''
    },
    analysisDate(): string {
      return (this.detail as any).analysis_date || ''
    },
    manualReview(): string {
      return (this.detail as any).manual_review || ''
    },
    converged(): boolean | null {
      const d = this.detail as any
      return d.converged != null ? d.converged : null
    },
    confidence(): string {
      const c = (this.detail as any).confidence
      return c ? c.toFixed(2) : ''
    },
    hasMetaFields(): boolean {
      return !!(this.triggerSource || this.totalDuration || this.actualModule
        || this.analysisDate || this.manualReview || this.converged !== null || this.confidence)
    },
    /** 问题描述 */
    description(): string {
      const d = this.detail as any
      return (d.description || d.root_cause || d.rootcause || '').trim()
    },
    /** 日志路径：仅使用后端验证过的真实路径 */
    logPath(): string {
      return (this.detail as any).log_path || ''
    },
    /** 推理轮次数据 */
    reasoningRounds(): any[] {
      const rr = (this.detail as any).reasoning_rounds
      return Array.isArray(rr) ? rr : []
    },
    /** 从 timeline 提取所有事件列表 */
    events(): Array<{ name: string; time: string; module: string; desc: string }> {
      const d = this.detail as any
      const result: Array<{ name: string; time: string; module: string; desc: string }> = []
      const dc = d.decision_chain

      if (dc && typeof dc === 'object') {
        const rounds = dc.timeline_rounds || []
        for (const round of rounds) {
          const phases = round.phases || round.stages || []
          for (const phase of phases) {
            const events = phase.events || []
            for (const evt of events) {
              const desc = (evt.desc || evt.text || '').trim()
              const time = (evt.time || '').trim()
              if (desc && desc.length > 3 && !desc.startsWith('触发来源')) {
                const phaseName = phase.phase_name || phase.stage || ''
                result.push({
                  name: this.inferEventName(desc, phaseName),
                  time,
                  module: phaseName || this.inferModule(desc, d),
                  desc: desc.slice(0, 300),
                })
              }
            }
          }
        }
      }

      // 回退：用 error_type + error_message 构造事件
      if (result.length === 0 && (d.error_type || d.error_message)) {
        result.push({
          name: d.error_type || '异常事件',
          time: d.problem_time || '',
          module: d.ai_module || d.actual_module || '',
          desc: d.error_message || d.error_type || '',
        })
      }

      // 再回退：用根因分析构造一个摘要事件
      if (result.length === 0 && d.root_cause_summary) {
        result.push({
          name: '根因分析结论',
          time: d.problem_time || d.analysis_date || '',
          module: d.ai_module || d.actual_module || '',
          desc: d.root_cause_summary.slice(0, 300),
        })
      }

      return result
    },
  },
  methods: {
    formatDuration(sec: number): string {
      if (!sec || sec <= 0) return ''
      const m = Math.floor(sec / 60)
      const s = Math.round(sec % 60)
      if (m > 0) return `${m}m${s > 0 ? s + 's' : ''}`
      return `${s}s`
    },
    copyText(text: string) {
      if (!text) return
      navigator.clipboard.writeText(text).then(() => {
        ElMessage.success('已复制到剪贴板')
      }).catch(() => {
        ElMessage.warning('复制失败')
      })
    },
    inferEventName(desc: string, phaseName: string): string {
      if (desc.includes('mismatch') || desc.includes('不匹配')) return 'ID 不匹配事件'
      if (desc.includes('超时') || desc.includes('timeout')) return '超时事件'
      if (desc.includes('异常') || desc.includes('error')) return '异常事件'
      if (desc.includes('丢弃') || desc.includes('drop')) return '消息丢弃事件'
      if (desc.includes('空') || desc.includes('empty')) return '数据为空事件'
      if (desc.includes('触发') || desc.includes('trigger')) return '触发事件'
      if (phaseName === '推理分析') return 'AI 推理分析'
      if (phaseName === '日志获取') return '日志采集'
      if (phaseName === '裁定判定') return '裁定判定'
      return phaseName || '分析事件'
    },
    inferModule(desc: string, d: any): string {
      if (d.ai_module) return d.ai_module
      if (d.actual_module) return d.actual_module
      const match = desc.match(/([\w-]+(?:_\w+)*)\s*(?:的|模块|服务|组件)/)
      if (match) return match[1]
      return d.trigger_source || ''
    },
    truncateTool(text: string): string {
      if (!text) return ''
      // 工具结果最多显示 2000 字符
      if (text.length > 2000) return text.slice(0, 2000) + '\n... (截断 ' + (text.length - 2000) + ' 字符)'
      return text
    },
    roundSummary(round: any): string {
      // 优先用结论，否则用 LLM 推理文本的第一句话
      const src = (round.conclusion || round.llm_text || '').trim()
      if (!src) return ''
      // 取第一个句号/感叹号/换行前的内容
      const m = src.match(/^(.{1,80}?)[。！？\n]/)
      if (m) return m[1]
      // 取前 60 字符
      return src.length > 60 ? src.slice(0, 60) + '...' : src
    },
  },
}
</script>

<style scoped>
.cic {
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
  margin-bottom: 0;
}

/* ── 顶部信息条 ── */
.cic-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  padding: 14px 20px;
  background: #fafafa;
  border-bottom: 1px solid #ebeef5;
}
.cic-header-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.cic-case-id {
  font-size: 16px;
  font-weight: 700;
  color: #303133;
  font-family: 'Consolas', 'Menlo', monospace;
}
.cic-tag {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 3px;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.6;
}
.cic-tag-module {
  background: #fdf6ec;
  color: #e6a23c;
  border: 1px solid #f5dab1;
}
.cic-tag-error {
  background: #fef0f0;
  color: #f56c6c;
  border: 1px solid #fbc4c4;
}
.cic-header-right {
  display: flex;
  align-items: center;
  gap: 20px;
  flex-wrap: wrap;
}
.cic-meta-item {
  font-size: 13px;
  color: #606266;
  white-space: nowrap;
}
.cic-meta-label {
  color: #909399;
}

/* ── 通用 section ── */

/* ── 扩展元数据条 ── */
.cic-meta-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  padding: 10px 20px;
  border-bottom: 1px solid #f0f0f0;
  background: #fafcff;
}
.cic-meta-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  border-radius: 4px;
  font-size: 12px;
  color: #606266;
  background: #f4f4f5;
  white-space: nowrap;
}
.cic-meta-k {
  color: #909399;
}

.cic-section {
  padding: 16px 20px;
  border-bottom: 1px solid #f0f0f0;
}
.cic-section:last-child {
  border-bottom: none;
}
.cic-section-label {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.cic-copy-btn {
  cursor: pointer;
  font-size: 13px;
  opacity: 0.4;
  transition: opacity 0.2s;
}
.cic-copy-btn:hover {
  opacity: 1;
}

/* ── 问题描述 ── */
.cic-desc-content {
  font-size: 14px;
  color: #303133;
  line-height: 1.8;
  word-break: break-word;
}

/* ── 事件卡片列表 ── */
.cic-event-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.cic-event-card {
  border-left: 3px solid #e6a23c;
  background: #f5f7fa;
  border-radius: 0 6px 6px 0;
  padding: 12px 16px;
}
.cic-event-header {
  margin-bottom: 6px;
}
.cic-event-name {
  font-size: 15px;
  font-weight: 700;
  color: #303133;
}
.cic-event-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}
.cic-event-time {
  font-size: 13px;
  color: #909399;
}
.cic-event-module-tag {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 3px;
  font-size: 12px;
  color: #409eff;
  background: #ecf5ff;
  border: 1px solid #b3d8ff;
}
.cic-event-desc {
  font-size: 13px;
  color: #606266;
  line-height: 1.7;
  word-break: break-word;
}

/* ── 日志路径 ── */
.cic-log-path {
  display: flex;
  align-items: center;
  gap: 6px;
}
.cic-log-icon {
  font-size: 14px;
  flex-shrink: 0;
}
.cic-log-text {
  font-size: 13px;
  color: #409eff;
  font-family: 'Consolas', 'Menlo', monospace;
  word-break: break-all;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ── 空数据 ── */
.cic-empty {
  font-size: 13px;
  color: #c0c4cc;
  font-style: italic;
}

/* ── 推理轮次折叠 ── */
.cic-reasoning-section :deep(.el-collapse) {
  border: none;
}
.cic-reasoning-section :deep(.el-collapse-item__header) {
  height: 40px;
  line-height: 40px;
  font-size: 13px;
  background: #f5f7fa;
  padding: 0 12px;
  border-radius: 4px;
}
.cic-reasoning-section :deep(.el-collapse-item__wrap) {
  background: #fff;
}
.cic-reasoning-section :deep(.el-collapse-item__content) {
  padding: 8px 0;
}
.cic-reasoning-section :deep(.el-collapse-item) {
  margin-bottom: 6px;
}
.cic-round-header {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
}
.cic-round-num {
  font-weight: 600;
  color: #303133;
  flex-shrink: 0;
}
.cic-round-summary {
  font-size: 12px;
  color: #606266;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}
.cic-round-time {
  font-size: 12px;
  color: #909399;
  font-family: 'Consolas', 'Menlo', monospace;
}
.cic-round-kb {
  font-size: 12px;
  color: #67c23a;
  margin-left: auto;
}
.cic-round-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.cic-round-block {
  border-left: 3px solid #e4e7ed;
  padding: 8px 12px;
  background: #fafafa;
  border-radius: 0 4px 4px 0;
}
.cic-conclusion-block {
  border-left-color: #e6a23c;
  background: #fdf6ec;
}
.cic-round-block-title {
  font-size: 12px;
  font-weight: 600;
  color: #606266;
  margin-bottom: 4px;
}
.cic-round-block-content {
  font-size: 13px;
  color: #303133;
  line-height: 1.7;
  word-break: break-word;
}
.cic-llm-text {
  white-space: pre-wrap;
}
.cic-tool-result {
  max-height: 300px;
  overflow-y: auto;
}
.cic-tool-pre {
  margin: 0;
  font-size: 12px;
  font-family: 'Consolas', 'Menlo', monospace;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
  color: #606266;
}

/* ── 响应式 ── */
@media (max-width: 900px) {
  .cic-header {
    flex-direction: column;
    align-items: flex-start;
  }
  .cic-header-right {
    flex-direction: column;
    gap: 4px;
  }
}
</style>
