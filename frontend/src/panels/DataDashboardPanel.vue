<template>
  <div class="db-panel">
    <!-- 顶部工具栏 -->
    <div class="db-toolbar">
      <div class="db-toolbar-left">
        <el-date-picker v-model="selectedDate" type="date" value-format="YYYY-MM-DD"
          placeholder="选择日期" style="width:155px" @change="loadDashboard" />
        <el-select v-model="selectedDate" placeholder="快捷选日期" style="width:220px" filterable @change="loadDashboard">
          <el-option v-for="d in dateList" :key="d.date"
            :label="d.date + ' (' + d.batch_count + '批次' + (d.has_daily_report ? ' · 有日报' : '') + ')'"
            :value="d.date" />
        </el-select>
        <el-divider direction="vertical" />
        <el-select v-model="sourceFilter" placeholder="来源" style="width:110px" clearable>
          <el-option label="全部来源" value="" /><el-option label="PC" value="PC" /><el-option label="线上" value="线上" />
        </el-select>
        <el-select v-model="statusFilter" placeholder="状态" style="width:120px" clearable>
          <el-option label="全部状态" value="" /><el-option label="有报告" value="has_report" /><el-option label="无报告" value="no_report" />
        </el-select>
      </div>
      <div class="db-toolbar-right">
        <el-button :loading="dataLoading" @click="loadDashboard" round size="small">
          <span v-if="!dataLoading" style="margin-right:2px">↻</span> 刷新
        </el-button>
        <span v-if="isToday" class="auto-badge"><span class="pulse-dot"></span> 自动刷新</span>
      </div>
    </div>

    <!-- 空状态 -->
    <el-empty v-if="!dataLoading && summary.total_batches === 0" description="该日期无批次数据"
      :image-size="80" style="padding:60px 0" />

    <!-- 批次卡片列表 -->
    <div v-if="filteredBatches.length > 0" class="db-section">
      <div class="db-section-head">
        <span class="db-section-title">批次执行记录</span>
        <span class="db-section-count">{{ filteredBatches.length }} 个批次</span>
      </div>

      <div v-for="(batch, idx) in filteredBatches" :key="batch.name"
        class="db-batch-card" :class="{ 'is-expanded': expandedName === batch.name }">
        <!-- 卡片头 -->
        <div class="db-batch-head" @click="toggleBatch(batch)">
          <div class="db-batch-left">
            <span class="db-batch-idx">{{ idx + 1 }}</span>
            <div class="db-batch-info">
              <span class="db-batch-name">{{ batch.name }}</span>
              <div class="db-batch-meta">
                <el-tag :type="batch.source === 'PC' ? '' : 'warning'" size="small" effect="plain" round>{{ batch.source }}</el-tag>
                <span>{{ batch.exec_time || '-' }}</span>
                <span v-if="batch.model">{{ batch.model }}</span>
              </div>
            </div>
          </div>
          <div class="db-batch-right">
            <div class="db-batch-stats">
              <span class="db-mini-stat">提交 <b>{{ batch.submit_ok }}</b>/{{ batch.total }}</span>
              <template v-if="batch._detail">
                <span class="db-mini-stat" :class="batch._detail.rate >= 70 ? 'ok' : 'warn'">
                  分析 <b>{{ batch._detail.rate }}%</b>
                </span>
                <div class="db-mini-bar">
                  <div class="db-mini-bar-fill db-bar-ok" :style="{ width: batchOkPct(batch) + '%' }"></div>
                  <div class="db-mini-bar-fill db-bar-fail" :style="{ width: batchFailPct(batch) + '%' }"></div>
                </div>
              </template>
            </div>
            <el-tag v-if="batch.has_report" type="success" size="small" effect="plain" round
              class="db-report-tag" @click.stop="openReport(batch)">报告 ↗</el-tag>
            <el-tag v-else-if="batch.all_failed" type="danger" size="small" effect="dark" round>
              全部失败
            </el-tag>
            <el-tag v-else type="info" size="small" effect="plain" round>无报告</el-tag>
            <span class="db-expand-arrow"
              :class="{ 'rotated': expandedName === batch.name, 'is-disabled': batch.all_failed }">▸</span>
          </div>
        </div>

        <!-- 展开详情 -->
        <transition name="db-expand">
          <div v-if="expandedName === batch.name" class="db-batch-body">
            <el-skeleton v-if="batch._detailLoading" :rows="3" animated />
            <template v-else-if="batch._detail">
              <div class="db-detail-grid">
                <!-- 基础信息 -->
                <div class="db-detail-block">
                  <div class="db-detail-title">基础信息</div>
                  <div class="db-kv-list">
                    <div class="db-kv"><span class="db-kv-k">执行时间</span><span class="db-kv-v">{{ batch.exec_time || '-' }}</span></div>
                    <div class="db-kv"><span class="db-kv-k">模型</span><span class="db-kv-v">{{ batch.model || '-' }}</span></div>
                    <div class="db-kv"><span class="db-kv-k">来源</span><span class="db-kv-v">{{ batch.source }}</span></div>
                    <div class="db-kv"><span class="db-kv-k">提交</span><span class="db-kv-v">{{ batch.submit_ok }} / {{ batch.total }}</span></div>
                  </div>
                </div>
                <!-- 匹配进度 -->
                <div class="db-detail-block">
                  <div class="db-detail-title">多维表格匹配</div>
                  <div class="db-match-bar">
                    <div class="db-match-fill db-m-ok" :style="{ width: batchOkPct(batch) + '%' }"></div>
                    <div class="db-match-fill db-m-fail" :style="{ width: batchFailPct(batch) + '%' }"></div>
                    <div class="db-match-fill db-m-miss" :style="{ width: (batch._detail.bt_miss / batch._detail.total * 100) + '%' }"></div>
                  </div>
                  <div class="db-match-legend">
                    <span><i class="db-dot db-dot-ok"></i>成功 {{ batch._detail.bt_ok }}</span>
                    <span><i class="db-dot db-dot-fail"></i>失败 {{ batch._detail.bt_fail }}</span>
                    <span><i class="db-dot db-dot-miss"></i>未匹配 {{ batch._detail.bt_miss }}</span>
                  </div>
                  <div class="db-kv-list" style="margin-top:8px">
                    <div class="db-kv"><span class="db-kv-k">成功率</span>
                      <el-tag :type="batch._detail.rate >= 70 ? 'success' : batch._detail.rate >= 50 ? 'warning' : 'danger'" size="small" round>{{ batch._detail.rate }}%</el-tag>
                    </div>
                  </div>
                </div>
                <!-- 耗时统计 -->
                <div class="db-detail-block">
                  <div class="db-detail-title">耗时统计</div>
                  <div class="db-kv-list">
                    <div class="db-kv"><span class="db-kv-k">平均耗时</span><span class="db-kv-v">{{ batch._detail.avg_dur > 0 ? (batch._detail.avg_dur / 60).toFixed(1) + ' min' : '-' }}</span></div>
                    <div class="db-kv"><span class="db-kv-k">最大耗时</span><span class="db-kv-v">{{ batch._detail.max_dur > 0 ? (batch._detail.max_dur / 60).toFixed(1) + ' min' : '-' }}</span></div>
                  </div>
                </div>
                <!-- 错误归类 -->
                <div v-if="Object.keys(batch._detail.fail_cats || {}).length" class="db-detail-block">
                  <div class="db-detail-title">错误归类</div>
                  <div class="db-fail-tags">
                    <el-tag v-for="(cnt, cat) in batch._detail.fail_cats" :key="cat"
                      type="danger" size="small" round>{{ cat }}：{{ cnt }}</el-tag>
                  </div>
                </div>
              </div>
              <div class="db-detail-actions">
                <el-button v-if="batch.has_report" type="primary" size="small" round @click="openReport(batch)">
                  查看批次报告 ↗
                </el-button>
              </div>
            </template>
          </div>
        </transition>
      </div>
    </div>

    <!-- 日报 -->
    <div v-if="summary.has_daily_report || summary.total_batches > 0" class="db-daily-bar">
      <div class="db-daily-info">
        <span class="db-daily-icon">📊</span>
        <span class="db-daily-label">{{ selectedDate }} 每日综合报告</span>
        <el-tag v-if="summary.has_daily_report" type="success" size="small" round effect="plain">已生成</el-tag>
        <el-tag v-else type="info" size="small" round>未生成</el-tag>
      </div>
      <el-button v-if="summary.has_daily_report" type="success" round size="small" @click="openDailyReport">
        查看日报 ↗
      </el-button>
    </div>
  </div>
