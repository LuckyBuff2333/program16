<template>
  <div class="test-panel">
    <div class="section-title">Jira 查询</div>
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
      <div class="preset-bar" style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">
        <el-button size="small" type="danger" :loading="todayBugLoading" @click="queryTodayNewBugs">今日新增 Bug</el-button>
        <el-button size="small" type="primary" @click="fillSummaryQuery">描述查 Jira 号</el-button>
      </div>
    </el-card>

    <el-card v-if="rows.length || errors.length" shadow="never" style="margin-top:14px">
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:10px">
        <span class="section-title" style="margin:0">查询结果</span>
        <el-tag type="success" size="small">成功 {{ rows.length }}</el-tag>
        <el-tag v-if="errors.length" type="danger" size="small">失败 {{ errors.length }}</el-tag>
        <el-tag type="info" size="small">{{ mode === 'jql' ? 'JQL 模式' : 'Key 模式' }}</el-tag>
        <el-button size="small" link type="primary" style="margin-left:auto" @click="copyAllKeys">复制所有 Key</el-button>
      </div>

      <el-table :data="rows" size="small" stripe border max-height="520"
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
      query: '',
      loading: false,
      queried: false,
      todayBugLoading: false,
      rows: [] as any[],
      errors: [] as any[],
      mode: 'keys',
    };
  },
  methods: {
    statusType(s: string) {
      const st = (s || '').toLowerCase();
      if (st.includes('closed') || st.includes('完成') || st.includes('已关闭')) return 'success';
      if (st.includes('progress') || st.includes('进行')) return '';
      if (st.includes('reopen') || st.includes('重开')) return 'warning';
      if (st.includes('todo') || st.includes('待')) return 'info';
      return 'info';
    },
    fillSummaryQuery() {
      this.query = 'summary ~ "全屏手写页面与dock栏有缝隙"';
      setTimeout(() => {
        const el = document.querySelector('textarea');
        if (el) {
          el.focus();
          const len = this.query.length;
          (el as HTMLTextAreaElement).setSelectionRange(len, len);
        }
      }, 30);
    },
    async doLookup() {
      const q = this.query.trim();
      if (!q) return ElMessage.warning('请输入 Jira 号或 JQL');
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
      const jql = 'created >= startOfDay() AND issuetype = "bug" AND status != "closed"';
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
    copyAllKeys() {
      if (!this.rows.length) return ElMessage.warning('暂无结果');
      const text = this.rows.map(r => r.key).join(', ');
      navigator.clipboard.writeText(text).then(() => ElMessage.success(`已复制 ${this.rows.length} 个 Key`));
    },
  },
};
</script>
