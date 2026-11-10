<template>
  <div class="test-panel">
    <div class="section-title">Jira 查询</div>
    <el-tabs v-model="activeTab" type="card">

      <!-- ==================== Jira查询（原有功能） ==================== -->
      <el-tab-pane label="Jira查询" name="jira">
        <el-alert type="info" :closable="false"
          title="通过 Jira 号或 JQL 语句查询 Bug 概要及根因，支持批量输入（逗号/空格/换行分隔）。"></el-alert>

        <el-card shadow="never" style="margin-top:12px">
          <div class="input-row" style="display:flex;gap:10px;align-items:flex-start">
            <el-input v-model="query" type="textarea" :rows="3"
              placeholder="输入 Jira 号（如 VCU-12345）或 JQL（如 summary ~ &quot;全屏手写页面与dock栏有缝隙&quot;）"
              @keydown.ctrl.enter="doLookup" @keydown.meta.enter="doLookup"></el-input>
            <div style="display:flex;flex-direction:column;gap:8px">
              <el-button type="primary" :loading="loading" @click="doLookup">查询</el-button>
              <el-button @click="query=''">清空</el-button>
            </div>
          </div>
          <div class="preset-bar" style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;align-items:center">
            <el-button size="small" type="danger" :loading="todayBugLoading" @click="queryTodayNewBugs">今日新增 Bug</el-button>
            <el-button size="small" type="warning" :loading="yesterdayBugLoading" @click="queryYesterdayNewBugs">昨日新增 Bug</el-button>
            <el-button size="small" type="success" :loading="weekBugLoading" @click="queryWeekNewBugs">本周新增 Bug</el-button>
            <el-button size="small" type="info" :loading="lastWeekBugLoading" @click="queryLastWeekNewBugs">上周新增 Bug</el-button>
            <el-button size="small" type="primary" @click="fillSummaryQuery">描述查 Jira 号</el-button>
            <el-divider direction="vertical" style="margin:0 4px"></el-divider>
            <el-checkbox v-model="filterAiPreliminary" size="small">过滤AI初步分析结果</el-checkbox>
          </div>
        </el-card>

        <el-card v-if="rows.length || errors.length" shadow="never" style="margin-top:14px">
          <div style="display:flex;align-items:center;gap:12px;margin-bottom:10px;flex-wrap:wrap">
            <span class="section-title" style="margin:0">查询结果</span>
            <div class="stat-bar" style="display:flex;gap:6px;align-items:center">
              <el-tag type="info" size="small">总数 <b>{{ rows.length }}</b></el-tag>
              <el-tag type="warning" size="small">待执行 <b>{{ pendingCount }}</b></el-tag>
              <el-tag type="success" size="small">已分析 <b>{{ analyzedCount }}</b></el-tag>
              <el-tag v-if="errors.length" type="danger" size="small">失败 {{ errors.length }}</el-tag>
            </div>
            <el-tag type="info" size="small">{{ mode === 'jql' ? 'JQL 模式' : 'Key 模式' }}</el-tag>
            <div style="margin-left:auto;display:flex;gap:8px;align-items:center">
              <el-button size="small" link type="primary" @click="copyAllKeys">复制所有 Key</el-button>
            </div>
          </div>

          <el-table :data="displayedRows" size="small" stripe border max-height="520"
            :default-sort="{ prop: 'key', order: 'ascending' }">
            <el-table-column prop="key" label="Jira 号" width="150" sortable>
              <template #default="{ row }">
                <span style="font-weight:600;color:#409eff">{{ row.key }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="summary" label="概要" min-width="320" show-overflow-tooltip>
              <template #default="{ row }"><span>{{ row.summary }}</span></template>
            </el-table-column>
            <el-table-column prop="status" label="状态" width="110" sortable>
              <template #default="{ row }">
                <el-tag size="small" :type="statusType(row.status)">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created" label="创建日期" width="120" sortable></el-table-column>
            <el-table-column prop="has_ai_preliminary" label="AI初步" width="80" align="center" sortable>
              <template #default="{ row }">
                <el-tag :type="row.has_ai_preliminary ? 'success' : 'info'" size="small">{{ row.has_ai_preliminary ? '有' : '无' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="root_cause" label="根本原因" min-width="320" show-overflow-tooltip>
              <template #default="{ row }">
                <span :style="{ color: row.root_cause && row.root_cause !== '（未填写）' ? '#67c23a' : '#c0c4cc' }">
                  {{ row.root_cause }}
                </span>
              </template>
            </el-table-column>
          </el-table>

          <template v-if="errors.length">
            <div style="margin-top:14px;font-weight:600;color:#f56c6c;font-size:13px">查询失败</div>
            <el-table :data="errors" size="small" stripe border style="margin-top:6px">
              <el-table-column prop="key" label="Jira 号" width="180"></el-table-column>
              <el-table-column prop="error" label="错误信息" min-width="400"></el-table-column>
            </el-table>
          </template>
        </el-card>

        <el-empty v-else-if="!loading && queried" description="未查询到任何结果，请检查输入" style="margin-top:20px"></el-empty>
        <el-empty v-else-if="!loading" description="输入 Jira 号或 JQL，按 Ctrl+Enter 查询" style="margin-top:20px"></el-empty>
      </el-tab-pane>

      <!-- ==================== 表格查询（新增） ==================== -->
      <el-tab-pane label="表格查询" name="table">
        <el-alert type="info" :closable="false"
          title="从 VCS BUG 多维表格按创建日期查询记录，支持快捷时间范围和AI初步分析结果过滤。"></el-alert>

        <el-card shadow="never" style="margin-top:12px">
          <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">
            <el-button type="danger" size="small" :loading="tbl.loading" @click="tblQueryToday">今日</el-button>
            <el-button type="warning" size="small" :loading="tbl.loading" @click="tblQueryYesterday">昨日</el-button>
            <el-button type="success" size="small" :loading="tbl.loading" @click="tblQueryThisWeek">本周</el-button>
            <el-button type="info" size="small" :loading="tbl.loading" @click="tblQueryLastWeek">上周</el-button>
            <el-divider direction="vertical" style="margin:0 4px"></el-divider>
            <span style="font-size:13px;color:#606266">自定义范围</span>
            <el-date-picker v-model="tbl.dateRange" type="daterange" size="small"
              range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期"
              value-format="YYYY-MM-DD" style="width:260px"
              @change="onDateRangeChange"></el-date-picker>
            <el-button type="primary" size="small" :loading="tbl.loading" @click="tblQueryCustom">查询</el-button>
            <el-divider direction="vertical" style="margin:0 4px"></el-divider>
            <el-checkbox v-model="tbl.filterAi" size="small">过滤AI初步分析结果</el-checkbox>
          </div>
        </el-card>

        <el-card v-if="tbl.rows.length" shadow="never" style="margin-top:14px">
          <div style="display:flex;align-items:center;gap:12px;margin-bottom:10px;flex-wrap:wrap">
            <span class="section-title" style="margin:0">查询结果</span>
            <div class="stat-bar" style="display:flex;gap:6px;align-items:center">
              <el-tag type="info" size="small">总数 <b>{{ tbl.rows.length }}</b></el-tag>
              <el-tag type="warning" size="small">待分析 <b>{{ tblPendingCount }}</b></el-tag>
              <el-tag type="success" size="small">已分析 <b>{{ tblAnalyzedCount }}</b></el-tag>
            </div>
            <el-tag v-if="tbl.dateLabel" type="info" size="small">{{ tbl.dateLabel }}</el-tag>
            <div style="margin-left:auto;display:flex;gap:8px;align-items:center">
              <el-button size="small" link type="primary" @click="tblCopyAllKeys">复制所有 Jira 号</el-button>
            </div>
          </div>

          <el-table :data="tblDisplayedRows" size="small" stripe border max-height="520"
            :default-sort="{ prop: '创建日期', order: 'descending' }">
            <el-table-column type="index" label="#" width="50" align="center"></el-table-column>
            <el-table-column prop="jira号" label="Jira号" width="180" sortable>
              <template #default="{ row }">
                <span style="font-weight:600;color:#409eff">{{ row['jira号'] }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="创建日期" label="创建日期" width="180" sortable></el-table-column>
            <el-table-column prop="AI初步分析结果" label="AI初步分析结果" min-width="400" show-overflow-tooltip>
              <template #default="{ row }">
                <span :style="{ color: row['AI初步分析结果'] && row['AI初步分析结果'] !== '-' ? '#67c23a' : '#c0c4cc' }">
                  {{ row['AI初步分析结果'] || '-' }}
                </span>
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <el-empty v-else-if="!tbl.loading && tbl.queried" description="未查询到任何记录" style="margin-top:20px"></el-empty>
        <el-empty v-else-if="!tbl.loading" description="点击快捷按钮或选择日期范围后查询" style="margin-top:20px"></el-empty>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script lang="ts">
// @ts-nocheck
import { ElMessage } from 'element-plus';
import { api } from '../composables/utils';

export default {
  name: 'JiraLookupPanel',
  data() {
    return {
      activeTab: 'jira',
      // ─── Jira查询（原有） ───
      query: '',
      loading: false,
      lastLookupAt: {} as Record<string, number>,
      queried: false,
      todayBugLoading: false,
      yesterdayBugLoading: false,
      weekBugLoading: false,
      lastWeekBugLoading: false,
      filterAiPreliminary: true,
      rows: [] as any[],
      errors: [] as any[],
      mode: 'keys',
      // ─── 表格查询（新增） ───
      tbl: {
        loading: false,
        queried: false,
        dateRange: null as [string, string] | null,
        filterAi: true,
        rows: [] as any[],
        dateLabel: '',
      },
    };
  },
  computed: {
    // Jira查询 computed
    displayedRows() {
      if (!this.filterAiPreliminary) return this.rows;
      return this.rows.filter((r: any) => !r.has_ai_preliminary);
    },
    analyzedCount() {
      return this.rows.filter((r: any) => r.has_ai_preliminary).length;
    },
    pendingCount() {
      return this.rows.length - this.analyzedCount;
    },
    // 表格查询 computed
    tblDisplayedRows() {
      if (!this.tbl.filterAi) return this.tbl.rows;
      return this.tbl.rows.filter((r: any) => !r['AI初步分析结果'] || r['AI初步分析结果'] === '-');
    },
    tblAnalyzedCount() {
      return this.tbl.rows.filter((r: any) => r['AI初步分析结果'] && r['AI初步分析结果'] !== '-' && r['AI初步分析结果'] !== '').length;
    },
    tblPendingCount() {
      return this.tbl.rows.length - this.tblAnalyzedCount;
    },
  },
  methods: {
    // ─── Jira查询 methods（原有逻辑不变） ───
    statusType(s: string) {
      const st = (s || '').toLowerCase();
      if (st.includes('closed') || st.includes('完成') || st.includes('已关闭')) return 'success';
      if (st.includes('progress') || st.includes('进行')) return '';
      if (st.includes('reopen') || st.includes('重开')) return 'warning';
      if (st.includes('todo') || st.includes('待')) return 'info';
      return 'info';
    },
    fillSummaryQuery() {
      this.query = 'summary ~ "全屏手写页面与dock栏有缝隙" AND project = VCS_Info4.0_High_Platform_PATAC_Jira';
      setTimeout(() => {
        const el = document.querySelector('textarea');
        if (el) {
          el.focus();
          const len = this.query.length;
          (el as HTMLTextAreaElement).setSelectionRange(len, len);
        }
      }, 30);
    },
    checkLookupCooldown(key: string) {
      const now = Date.now();
      const last = this.lastLookupAt[key] || 0;
      if (now - last < 30000) {
        const left = Math.ceil((30000 - (now - last)) / 1000);
        ElMessage.warning(`操作太频繁，请 ${left} 秒后再试`);
        return false;
      }
      this.lastLookupAt[key] = now;
      return true;
    },
    async doLookup() {
      const q = this.query.trim();
      if (!q) return ElMessage.warning('请输入 Jira 号或 JQL');
      if (!this.checkLookupCooldown('lookup')) return;
      this.loading = true; this.queried = true; this.rows = []; this.errors = [];
      try {
        const result = await api('/api/test/jira_lookup', { method: 'POST', body: JSON.stringify({ query: q }) });
        const data = result.data || {};
        this.rows = data.rows || [];
        this.errors = data.errors || [];
        this.mode = data.mode || 'keys';
        if (!this.rows.length && !this.errors.length) ElMessage.info('未查询到结果');
        else if (this.errors.length) ElMessage.warning(`成功 ${this.rows.length} 条，失败 ${this.errors.length} 条`);
        else ElMessage.success(`成功查询 ${this.rows.length} 条`);
      } catch (e: any) {
        ElMessage.error('查询失败: ' + e.message);
      } finally {
        this.loading = false;
      }
    },
    async queryTodayNewBugs() {
      if (!this.checkLookupCooldown('today')) return;
      const jql = 'created >= startOfDay() AND issuetype = "bug" AND status != "closed" AND project = VCS_Info4.0_High_Platform_PATAC_Jira';
      this.query = jql;
      this.todayBugLoading = true;
      this.loading = true; this.queried = true; this.rows = []; this.errors = [];
      try {
        const result = await api('/api/test/jira_lookup', { method: 'POST', body: JSON.stringify({ query: jql }) });
        const data = result.data || {};
        this.rows = data.rows || [];
        this.errors = data.errors || [];
        this.mode = data.mode || 'jql';
        if (!this.rows.length) ElMessage.info('今日暂无新增 Bug');
        else ElMessage.success(`今日新增 ${this.rows.length} 个 Bug`);
      } catch (e: any) {
        ElMessage.error('查询失败: ' + e.message);
      } finally {
        this.loading = false;
        this.todayBugLoading = false;
      }
    },
    async queryYesterdayNewBugs() {
      if (!this.checkLookupCooldown('yesterday')) return;
      const jql = 'created >= startOfDay("-1d") AND created <= endOfDay("-1d") AND issuetype = "bug" AND status != "closed" AND project = VCS_Info4.0_High_Platform_PATAC_Jira';
      this.query = jql;
      this.yesterdayBugLoading = true;
      this.loading = true; this.queried = true; this.rows = []; this.errors = [];
      try {
        const result = await api('/api/test/jira_lookup', { method: 'POST', body: JSON.stringify({ query: jql }) });
        const data = result.data || {};
        this.rows = data.rows || [];
        this.errors = data.errors || [];
        this.mode = data.mode || 'jql';
        if (!this.rows.length) ElMessage.info('昨日暂无新增 Bug');
        else ElMessage.success(`昨日新增 ${this.rows.length} 个 Bug`);
      } catch (e: any) {
        ElMessage.error('查询失败: ' + e.message);
      } finally {
        this.loading = false;
        this.yesterdayBugLoading = false;
      }
    },
    weekStartDate() {
      const now = new Date();
      const day = now.getDay();
      const diff = (day + 6) % 7;
      const monday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - diff);
      const mm = String(monday.getMonth() + 1).padStart(2, '0');
      const dd = String(monday.getDate()).padStart(2, '0');
      return `${monday.getFullYear()}-${mm}-${dd}`;
    },
    async queryWeekNewBugs() {
      if (!this.checkLookupCooldown('week')) return;
      const jql = `created >= "${this.weekStartDate()}" AND issuetype = "bug" AND status != "closed" AND project = VCS_Info4.0_High_Platform_PATAC_Jira`;
      this.query = jql;
      this.weekBugLoading = true;
      this.loading = true; this.queried = true; this.rows = []; this.errors = [];
      try {
        const result = await api('/api/test/jira_lookup', { method: 'POST', body: JSON.stringify({ query: jql }) });
        const data = result.data || {};
        this.rows = data.rows || [];
        this.errors = data.errors || [];
        this.mode = data.mode || 'jql';
        if (!this.rows.length) ElMessage.info('本周暂无新增 Bug');
        else ElMessage.success(`本周新增 ${this.rows.length} 个 Bug`);
      } catch (e: any) {
        ElMessage.error('查询失败: ' + e.message);
      } finally {
        this.loading = false;
        this.weekBugLoading = false;
      }
    },
    async queryLastWeekNewBugs() {
      if (!this.checkLookupCooldown('lastWeek')) return;
      const jql = 'created >= startOfWeek(-1) AND created < startOfWeek() AND issuetype = "bug" AND status != "closed" AND project = VCS_Info4.0_High_Platform_PATAC_Jira';
      this.query = jql;
      this.lastWeekBugLoading = true;
      this.loading = true; this.queried = true; this.rows = []; this.errors = [];
      try {
        const result = await api('/api/test/jira_lookup', { method: 'POST', body: JSON.stringify({ query: jql }) });
        const data = result.data || {};
        this.rows = data.rows || [];
        this.errors = data.errors || [];
        this.mode = data.mode || 'jql';
        if (!this.rows.length) ElMessage.info('上周暂无新增 Bug');
        else ElMessage.success(`上周新增 ${this.rows.length} 个 Bug`);
      } catch (e: any) {
        ElMessage.error('查询失败: ' + e.message);
      } finally {
        this.loading = false;
        this.lastWeekBugLoading = false;
      }
    },
    copyAllKeys() {
      const list = this.filterAiPreliminary ? this.displayedRows : this.rows;
      if (!list.length) return ElMessage.warning('暂无结果');
      const text = list.map((r: any) => r.key).join(', ');
      navigator.clipboard.writeText(text).then(() => ElMessage.success(`已复制 ${list.length} 个 Key`));
    },

    // ─── 表格查询 methods（新增） ───
    fmtDate(d: Date): string {
      const y = d.getFullYear();
      const m = String(d.getMonth() + 1).padStart(2, '0');
      const dd = String(d.getDate()).padStart(2, '0');
      return `${y}-${m}-${dd}`;
    },
    weekMonday(): Date {
      const now = new Date();
      const day = now.getDay();
      const diff = (day + 6) % 7;
      return new Date(now.getFullYear(), now.getMonth(), now.getDate() - diff);
    },
    async tblDoQuery(dateFrom: string, dateTo: string, label: string) {
      if (!this.checkLookupCooldown('tbl_' + label)) return;
      this.tbl.loading = true;
      this.tbl.queried = true;
      this.tbl.rows = [];
      this.tbl.dateLabel = label;
      try {
        const result = await api('/api/test/bitable_vcs_query', {
          method: 'POST',
          body: JSON.stringify({ date_from: dateFrom, date_to: dateTo, filter_ai: false }),
        });
        const data = result.data || {};
        this.tbl.rows = data.rows || [];
        if (!this.tbl.rows.length) ElMessage.info(`${label}：无记录`);
        else ElMessage.success(`${label}：${this.tbl.rows.length} 条记录`);
      } catch (e: any) {
        ElMessage.error('表格查询失败: ' + e.message);
      } finally {
        this.tbl.loading = false;
      }
    },
    tblQueryToday() {
      const today = this.fmtDate(new Date());
      this.tbl.dateRange = [today, today];
      this.tblDoQuery(today, today, '今日');
    },
    tblQueryYesterday() {
      const y = new Date();
      y.setDate(y.getDate() - 1);
      const yd = this.fmtDate(y);
      this.tbl.dateRange = [yd, yd];
      this.tblDoQuery(yd, yd, '昨日');
    },
    tblQueryThisWeek() {
      const monday = this.weekMonday();
      const now = new Date();
      const from = this.fmtDate(monday);
      const to = this.fmtDate(now);
      this.tbl.dateRange = [from, to];
      this.tblDoQuery(from, to, '本周');
    },
    tblQueryLastWeek() {
      const thisMonday = this.weekMonday();
      const lastMonday = new Date(thisMonday);
      lastMonday.setDate(lastMonday.getDate() - 7);
      const lastSunday = new Date(lastMonday);
      lastSunday.setDate(lastSunday.getDate() + 6);
      const from = this.fmtDate(lastMonday);
      const to = this.fmtDate(lastSunday);
      this.tbl.dateRange = [from, to];
      this.tblDoQuery(from, to, '上周');
    },
    tblQueryCustom() {
      if (!this.tbl.dateRange || !this.tbl.dateRange[0] || !this.tbl.dateRange[1]) {
        return ElMessage.warning('请选择日期范围');
      }
      this.tblDoQuery(this.tbl.dateRange[0], this.tbl.dateRange[1], `${this.tbl.dateRange[0]} ~ ${this.tbl.dateRange[1]}`);
    },
    onDateRangeChange() {
      // 选择范围后自动查询
      if (this.tbl.dateRange && this.tbl.dateRange[0] && this.tbl.dateRange[1]) {
        this.tblQueryCustom();
      }
    },
    tblCopyAllKeys() {
      const list = this.tblDisplayedRows;
      if (!list.length) return ElMessage.warning('暂无结果');
      const text = list.map((r: any) => r['jira号']).join(', ');
      navigator.clipboard.writeText(text).then(() => ElMessage.success(`已复制 ${list.length} 个 Jira 号`));
    },
  },
};
</script>
