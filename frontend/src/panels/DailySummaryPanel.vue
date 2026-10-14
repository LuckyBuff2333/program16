<template>
  <div class="test-panel">
    <div class="section-title">每日汇总</div>
    <el-alert type="info" :closable="false"
      title="按日/周/自定义时间段维度汇总分析执行数据，支撑质量回顾与决策。"></el-alert>

    <el-card shadow="never" style="margin-top:12px">
      <el-tabs v-model="activeTab" @tab-change="onTabChange">
        <!-- 每日汇总 -->
        <el-tab-pane label="每日汇总" name="daily">
          <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px">
            <el-date-picker v-model="daily.date" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" style="width:180px" />
            <el-button type="primary" :loading="daily.loading" @click="loadDaily">生成汇总</el-button>
            <span v-if="daily.reportDates.length" style="color:#909399;font-size:12px">
              覆盖日期：{{ daily.reportDates.join(' ~ ') }}
            </span>
          </div>
          <template v-if="daily.data">
            <div class="summary-metrics">
              <div class="metric-item"><span class="metric-label">执行总数</span><span class="metric-value">{{ daily.data.total }}</span></div>
              <div class="metric-item"><span class="metric-label">💻 PC</span><span class="metric-value">{{ daily.data.pc_count || 0 }}</span></div>
              <div class="metric-item"><span class="metric-label">🌐 线上</span><span class="metric-value">{{ daily.data.online_count || 0 }}</span></div>
              <div class="metric-item"><span class="metric-label">成功</span><span class="metric-value" style="color:#67c23a">{{ daily.data.success }}</span></div>
              <div class="metric-item"><span class="metric-label">失败</span><span class="metric-value" style="color:#f56c6c">{{ daily.data.fail }}</span></div>
              <div class="metric-item"><span class="metric-label">待分析</span><span class="metric-value" style="color:#e6a23c">{{ daily.data.pending }}</span></div>
              <div class="metric-item"><span class="metric-label">去重</span><span class="metric-value">{{ daily.data.dedup }}</span></div>
              <div class="metric-item"><span class="metric-label">成功率</span><span class="metric-value" style="color:#409eff;font-weight:700">{{ daily.data.success_rate }}</span></div>
              <div class="metric-item"><span class="metric-label">平均总耗时</span><span class="metric-value">{{ daily.data.avg_total_duration }}</span></div>
              <div class="metric-item"><span class="metric-label">平均分析耗时</span><span class="metric-value">{{ daily.data.avg_analysis_duration }}<template v-if="daily.data.too_long"> <el-tag type="warning" size="small">过高{{ daily.data.too_long }}条</el-tag></template></span></div>
            </div>
            <!-- 失败分类 -->
            <template v-if="Object.keys(daily.data.failures || {}).length">
              <div style="font-weight:600;margin:14px 0 8px;font-size:13px;color:#1f3b73">失败分析</div>
              <div style="display:flex;gap:8px;flex-wrap:wrap">
                <el-tag v-for="(cnt, cat) in daily.data.failures" :key="cat" type="danger" size="small">{{ cat }}：{{ cnt }}</el-tag>
              </div>
              <!-- 失败Jira详情 -->
              <template v-if="daily.data.failure_jiras">
                <el-collapse style="margin-top:8px">
                  <el-collapse-item v-for="(jiras, cat) in daily.data.failure_jiras" :key="cat" :title="cat + '（' + jiras.length + '条）'">
                    <el-table :data="jiras" size="small" stripe border max-height="200">
                      <el-table-column prop="jira号" label="Jira号" width="130"></el-table-column>
                      <el-table-column prop="错误信息" label="错误信息" show-overflow-tooltip></el-table-column>
                    </el-table>
                  </el-collapse-item>
                </el-collapse>
              </template>
            </template>
          </template>
        </el-tab-pane>

        <!-- 每周汇总 -->
        <el-tab-pane label="每周汇总" name="weekly">
          <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px">
            <el-date-picker v-model="weekly.date" type="date" value-format="YYYY-MM-DD" placeholder="选择日期（所在周）" style="width:220px" />
            <el-button type="primary" :loading="weekly.loading" @click="loadWeekly">生成汇总</el-button>
            <span v-if="weekly.data?.week_info" style="color:#909399;font-size:12px">
              {{ weekly.data.week_info.week_label }}（{{ weekly.data.week_info.monday }} ~ {{ weekly.data.week_info.sunday }}）
            </span>
          </div>
          <template v-if="weekly.data">
            <div class="summary-metrics">
              <div class="metric-item"><span class="metric-label">执行总数</span><span class="metric-value">{{ weekly.data.total }}</span></div>
              <div class="metric-item"><span class="metric-label">💻 PC</span><span class="metric-value">{{ weekly.data.pc_count || 0 }}</span></div>
              <div class="metric-item"><span class="metric-label">🌐 线上</span><span class="metric-value">{{ weekly.data.online_count || 0 }}</span></div>
              <div class="metric-item"><span class="metric-label">成功</span><span class="metric-value" style="color:#67c23a">{{ weekly.data.success }}</span></div>
              <div class="metric-item"><span class="metric-label">失败</span><span class="metric-value" style="color:#f56c6c">{{ weekly.data.fail }}</span></div>
              <div class="metric-item"><span class="metric-label">待分析</span><span class="metric-value" style="color:#e6a23c">{{ weekly.data.pending }}</span></div>
              <div class="metric-item"><span class="metric-label">去重</span><span class="metric-value">{{ weekly.data.dedup }}</span></div>
              <div class="metric-item"><span class="metric-label">回归</span><span class="metric-value">{{ weekly.data.regression }}</span></div>
              <div class="metric-item"><span class="metric-label">成功率</span><span class="metric-value" style="color:#409eff;font-weight:700">{{ weekly.data.weekly_rate }}</span></div>
              <div class="metric-item"><span class="metric-label">耗时过高</span><span class="metric-value">{{ weekly.data.too_long || 0 }} 条</span></div>
            </div>
            <!-- 每日明细 -->
            <template v-if="weekly.data.daily_breakdown?.length">
              <div style="font-weight:600;margin:14px 0 8px;font-size:13px;color:#1f3b73">每日明细</div>
              <el-table :data="weekly.data.daily_breakdown" size="small" stripe border max-height="260">
                <el-table-column prop="date" label="日期" width="120"></el-table-column>
                <el-table-column prop="total" label="总数" width="70" align="center"></el-table-column>
                <el-table-column prop="success" label="成功" width="70" align="center">
                  <template #default="{row}"><span style="color:#67c23a">{{ row.success }}</span></template>
                </el-table-column>
                <el-table-column prop="fail" label="失败" width="70" align="center">
                  <template #default="{row}"><span style="color:#f56c6c">{{ row.fail }}</span></template>
                </el-table-column>
                <el-table-column prop="pending" label="待分析" width="70" align="center"></el-table-column>
                <el-table-column prop="dedup" label="去重" width="70" align="center"></el-table-column>
                <el-table-column prop="rate" label="成功率" width="90" align="center"></el-table-column>
                <el-table-column prop="avg_analysis" label="平均分析耗时" width="120" align="center"></el-table-column>
              </el-table>
            </template>
            <!-- 失败分类 -->
            <template v-if="Object.keys(weekly.data.failures || {}).length">
              <div style="font-weight:600;margin:14px 0 8px;font-size:13px;color:#1f3b73">失败分析</div>
              <div style="display:flex;gap:8px;flex-wrap:wrap">
                <el-tag v-for="(cnt, cat) in weekly.data.failures" :key="cat" type="danger" size="small">{{ cat }}：{{ cnt }}</el-tag>
              </div>
            </template>
          </template>
        </el-tab-pane>

        <!-- 时间段汇总 -->
        <el-tab-pane label="时间段汇总" name="range">
          <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px;flex-wrap:wrap">
            <el-date-picker v-model="range.startDate" type="date" value-format="YYYY-MM-DD" placeholder="起始日期" style="width:170px" />
            <span style="color:#909399">~</span>
            <el-date-picker v-model="range.endDate" type="date" value-format="YYYY-MM-DD" placeholder="结束日期" style="width:170px" />
            <el-button type="primary" :loading="range.loading" @click="loadRange">生成汇总</el-button>
            <span v-if="range.data?.range_info" style="color:#909399;font-size:12px">
              {{ range.data.range_info.range_label }}（{{ range.data.range_info.working_days?.length || 0 }} 个工作日）
            </span>
          </div>
          <template v-if="range.data">
            <div class="summary-metrics">
              <div class="metric-item"><span class="metric-label">执行总数</span><span class="metric-value">{{ range.data.total }}</span></div>
              <div class="metric-item"><span class="metric-label">💻 PC</span><span class="metric-value">{{ range.data.pc_count || 0 }}</span></div>
              <div class="metric-item"><span class="metric-label">🌐 线上</span><span class="metric-value">{{ range.data.online_count || 0 }}</span></div>
              <div class="metric-item"><span class="metric-label">成功</span><span class="metric-value" style="color:#67c23a">{{ range.data.success }}</span></div>
              <div class="metric-item"><span class="metric-label">失败</span><span class="metric-value" style="color:#f56c6c">{{ range.data.fail }}</span></div>
              <div class="metric-item"><span class="metric-label">待分析</span><span class="metric-value" style="color:#e6a23c">{{ range.data.pending }}</span></div>
              <div class="metric-item"><span class="metric-label">去重</span><span class="metric-value">{{ range.data.dedup }}</span></div>
              <div class="metric-item"><span class="metric-label">回归</span><span class="metric-value">{{ range.data.regression }}</span></div>
              <div class="metric-item"><span class="metric-label">成功率</span><span class="metric-value" style="color:#409eff;font-weight:700">{{ range.data.weekly_rate }}</span></div>
              <div class="metric-item"><span class="metric-label">耗时过高</span><span class="metric-value">{{ range.data.too_long || 0 }} 条</span></div>
            </div>
            <!-- 每日明细 -->
            <template v-if="range.data.daily_breakdown?.length">
              <div style="font-weight:600;margin:14px 0 8px;font-size:13px;color:#1f3b73">每日明细</div>
              <el-table :data="range.data.daily_breakdown" size="small" stripe border max-height="300">
                <el-table-column prop="date" label="日期" width="120"></el-table-column>
                <el-table-column prop="total" label="总数" width="70" align="center"></el-table-column>
                <el-table-column prop="success" label="成功" width="70" align="center">
                  <template #default="{row}"><span style="color:#67c23a">{{ row.success }}</span></template>
                </el-table-column>
                <el-table-column prop="fail" label="失败" width="70" align="center">
                  <template #default="{row}"><span style="color:#f56c6c">{{ row.fail }}</span></template>
                </el-table-column>
                <el-table-column prop="pending" label="待分析" width="70" align="center"></el-table-column>
                <el-table-column prop="dedup" label="去重" width="70" align="center"></el-table-column>
                <el-table-column prop="rate" label="成功率" width="90" align="center"></el-table-column>
                <el-table-column prop="avg_analysis" label="平均分析耗时" width="120" align="center"></el-table-column>
              </el-table>
            </template>
            <!-- 失败分类 -->
            <template v-if="Object.keys(range.data.failures || {}).length">
              <div style="font-weight:600;margin:14px 0 8px;font-size:13px;color:#1f3b73">失败分析</div>
              <div style="display:flex;gap:8px;flex-wrap:wrap">
                <el-tag v-for="(cnt, cat) in range.data.failures" :key="cat" type="danger" size="small">{{ cat }}：{{ cnt }}</el-tag>
              </div>
            </template>
          </template>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script lang="ts">
