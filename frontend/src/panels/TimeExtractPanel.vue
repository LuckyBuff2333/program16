<template>
  <div>
    <div class="section-title">时间批量提取</div>
    <el-alert type="info" :closable="false"
      title="通过 JQL 查询或手动输入 Jira 号，批量提取触发时间（评论/字段 → 视频OCR → 图片OCR），20条一批写入云端"></el-alert>

    <el-tabs v-model="activeTab" style="margin-top:12px">
      <!-- ====== Tab 1: JQL/手动提取 ====== -->
      <el-tab-pane label="JQL/手动提取" name="jql">

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
      </el-tab-pane>

      <!-- ====== Tab 2: 表格提取 ====== -->
      <el-tab-pane label="表格提取" name="table">
        <el-card shadow="never">
          <el-alert type="info" :closable="false" show-icon
            title="上传 Excel/CSV 文件，自动识别 Jira 号和问题发生时间列，提取触发时间后与表格时间对比（差值≤5分钟视为一致）。结果仅保存本地，不写入云端。"></el-alert>
          <div style="display:flex;gap:12px;align-items:flex-start;margin-top:12px">
            <el-upload ref="tableUploadRef" :auto-upload="false" :show-file-list="false"
              accept=".xlsx,.xls,.csv" :on-change="onTableFileChange">
              <el-button type="primary" plain>选择文件</el-button>
            </el-upload>
            <div v-if="tableExtract.fileName" style="font-size:12px;color:#909399">
              {{ tableExtract.fileName }}
              <template v-if="tableExtract.colInfo"> — 识别: Jira列="{{ tableExtract.colInfo.jiraCol }}"，时间列="{{ tableExtract.colInfo.timeCol || '未识别' }}"，{{ tableExtract.total }} 条</template>
            </div>
          </div>
        </el-card>

        <!-- 执行按钮 + 进度 -->
        <div style="margin-top:14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap">
          <el-button type="primary" :loading="tableExtract.running" :disabled="!tableExtract.file" @click="startTableExtract">开始对比提取</el-button>
          <el-button @click="tableExtract.file = null; tableExtract.fileName = ''; tableExtract.rows = []; tableExtract.colInfo = null">清空</el-button>
          <span v-if="tableExtract.statusMsg" style="font-size:13px;color:#606266">{{ tableExtract.statusMsg }}</span>
        </div>
        <div v-if="tableExtract.total > 0" style="margin-top:10px">
          <el-progress :percentage="tablePct" :stroke-width="18" :text-inside="true" :status="tableProgressStatus"></el-progress>
          <div style="margin-top:6px;font-size:12px;color:#909399;display:flex;gap:16px">
            <span>完成: {{ tableExtract.doneCount }}/{{ tableExtract.total }}</span>
            <span style="color:#67c23a">一致: {{ tableExtract.matched }}</span>
            <span style="color:#e6a23c">不一致: {{ tableExtract.unmatched }}</span>
            <span style="color:#f56c6c">失败: {{ tableExtract.failed }}</span>
          </div>
        </div>

        <!-- 结果表格 -->
        <el-card v-if="tableExtract.rows.length" shadow="never" style="margin-top:14px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
            <span style="font-weight:600">对比结果（共 {{ tableExtract.rows.length }} 条）</span>
            <el-tag v-if="tableExtract.savedPath" type="success" size="small">已保存: {{ tableExtract.savedPath }}</el-tag>
          </div>
          <el-table :data="tableExtract.rows" size="small" stripe border max-height="400">
            <el-table-column type="index" label="#" width="50" align="center"></el-table-column>
            <el-table-column prop="bugid" label="Jira号" width="140">
              <template #default="{ row }">
                <span style="font-weight:600;color:#409eff">{{ row.bugid }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="table_time" label="表格时间" width="170" show-overflow-tooltip></el-table-column>
            <el-table-column prop="extracted_time" label="提取时间" width="170">
              <template #default="{ row }">
                <span :style="row.extracted_time ? 'color:#67c23a' : 'color:#c0c4cc'">{{ row.extracted_time || '—' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="对比结果" width="90" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.match === '成功'" type="success" size="small">成功</el-tag>
                <el-tag v-else-if="row.match === '不一致'" type="warning" size="small">不一致</el-tag>
                <el-tag v-else-if="row.match === '失败'" type="danger" size="small">失败</el-tag>
                <el-tag v-else type="info" size="small">{{ row.match || '—' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="source" label="提取来源" width="110" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.source === '标准提取'" type="success" size="small">标准提取</el-tag>
                <el-tag v-else-if="row.source && row.source.includes('视频')" type="warning" size="small">{{ row.source }}</el-tag>
                <el-tag v-else-if="row.source === '图片OCR'" size="small">图片OCR</el-tag>
                <el-tag v-else type="info" size="small">{{ row.source || '—' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="remark" label="备注" min-width="140" show-overflow-tooltip>
              <template #default="{ row }"><span style="color:#f56c6c">{{ row.remark || '' }}</span></template>
            </el-table-column>
          </el-table>
        </el-card>

        <el-empty v-if="!tableExtract.running && !tableExtract.rows.length" description="上传 Excel/CSV 文件后点击开始对比提取" style="margin-top:30px"></el-empty>
      </el-tab-pane>
    </el-tabs>
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
      activeTab: 'jql',
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
      tableExtract: {
        file: null as File | null,
        fileName: '',
        running: false,
        total: 0,
        doneCount: 0,
        matched: 0,
        unmatched: 0,
        failed: 0,
        statusMsg: '',
        rows: [] as any[],
        colInfo: null as any,
        savedPath: '',
      },
    };
  },
  computed: {
    pct() { return this.total ? Math.round((this.doneCount / this.total) * 100) : 0; },
    progressStatus() {
      if (this.doneCount < this.total) return undefined;
      return this.hitCount > 0 ? 'success' : 'warning';
    },
    tablePct() { return this.tableExtract.total ? Math.round((this.tableExtract.doneCount / this.tableExtract.total) * 100) : 0; },
    tableProgressStatus() {
      if (this.tableExtract.doneCount < this.tableExtract.total) return undefined;
      return this.tableExtract.failed === 0 ? 'success' : 'warning';
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
    // ===== 表格提取相关 =====
    onTableFileChange(uploadFile: any) {
      if (!uploadFile || !uploadFile.raw) return;
      this.tableExtract.file = uploadFile.raw;
      this.tableExtract.fileName = uploadFile.name;
      this.tableExtract.rows = [];
      this.tableExtract.colInfo = null;
      this.tableExtract.savedPath = '';
      this.tableExtract.total = 0;
      this.tableExtract.doneCount = 0;
      this.tableExtract.matched = 0;
      this.tableExtract.unmatched = 0;
      this.tableExtract.failed = 0;
      this.tableExtract.statusMsg = '';
    },
    async startTableExtract() {
      if (!this.tableExtract.file) return ElMessage.warning('请先选择文件');
      this.tableExtract.running = true;
      this.tableExtract.rows = [];
      this.tableExtract.doneCount = 0;
      this.tableExtract.matched = 0;
      this.tableExtract.unmatched = 0;
      this.tableExtract.failed = 0;
      this.tableExtract.savedPath = '';
      this.tableExtract.statusMsg = '正在解析文件...';

      const formData = new FormData();
      formData.append('file', this.tableExtract.file);

      try {
        const resp = await fetch('/api/trigger/compare_extract_time', {
          method: 'POST', body: formData,
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
              this.handleTableSSE(evt);
            } catch { /* ignore */ }
          }
        }
      } catch (e: any) {
        this.tableExtract.statusMsg = '执行失败: ' + e.message;
        ElMessage.error('对比提取失败: ' + e.message);
      } finally {
        this.tableExtract.running = false;
      }
    },
    handleTableSSE(evt: any) {
      if (evt.type === 'start') {
        this.tableExtract.total = evt.total;
        this.tableExtract.colInfo = { jiraCol: evt.jira_col, timeCol: evt.time_col };
        this.tableExtract.statusMsg = `共 ${evt.total} 条待对比，并行 2 个...`;
      } else if (evt.type === 'progress') {
        this.tableExtract.doneCount = evt.current;
        if (evt.match === '成功') this.tableExtract.matched++;
        else if (evt.match === '不一致' || evt.match === '无法对比') this.tableExtract.unmatched++;
        else this.tableExtract.failed++;
        this.tableExtract.statusMsg = `对比中 ${evt.current}/${evt.total}`;
        this.tableExtract.rows.push({
          bugid: evt.bugid, table_time: evt.table_time,
          extracted_time: evt.extracted_time, match: evt.match,
          source: evt.source, remark: evt.remark || '',
        });
      } else if (evt.type === 'done') {
        this.tableExtract.savedPath = evt.saved_path || '';
        this.tableExtract.statusMsg = evt.message || '对比完成';
      } else if (evt.type === 'error') {
        this.tableExtract.statusMsg = evt.message || '解析失败';
        ElMessage.error(evt.message || '解析失败');
      }
    },
  },
};
</script>