</template>

<script lang="ts">
// @ts-nocheck
import { ElMessage } from 'element-plus';
import { api } from '../composables/utils';

const REFRESH_INTERVAL = 30 * 60 * 1000;

export default {
  name: 'DataDashboardPanel',
  data() {
    return {
      selectedDate: new Date().toISOString().slice(0, 10),
      dateList: [],
      datesLoading: false,
      dataLoading: false,
      sourceFilter: '',
      statusFilter: '',
      summary: { total_batches: 0, total_submit: 0, total_ok: 0, total_fail: 0, pc_batches: 0, online_batches: 0, submit_rate: 0, has_daily_report: false },
      batches: [],
      dashDetail: { bt_match: 0, bt_ok: 0, bt_fail: 0 },
      expandedName: '',
      refreshTimer: null,
    };
  },
  computed: {
    isToday() { return this.selectedDate === new Date().toISOString().slice(0, 10); },
    filteredBatches() {
      let list = this.batches;
      if (this.sourceFilter) list = list.filter(b => b.source === this.sourceFilter);
      if (this.statusFilter === 'has_report') list = list.filter(b => b.has_report);
      else if (this.statusFilter === 'no_report') list = list.filter(b => !b.has_report);
      return list;
    },
  },
  mounted() { this.loadDates(); this.loadDashboard(); this.startAutoRefresh(); },
  beforeUnmount() { this.stopAutoRefresh(); },
  methods: {
    batchOkPct(b) { return b._detail && b._detail.total > 0 ? (b._detail.bt_ok / b._detail.total * 100).toFixed(1) : 0; },
    batchFailPct(b) { return b._detail && b._detail.total > 0 ? (b._detail.bt_fail / b._detail.total * 100).toFixed(1) : 0; },
    async loadDates() {
      this.datesLoading = true;
      try { const r = await api('/api/dashboard/dates'); this.dateList = r.data || []; } catch (_) {} finally { this.datesLoading = false; }
    },
    async loadDashboard() {
      this.dataLoading = true;
      try {
        const r = await api(`/api/dashboard/data?date=${this.selectedDate}`);
        this.summary = r.data.summary || { total_batches: 0, total_submit: 0, total_ok: 0, total_fail: 0, pc_batches: 0, online_batches: 0, submit_rate: 0, has_daily_report: false };
        this.batches = (r.data.batches || []).map(b => ({ ...b, _detail: null, _detailLoading: false }));
        this.dashDetail = { bt_match: 0, bt_ok: 0, bt_fail: 0 };
        this.expandedName = '';
      } catch (e) { ElMessage.error('加载看板数据失败: ' + (e.message || e)); } finally { this.dataLoading = false; }
    },
    async loadBatchDetail(row) {
      if (row._detail || row._detailLoading) return;
      row._detailLoading = true;
      try {
        const ids = (row.rows || []).map(r => r['jira号'] || r.jira号 || '').filter(Boolean).join(',');
        const url = ids
          ? `/api/dashboard/batch_detail?date=${this.selectedDate}&batch=${encodeURIComponent(row.name)}&jira_ids=${encodeURIComponent(ids)}`
          : `/api/dashboard/batch_detail?date=${this.selectedDate}&batch=${encodeURIComponent(row.name)}`;
        const r = await api(url);
        row._detail = r.data;
        this.recalcDetail();
      } catch (e) { ElMessage.warning('批次详情加载失败: ' + (e.message || e)); } finally { row._detailLoading = false; }
    },
    toggleBatch(batch) {
      if (batch.all_failed) {
        ElMessage.info('该批次全部失败，仅展示不分析');
        return;
      }
      if (this.expandedName === batch.name) { this.expandedName = ''; return; }
      this.expandedName = batch.name;
      this.loadBatchDetail(batch);
    },
    recalcDetail() {
      let m = 0, ok = 0, fail = 0;
      for (const b of this.batches) if (b._detail) { m += b._detail.bt_match; ok += b._detail.bt_ok; fail += b._detail.bt_fail; }
      this.dashDetail = { bt_match: m, bt_ok: ok, bt_fail: fail };
    },
    openReport(row) { window.open(`/reports/${this.selectedDate}/${row.report_file}`, '_blank'); },
    openDailyReport() { window.open(`/reports/${this.selectedDate}/daily_report_${this.selectedDate}.html`, '_blank'); },
    startAutoRefresh() {
      this.stopAutoRefresh();
      this.refreshTimer = setInterval(() => { if (this.isToday) { this.loadDashboard(); this.loadDates(); } }, REFRESH_INTERVAL);
    },
    stopAutoRefresh() { if (this.refreshTimer) { clearInterval(this.refreshTimer); this.refreshTimer = null; } },
  },
};
</script>