// @ts-nocheck
import { ElMessage } from 'element-plus';
import { api } from '../composables/utils';

export default {
  name: 'DailySummaryPanel',
  data() {
    const today = new Date().toISOString().slice(0, 10);
    return {
      activeTab: 'daily',
      daily: { date: today, loading: false, data: null as any, reportDates: [] as string[] },
      weekly: { date: today, loading: false, data: null as any },
      range: { startDate: '', endDate: '', loading: false, data: null as any },
    };
  },
  methods: {
    onTabChange() {
      // 切换 tab 时不自动加载，用户手动触发
    },
    async loadDaily() {
      if (!this.daily.date) { ElMessage.warning('请选择日期'); return; }
      this.daily.loading = true;
      this.daily.data = null;
      this.daily.reportDates = [];
      try {
        const res = await api(`/api/report/daily_summary?date=${this.daily.date}`);
        this.daily.data = res.data;
        this.daily.reportDates = res.data.report_dates || [this.daily.date];
        if (res.data.total === 0) {
          ElMessage.info('该日期无执行数据');
        }
      } catch (e: any) {
        ElMessage.error('每日汇总生成失败: ' + (e.message || e));
      } finally {
        this.daily.loading = false;
      }
    },
    async loadWeekly() {
      if (!this.weekly.date) { ElMessage.warning('请选择日期'); return; }
      this.weekly.loading = true;
      this.weekly.data = null;
      try {
        const res = await api(`/api/report/weekly_summary?date=${this.weekly.date}`);
        this.weekly.data = res.data;
        if (res.data.total === 0) {
          ElMessage.info('该周无执行数据');
        }
      } catch (e: any) {
        ElMessage.error('每周汇总生成失败: ' + (e.message || e));
      } finally {
        this.weekly.loading = false;
      }
    },
    async loadRange() {
      if (!this.range.startDate || !this.range.endDate) { ElMessage.warning('请选择起止日期'); return; }
      this.range.loading = true;
      this.range.data = null;
      try {
        const res = await api(`/api/report/range_summary?start_date=${this.range.startDate}&end_date=${this.range.endDate}`);
        this.range.data = res.data;
        if (res.data.total === 0) {
          ElMessage.info('该时间段无执行数据');
        }
      } catch (e: any) {
        ElMessage.error('时间段汇总生成失败: ' + (e.message || e));
      } finally {
        this.range.loading = false;
      }
    },
  },
};
</script>

<style scoped>
.summary-metrics {
  display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 8px;
}
.metric-item {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  background: #f7f8fa; border-radius: 8px; padding: 10px 16px; min-width: 90px;
  border: 1px solid #ebeef5;
}
.metric-label { font-size: 11px; color: #909399; margin-bottom: 4px; white-space: nowrap; }
.metric-value { font-size: 16px; font-weight: 600; color: #303133; }
</style>
