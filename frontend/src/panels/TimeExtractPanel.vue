<template>
  <div class="test-panel">
    <div class="section-title">时间批量提取</div>
    <el-alert type="info" :closable="false"
      title="通过 JQL 查询或手动输入 Jira 号，批量提取触发时间（评论/字段 → 视频OCR → 图片OCR），20条一批写入云端"></el-alert>

    <el-tabs v-model="activeTab" type="border-card" class="time-tabs" style="margin-top:12px">
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
              <template v-if="tableExtract.colInfo"> — 识别: Jira列="{{ tableExtract.colInfo.jiraCol }}"，时间列="{{ tableExtract.colInfo.timeCol || '未识别' }}"，描述列="{{ tableExtract.colInfo.descCol || '未识别' }}"，状态列="{{ tableExtract.colInfo.statusCol || '未识别' }}"，共 {{ tableExtract.total }} 条<template v-if="tableExtract.filtered > 0">（已筛选 {{ tableExtract.filtered }} 条）</template></template>
            </div>
          </div>
        </el-card>

        <!-- 筛选条件 -->
        <el-card v-if="tableExtract.fileName" shadow="never" style="margin-top:12px">
          <div style="display:flex;gap:16px;align-items:center;flex-wrap:wrap">
            <span style="font-size:13px;font-weight:600;color:#303133">状态筛选：</span>
            <el-input v-model="tableExtract.statusFilter" placeholder="输入状态，逗号分隔，如：完成,分析失败" size="small" style="width:300px"
              @keydown.enter="startTableExtract"
              :disabled="tableExtract.running"></el-input>
            <el-tag v-if="tableExtract.statusFilter" type="primary" size="small">{{ tableExtract.statusFilter }}</el-tag>
            <span style="font-size:12px;color:#909399">为空则处理全部</span>
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
            <el-table-column prop="desc" label="问题描述" min-width="180" show-overflow-tooltip>
              <template #default="{ row }">
                <span style="font-size:12px;">{{ row.desc || '—' }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="status" label="完成状态" width="90" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.status === '完成'" type="success" size="small">{{ row.status }}</el-tag>
                <el-tag v-else-if="row.status === '分析失败'" type="danger" size="small">{{ row.status }}</el-tag>
                <el-tag v-else-if="row.status" type="info" size="small">{{ row.status }}</el-tag>
                <span v-else style="color:#c0c4cc">—</span>
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
            <el-table-column label="时间判定" width="110" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.judge" :type="judgeTagType(row.judge)" size="small" effect="light">
                  {{ row.judge }}
                </el-tag>
                <span v-else style="color:#bbb">—</span>
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

      <!-- ====== Tab 3: 链接提取 ====== -->
      <el-tab-pane label="链接提取" name="link">
        <el-card shadow="never">
          <el-alert type="info" :closable="false" show-icon
            title="粘贴云端多维表格链接，选择表格后提取时间并对比；对比完可一键写回锚点、或批量写入云端触发时间表。"></el-alert>
          <div style="display:flex;gap:8px;margin-top:12px;align-items:center">
            <el-input v-model="linkExtract.url" placeholder="https://xxx.feishu.cn/base/xxxx?table=tblxxxx" style="flex:1"
              @keydown.enter="parseLinkTables"></el-input>
            <el-button type="primary" plain :loading="linkExtract.parsing" @click="parseLinkTables">解析表格</el-button>
          </div>
          <div v-if="linkExtract.tables.length" style="margin-top:10px;display:flex;gap:8px;align-items:center">
            <span style="font-size:13px;color:#606266">选择表格：</span>
            <el-select v-model="linkExtract.tableId" style="width:360px" placeholder="请选择表格">
              <el-option v-for="t in linkExtract.tables" :key="t.table_id" :label="t.name" :value="t.table_id"></el-option>
            </el-select>
          </div>
        </el-card>

        <div style="margin-top:14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap">
          <el-button type="primary" :loading="linkExtract.running" :disabled="!linkExtract.tableId" @click="startLinkExtract">开始对比提取</el-button>
          <el-button @click="clearLinkExtract">清空</el-button>
          <span v-if="linkExtract.statusMsg" style="font-size:13px;color:#606266">{{ linkExtract.statusMsg }}</span>
          <div style="margin-left:auto;display:flex;gap:8px">
            <el-button type="warning" :disabled="!linkWriteCount || linkExtract.running" @click="writeBackLink">一键写回</el-button>
            <el-button type="success" :disabled="!linkWriteCount || linkExtract.running" @click="writeLinkToCloud">一键写入云端</el-button>
          </div>
        </div>

        <div v-if="linkExtract.total > 0" style="margin-top:10px">
          <el-progress :percentage="linkPct" :stroke-width="18" :text-inside="true"></el-progress>
          <div style="margin-top:6px;font-size:12px;color:#909399;display:flex;gap:16px">
            <span>完成: {{ linkExtract.doneCount }}/{{ linkExtract.total }}</span>
            <span style="color:#67c23a">一致: {{ linkExtract.matched }}</span>
            <span style="color:#e6a23c">不一致: {{ linkExtract.unmatched }}</span>
            <span style="color:#f56c6c">失败: {{ linkExtract.failed }}</span>
          </div>
        </div>

        <el-card v-if="linkExtract.rows.length" shadow="never" style="margin-top:14px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
            <span style="font-weight:600">对比结果（共 {{ linkExtract.rows.length }} 条）</span>
            <el-tag v-if="linkExtract.savedPath" type="success" size="small">已保存: {{ linkExtract.savedPath }}</el-tag>
          </div>
          <el-table :data="linkExtract.rows" size="small" stripe border max-height="420">
            <el-table-column type="index" label="#" width="50" align="center"></el-table-column>
            <el-table-column prop="bugid" label="Jira号" width="140">
              <template #default="{ row }"><span style="font-weight:600;color:#409eff">{{ row.bugid }}</span></template>
            </el-table-column>
            <el-table-column prop="desc" label="问题描述" min-width="180" show-overflow-tooltip></el-table-column>
            <el-table-column prop="status" label="状态" width="90" align="center"></el-table-column>
            <el-table-column prop="table_time" label="表格时间" width="160"></el-table-column>
            <el-table-column prop="extracted_time" label="提取时间" width="170">
              <template #default="{ row }"><span :style="row.extracted_time ? 'color:#67c23a' : 'color:#c0c4cc'">{{ row.extracted_time || '—' }}</span></template>
            </el-table-column>
            <el-table-column label="对比结果" width="90" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.match === '成功'" type="success" size="small">成功</el-tag>
                <el-tag v-else-if="row.match === '不一致'" type="warning" size="small">不一致</el-tag>
                <el-tag v-else-if="row.match === '失败'" type="danger" size="small">失败</el-tag>
                <el-tag v-else type="info" size="small">{{ row.match || '—' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="judge" label="时间判定" width="110" align="center"></el-table-column>
            <el-table-column prop="source" label="提取来源" width="110" align="center"></el-table-column>
            <el-table-column prop="remark" label="备注" min-width="150" show-overflow-tooltip></el-table-column>
          </el-table>
        </el-card>
        <el-empty v-if="!linkExtract.running && !linkExtract.rows.length" description="解析表格并选择后，点击开始对比提取" style="margin-top:30px"></el-empty>
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
        filtered: 0,
        statusMsg: '',
        rows: [] as any[],
        colInfo: null as any,
        savedPath: '',
        statusFilter: '',
      },
      linkExtract: {
        url: '', parsing: false, tables: [] as any[], tableId: '',
        running: false, total: 0, doneCount: 0, matched: 0, unmatched: 0, failed: 0,
        statusMsg: '', rows: [] as any[], savedPath: '',
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
    linkPct() { return this.linkExtract.total ? Math.round((this.linkExtract.doneCount / this.linkExtract.total) * 100) : 0; },
    linkWriteCount() {
      return this.linkExtract.rows.filter(r => r.match === '不一致' && r.extracted_time).length;
    },
  },
  methods: {
    judgeTagType(judge: string) {
      const map: Record<string, string> = {
        '正常': 'success',
        '表格错误': 'warning',
        '提取错误': 'danger',
        '两边都错': 'danger',
        '日期待确认': 'warning',
        '待确认': 'info',
        '提取失败': 'danger',
      };
      return map[judge] || 'info';
    },
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
      if (this.tableExtract.statusFilter) {
        formData.append('filter_statuses', this.tableExtract.statusFilter);
      }

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
        this.tableExtract.colInfo = { jiraCol: evt.jira_col, timeCol: evt.time_col, descCol: evt.desc_col, statusCol: evt.status_col };
        this.tableExtract.filtered = evt.filtered || 0;
        this.tableExtract.statusMsg = `共 ${evt.total} 条待对比` + (this.tableExtract.filtered ? `（已筛选 ${this.tableExtract.filtered} 条）` : '') + `，并行 2 个...`;
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
          desc: evt.desc || '', status: evt.status || '',
        });
      } else if (evt.type === 'done') {
        this.tableExtract.savedPath = evt.saved_path || '';
        this.tableExtract.statusMsg = evt.message || '对比完成';
      } else if (evt.type === 'error') {
        this.tableExtract.statusMsg = evt.message || '解析失败';
        ElMessage.error(evt.message || '解析失败');
      }
    },

    async parseLinkTables() {
      const url = (this.linkExtract.url || '').trim();
      if (!url) { ElMessage.warning('请输入云端表格链接'); return; }
      this.linkExtract.parsing = true;
      try {
        const data = await api('/api/trigger/link_tables', { method: 'POST', body: JSON.stringify({ url }) });
        if (!data.ok) { ElMessage.error(data.message || '解析失败'); return; }
        this.linkExtract.tables = data.data || [];
        if (this.linkExtract.tables.length === 1) this.linkExtract.tableId = this.linkExtract.tables[0].table_id;
        ElMessage.success(`解析到 ${this.linkExtract.tables.length} 个表格`);
      } catch (e) {
        ElMessage.error('解析失败: ' + e.message);
      } finally {
        this.linkExtract.parsing = false;
      }
    },
    clearLinkExtract() {
      this.linkExtract.rows = []; this.linkExtract.total = 0; this.linkExtract.doneCount = 0;
      this.linkExtract.matched = 0; this.linkExtract.unmatched = 0; this.linkExtract.failed = 0;
      this.linkExtract.statusMsg = ''; this.linkExtract.savedPath = '';
    },
    linkAppToken() {
      const m = (this.linkExtract.url || '').match(/\/base\/([A-Za-z0-9]+)/);
      return m ? m[1] : '';
    },
    async startLinkExtract() {
      if (!this.linkExtract.tableId) { ElMessage.warning('请先选择表格'); return; }
      const app = this.linkAppToken();
      if (!app) { ElMessage.error('链接中未找到 base token'); return; }
      this.clearLinkExtract();
      this.linkExtract.running = true;
      this.linkExtract.statusMsg = '读取表格中...';
      try {
        const resp = await fetch('/api/trigger/link_compare', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ app_token: app, table_id: this.linkExtract.tableId }),
        });
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const parts = buffer.split('\n\n'); buffer = parts.pop() || '';
          for (const part of parts) {
            const line = part.split('\n').find(l => l.startsWith('data: '));
            if (!line) continue;
            let evt; try { evt = JSON.parse(line.slice(6)); } catch { continue; }
            if (evt.type === 'start') {
              this.linkExtract.total = evt.total;
              this.linkExtract.statusMsg = `共 ${evt.total} 条待对比...`;
            } else if (evt.type === 'progress') {
              this.linkExtract.doneCount = evt.current;
              if (evt.match === '成功') this.linkExtract.matched++;
              else if (evt.match === '不一致' || evt.match === '无法对比') this.linkExtract.unmatched++;
              else this.linkExtract.failed++;
              this.linkExtract.rows.push(evt);
              this.linkExtract.statusMsg = `对比中 ${evt.current}/${evt.total}`;
            } else if (evt.type === 'done') {
              this.linkExtract.savedPath = evt.saved_path || '';
              this.linkExtract.statusMsg = `完成：${evt.matched} 成功，${evt.unmatched} 不一致，${evt.failed} 失败`;
            } else if (evt.type === 'error') {
              this.linkExtract.statusMsg = evt.message;
              ElMessage.error(evt.message);
            }
          }
        }
      } catch (e) {
        ElMessage.error('对比失败: ' + e.message);
      } finally {
        this.linkExtract.running = false;
      }
    },
    async writeBackLink() {
      const items = this.linkExtract.rows.filter(r => r.match === '不一致' && r.extracted_time)
        .map(r => ({ record_id: r.record_id, bugid: r.bugid, time: r.extracted_time }));
      if (!items.length) { ElMessage.warning('没有可写回的不一致时间'); return; }
      const app = this.linkAppToken();
      try {
        const data = await api('/api/trigger/link_writeback', {
          method: 'POST',
          body: JSON.stringify({ app_token: app, table_id: this.linkExtract.tableId, items }),
        });
        if (data.ok) ElMessage.success(`已写回 ${data.data?.count ?? items.length} 条`);
        else ElMessage.error(data.message || '写回失败');
      } catch (e) { ElMessage.error('写回失败: ' + e.message); }
    },
    async writeLinkToCloud() {
      const items = this.linkExtract.rows.filter(r => r.extracted_time)
        .map(r => ({ bugid: r.bugid, time: r.extracted_time }));
      if (!items.length) { ElMessage.warning('没有可写入的时间'); return; }
      try {
        const data = await api('/api/trigger/link_to_trigger', {
          method: 'POST', body: JSON.stringify({ items }),
        });
        if (data.ok) ElMessage.success(`已写入云端 ${data.data?.count ?? items.length} 条，表 ${data.data?.table_id || ''}`);
        else ElMessage.error(data.message || '写入失败');
      } catch (e) { ElMessage.error('写入失败: ' + e.message); }
    },
  },
};
</script>

<style scoped>
.test-panel { padding: 0; }
.section-title { font-size: 16px; font-weight: 600; margin-bottom: 10px; color: #303133; }
.time-tabs { border-radius: 8px; }
.time-tabs :deep(.el-tabs__content) { padding: 16px; overflow: visible; }
</style>
