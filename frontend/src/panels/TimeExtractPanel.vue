<template>
  <div>
    <div class="section-title">时间批量提取</div>
    <el-alert type="info" :closable="false"
      title="通过 JQL 查询或手动输入 Jira 号，批量提取触发时间（评论/字段 → 视频OCR → 图片OCR），20条一批写入云端"></el-alert>

    <!-- JQL 搜索区域 -->
    <el-card shadow="never" style="margin-top:14px">
      <div style="margin-bottom:8px;font-weight:600;color:#303133">JQL 查询</div>
      <el-input v-model="jql" type="textarea" :rows="2" placeholder="输入 JQL 查询语句，如 created >= startOfDay() AND issuetype = 'bug'"
        @keydown.ctrl.enter="startExtract"></el-input>
      <div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap">
        <el-button size="small" @click="setJql('today')">今日新增 Bug</el-button>
        <el-button size="small" @click="setJql('yesterday')">昨日新增 Bug</el-button>
        <el-button size="small" @click="setJql('week')">本周新增 Bug</el-button>
        <el-button size="small" @click="setJql('no_label')">无触发时间标签</el-button>
      </div>
    </el-card>

    <!-- 手动输入区域 -->
    <el-card shadow="never" style="margin-top:14px">
      <div style="margin-bottom:8px;font-weight:600;color:#303133">手动输入 Jira 号（可选，逗号/换行分隔）</div>
      <el-input v-model="manualBugids" type="textarea" :rows="2" placeholder="VCU-123456, VCU-234567"></el-input>
    </el-card>

    <!-- 操作按钮 -->
    <div style="margin-top:14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap">
      <el-checkbox v-model="skipCached">跳过已有缓存</el-checkbox>
      <el-checkbox v-model="filterAiPreliminary">过滤AI初步分析结果</el-checkbox>
      <el-button type="primary" :loading="running" :disabled="!jql && !manualBugids" @click="startExtract">开始提取</el-button>
      <el-button type="danger" :disabled="!running" @click="stopExtract">停止</el-button>
      <span v-if="statusMsg" style="font-size:13px;color:#606266">{{ statusMsg }}</span>
    </div>

    <!-- 进度条 -->
    <div v-if="total > 0" style="margin-top:14px">
      <el-progress :percentage="pct" :stroke-width="18" :text-inside="true" :status="progressStatus"></el-progress>
      <div style="margin-top:6px;font-size:12px;color:#909399;display:flex;gap:16px">
        <span>完成: {{ doneCount }}/{{ total }}</span>
        <span>命中: {{ hitCount }}</span>
        <span v-if="aiSkippedCount">AI分析跳过: {{ aiSkippedCount }}</span>
        <span v-if="cacheSkippedCount">缓存跳过: {{ cacheSkippedCount }}</span>
        <span v-if="batchSavedCount">已写入云端: {{ batchSavedCount }} 条</span>
      </div>
    </div>

    <!-- 结果表格 -->
    <el-card v-if="rows.length" shadow="never" style="margin-top:14px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
        <span style="font-weight:600">提取结果（共 {{ rows.length }} 条，命中 {{ hitCount }}）</span>
      </div>
      <el-table :data="rows" size="small" stripe border max-height="400">
        <el-table-column type="index" label="#" width="50" align="center"></el-table-column>
        <el-table-column prop="bugid" label="Jira号" width="140"></el-table-column>
        <el-table-column prop="time" label="触发时间" min-width="160">
          <template #default="{ row }">
            <span :style="row.time ? 'color:#67c23a' : 'color:#c0c4cc'">{{ row.time || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="source" label="来源" width="110" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.source === 'summary'" type="success" size="small">标题</el-tag>
            <el-tag v-else-if="row.source === 'comment'" type="success" size="small">评论</el-tag>
            <el-tag v-else-if="row.source === 'custom_field'" type="success" size="small">字段</el-tag>
            <el-tag v-else-if="row.source === 'description'" type="success" size="small">描述</el-tag>
            <el-tag v-else-if="row.source === 'attachment_name'" type="success" size="small">附件名</el-tag>
            <el-tag v-else-if="row.source === 'video_ocr'" type="warning" size="small">视频OCR</el-tag>
            <el-tag v-else-if="row.source === 'image_ocr'" size="small">图片OCR</el-tag>
            <el-tag v-else-if="row.source === 'ai_analyzed'" type="info" size="small" style="color:#409eff">AI已分析</el-tag>
            <el-tag v-else-if="row.source === 'no_gmlogger'" type="info" size="small">无gmlogger</el-tag>
            <el-tag v-else-if="row.source === 'failed'" type="danger" size="small">提取失败</el-tag>
            <el-tag v-else-if="row.source === 'error'" type="danger" size="small">异常</el-tag>
            <el-tag v-else type="info" size="small">{{ row.source || '等待中' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="error" label="备注" min-width="160" show-overflow-tooltip>
          <template #default="{ row }"><span style="color:#f56c6c">{{ row.error || '' }}</span></template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-empty v-if="!running && !rows.length" description="输入 JQL 或 Jira 号后点击开始提取" style="margin-top:30px"></el-empty>
  </div>
</template>

<script lang="ts">
// @ts-nocheck
import { ElMessage } from 'element-plus';
import { api } from '../composables/utils';

const JQL_PRESETS = {
  today: 'created >= startOfDay() AND issuetype = "bug" AND status != "closed" AND project = VCS_Info4.0_High_Platform_PATAC_Jira',
  yesterday: 'created >= startOfDay("-1d") AND created <= endOfDay("-1d") AND issuetype = "bug" AND status != "closed" AND project = VCS_Info4.0_High_Platform_PATAC_Jira ORDER BY cf[10603] ASC',
  week: 'created >= startOfWeek() AND issuetype = "bug" AND status != "closed" AND project = VCS_Info4.0_High_Platform_PATAC_Jira',
  no_label: 'labels not in (trigger_time) AND issuetype = "bug" AND status != "closed" AND project = VCS_Info4.0_High_Platform_PATAC_Jira',
};

export default {
  name: 'TimeExtractPanel',
  data() {
    return {
      jql: '',
      manualBugids: '',
      skipCached: true,
      filterAiPreliminary: true,
      running: false,
      abortCtrl: null as AbortController | null,
      total: 0,
      doneCount: 0,
      hitCount: 0,
      skippedCount: 0,
      aiSkippedCount: 0,
      cacheSkippedCount: 0,
      batchSavedCount: 0,
      statusMsg: '',
      rows: [] as any[],
    };
  },
  computed: {
    pct() { return this.total ? Math.round((this.doneCount / this.total) * 100) : 0; },
    progressStatus() {
      if (this.doneCount < this.total) return undefined;
      return this.hitCount > 0 ? 'success' : 'warning';
    },
  },
  methods: {
    setJql(key: string) { this.jql = JQL_PRESETS[key] || ''; },
    async startExtract() {
      if (!this.jql && !this.manualBugids) return ElMessage.warning('请输入 JQL 或 Jira 号');
      // 解析手动输入的 bugid 列表
      const manual = this.manualBugids.split(/[\s,;\n]+/).map((s: string) => s.trim()).filter(Boolean);
      const body: any = {};
      if (this.jql) body.jql = this.jql;
      if (manual.length) body.bugids = manual;
      body.skip_cached = this.skipCached;
      body.filter_ai_preliminary = this.filterAiPreliminary;

      this.running = true;
      this.total = 0; this.doneCount = 0; this.hitCount = 0; this.skippedCount = 0; this.aiSkippedCount = 0; this.cacheSkippedCount = 0; this.batchSavedCount = 0;
      this.rows = []; this.statusMsg = '正在启动...';
      this.abortCtrl = new AbortController();

      try {
        const resp = await fetch('/api/trigger/batch_extract_time', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body), signal: this.abortCtrl.signal,
        });
        if (!resp.ok) {
          const errBody = await resp.json().catch(() => ({}));
          throw new Error(errBody.message || `HTTP ${resp.status}`);
        }
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            try {
              const evt = JSON.parse(line.slice(6));
              this.handleSSE(evt);
            } catch (e) { /* ignore */ }
          }
        }
      } catch (e: any) {
        if (e.name === 'AbortError') {
          this.statusMsg = '已停止';
          ElMessage.warning('已停止提取，已提取的数据已写入云端');
        } else {
          this.statusMsg = '执行失败: ' + e.message;
          ElMessage.error('提取失败: ' + e.message);
        }
      } finally {
        this.running = false;
        this.abortCtrl = null;
      }
    },
    handleSSE(evt: any) {
      if (evt.type === 'start') {
        this.total = evt.total;
        this.skippedCount = evt.skipped || 0;
        this.aiSkippedCount = evt.ai_skipped || 0;
        this.cacheSkippedCount = evt.cache_skipped || 0;
        this.statusMsg = evt.message || `共 ${evt.total} 条待提取，并行 2 个...`;
      } else if (evt.type === 'progress') {
        this.doneCount = evt.current;
        this.hitCount = evt.hit;
        this.statusMsg = `提取中 ${evt.current}/${evt.total}`;
        this.rows.push({
          bugid: evt.bugid, time: evt.time || '', source: evt.source || '', error: evt.error || '',
        });
      } else if (evt.type === 'batch_saved') {
        this.batchSavedCount += (evt.count || 0);
      } else if (evt.type === 'done') {
        this.aiSkippedCount = evt.ai_skipped || this.aiSkippedCount;
        this.statusMsg = evt.message || '提取完成';
      } else if (evt.type === 'stopped') {
        this.doneCount = evt.current || this.doneCount;
        this.hitCount = evt.hit || this.hitCount;
        this.statusMsg = evt.message || '已停止';
      }
    },
    stopExtract() {
      // 调用后端停止接口 + 前端中止
      fetch('/api/trigger/batch_extract_time/stop', { method: 'POST', headers: { 'Content-Type': 'application/json' } });
      if (this.abortCtrl) this.abortCtrl.abort();
    },
  },
};
</script>