<style scoped>
.db-panel { padding: 0; }

/* ── 工具栏 ── */
.db-toolbar {
  display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px;
  margin-bottom: 16px;
}
.db-toolbar-left { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.db-toolbar-right { display: flex; align-items: center; gap: 10px; }
.auto-badge {
  display: inline-flex; align-items: center; gap: 5px; padding: 3px 10px; border-radius: 20px;
  background: #f0fdf4; color: #16a34a; font-size: 11px; font-weight: 500;
}
.pulse-dot {
  width: 6px; height: 6px; border-radius: 50%; background: #16a34a;
  animation: pulse-anim 2s ease-in-out infinite;
}
@keyframes pulse-anim { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }

/* ── 统计卡片 ── */
.db-stats {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 20px;
}
.db-stat-card {
  background: var(--bg, #f5f7fa); border-radius: 12px; padding: 18px 20px;
  display: flex; flex-wrap: wrap; align-items: center; gap: 12px;
  border: 1px solid rgba(0,0,0,.04);
  transition: transform .2s ease, box-shadow .2s ease;
}
.db-stat-card:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(0,0,0,.06); }
.db-stat-icon { font-size: 28px; line-height: 1; }
.db-stat-body { flex: 1; min-width: 0; }
.db-stat-value { font-size: 26px; font-weight: 800; color: #1a202c; line-height: 1.2; }
.db-stat-label { font-size: 12px; color: #718096; margin-top: 2px; }
.db-stat-foot { width: 100%; font-size: 11px; color: #909399; padding-top: 6px; border-top: 1px solid rgba(0,0,0,.05); }

/* ── 分区标题 ── */
.db-section { margin-bottom: 20px; }
.db-section-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 12px; }
.db-section-title { font-size: 15px; font-weight: 700; color: #1f3b73; }
.db-section-count { font-size: 12px; color: #909399; }

/* ── 批次卡片 ── */
.db-batch-card {
  background: #fff; border: 1px solid #e8ecf1; border-radius: 10px; margin-bottom: 10px;
  overflow: hidden; transition: border-color .2s ease, box-shadow .2s ease;
}
.db-batch-card:hover { border-color: #c6d4e8; box-shadow: 0 2px 10px rgba(31,59,115,.06); }
.db-batch-card.is-expanded { border-color: #409eff; box-shadow: 0 4px 16px rgba(64,158,255,.1); }

.db-batch-head {
  display: flex; align-items: center; justify-content: space-between; padding: 14px 18px;
  cursor: pointer; user-select: none; transition: background .15s ease;
}
.db-batch-head:hover { background: #f8fafc; }
.db-batch-left { display: flex; align-items: center; gap: 12px; min-width: 0; }
.db-batch-idx {
  width: 26px; height: 26px; border-radius: 8px; background: #eef2ff; color: #4f46e5;
  display: grid; place-items: center; font-size: 11px; font-weight: 800; flex-shrink: 0;
}
.db-batch-info { min-width: 0; }
.db-batch-name { font-weight: 600; font-size: 14px; color: #1a202c; display: block; }
.db-batch-meta { display: flex; align-items: center; gap: 8px; margin-top: 3px; font-size: 11px; color: #909399; }
.db-batch-right { display: flex; align-items: center; gap: 14px; flex-shrink: 0; }
.db-batch-stats { display: flex; align-items: center; gap: 10px; }
.db-mini-stat { font-size: 12px; color: #606266; white-space: nowrap; }
.db-mini-stat b { font-weight: 700; }
.db-mini-stat.ok b { color: #16a34a; }
.db-mini-stat.warn b { color: #d97706; }
.db-mini-bar { width: 60px; height: 6px; border-radius: 3px; background: #ebeef5; overflow: hidden; display: flex; }
.db-mini-bar-fill { height: 100%; transition: width .4s ease; }
.db-bar-ok { background: #67c23a; }
.db-bar-fail { background: #f56c6c; }
.db-report-tag { cursor: pointer; }
.db-expand-arrow { font-size: 16px; color: #c0c4cc; transition: transform .25s ease; }
.db-expand-arrow.rotated { transform: rotate(90deg); color: #409eff; }
.db-expand-arrow.is-disabled { color: #e5e7eb; cursor: not-allowed; }

/* ── 展开详情 ── */
.db-batch-body { padding: 16px 22px 18px; border-top: 1px solid #ebeef5; background: #fafbfd; }
.db-expand-enter-active { animation: expand-in .25s ease; }
.db-expand-leave-active { animation: expand-in .2s ease reverse; }
@keyframes expand-in { from { opacity: 0; max-height: 0; } to { opacity: 1; max-height: 500px; } }

.db-detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
.db-detail-block {
  background: #fff; border: 1px solid #ebeef5; border-radius: 8px; padding: 14px 16px;
}
.db-detail-title {
  font-size: 11px; font-weight: 700; color: #909399; text-transform: uppercase; letter-spacing: .5px;
  margin-bottom: 10px; padding-bottom: 6px; border-bottom: 1px solid #f0f2f5;
}
.db-kv-list { display: flex; flex-direction: column; gap: 6px; }
.db-kv { display: flex; align-items: center; justify-content: space-between; font-size: 13px; }
.db-kv-k { color: #909399; }
.db-kv-v { color: #303133; font-weight: 500; }

/* 匹配进度条 */
.db-match-bar { height: 10px; border-radius: 5px; background: #ebeef5; overflow: hidden; display: flex; margin-bottom: 8px; }
.db-match-fill { height: 100%; transition: width .4s ease; }
.db-m-ok { background: #67c23a; }
.db-m-fail { background: #f56c6c; }
.db-m-miss { background: #e6e8eb; }
.db-match-legend { display: flex; gap: 14px; font-size: 11px; color: #606266; }
.db-dot { display: inline-block; width: 8px; height: 8px; border-radius: 2px; margin-right: 3px; vertical-align: middle; }
.db-dot-ok { background: #67c23a; }
.db-dot-fail { background: #f56c6c; }
.db-dot-miss { background: #dcdfe6; }

.db-fail-tags { display: flex; gap: 6px; flex-wrap: wrap; }
.db-detail-actions { margin-top: 14px; display: flex; gap: 8px; }

/* ── 日报 ── */
.db-daily-bar {
  display: flex; align-items: center; justify-content: space-between;
  margin-top: 16px; padding: 14px 20px; background: #f8fafc; border: 1px solid #e8ecf1; border-radius: 10px;
}
.db-daily-info { display: flex; align-items: center; gap: 10px; }
.db-daily-icon { font-size: 20px; }
.db-daily-label { font-weight: 600; font-size: 14px; color: #303133; }

@media (max-width: 900px) {
  .db-stats { grid-template-columns: repeat(2, 1fr); }
  .db-detail-grid { grid-template-columns: 1fr; }
  .db-toolbar-right { display: none; }
}
</style>
