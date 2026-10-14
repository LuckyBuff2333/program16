<template>
  <div class="test-panel">
    <template v-if="!embedded">
      <div class="section-title">性能数据统计</div>
      <el-alert type="info" :closable="false"
        title="选择批量执行批次，对比不同配置参数（并发数/模型）下的分析成功率和耗时表现"></el-alert>
    </template>
    <el-card shadow="never" :style="{ marginTop: embedded ? '12px' : '14px' }">
      <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap">
        <el-radio-group v-model="tuning.source" @change="loadTuningBatches">
          <el-radio-button label="pc">PC 执行</el-radio-button>
          <el-radio-button label="online">线上执行</el-radio-button>
        </el-radio-group>
        <el-button type="primary" :loading="tuning.loading" @click="loadTuningBatches">加载批次</el-button>
        <span v-if="tuning.batches.length" style="color:#909399">共 {{ tuning.batches.length }} 个批次</span>
      </div>
    </el-card>
    <el-card shadow="never" style="margin-top:14px" v-if="tuning.batches.length">
      <div style="font-weight:600;margin-bottom:10px">选择批次（可多选）</div>
      <el-checkbox-group v-model="tuning.selected">
        <div v-for="b in tuning.batches" :key="b.batch_id" style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
          <el-checkbox :label="b.batch_id" style="min-width:40px"></el-checkbox>
          <el-tag size="small" type="info">{{ b.date }}</el-tag>
          <span style="font-size:13px">{{ b.name }}</span>
          <el-tag size="small">并发{{ b.base_info['分析并发数'] || '-' }}/{{ b.base_info['下载并发数'] || '-' }}</el-tag>
          <el-tag size="small" type="warning">{{ b.base_info['模型'] || '-' }}</el-tag>
          <span style="font-size:12px;color:#909399">成功 {{ b.success }}/{{ b.total }}</span>
          <el-input v-if="tuning.selected.includes(b.batch_id)" v-model="tuning.versionLabels[b.batch_id]"
            placeholder="版本号" size="small" style="width:100px;margin-left:auto"></el-input>
        </div>
      </el-checkbox-group>
      <el-button type="success" style="margin-top:12px" :loading="tuning.analyzing"
        :disabled="!tuning.selected.length" @click="analyzeTuning">开始分析</el-button>
    </el-card>
    <template v-if="tuning.results.length">
      <el-card shadow="never" style="margin-top:14px">
        <div style="font-weight:600;margin-bottom:10px">分析结果</div>
        <el-table :data="tuning.results" stripe size="small">
          <el-table-column prop="date" label="日期" width="100"></el-table-column>
          <el-table-column label="版本" width="80"><template #default="{row}">{{ row.version }}</template></el-table-column>
          <el-table-column label="基础信息" min-width="200">
            <template #default="{row}">并发{{ row.base_info['分析并发数'] || '-' }}/{{ row.base_info['下载并发数'] || '-' }} {{ row.base_info['模型'] || '-' }}</template>
          </el-table-column>
          <el-table-column prop="total" label="执行数" width="70"></el-table-column>
          <el-table-column prop="success_rate" label="成功率" width="80"></el-table-column>
          <el-table-column prop="avg_analysis_time" label="平均分析耗时" width="110"></el-table-column>
          <el-table-column prop="median_analysis_time" label="中位数分析耗时" width="120"></el-table-column>
        </el-table>
      </el-card>
      <el-card shadow="never" style="margin-top:14px">
        <div style="font-weight:600;margin-bottom:10px">对比图表</div>
        <el-row :gutter="16">
          <el-col :span="12"><div ref="tuningChart1" style="height:300px"></div></el-col>
          <el-col :span="12"><div ref="tuningChart2" style="height:300px"></div></el-col>
        </el-row>
        <div ref="tuningChart3" style="height:300px;margin-top:16px"></div>
      </el-card>
      <el-card shadow="never" style="margin-top:14px">
        <div style="font-weight:600;margin-bottom:10px">对比结论</div>
        <el-checkbox-group v-model="tuning.comparing">
          <el-checkbox v-for="r in tuning.results" :key="r.batch_id" :label="r.batch_id" style="margin-right:16px">
            {{ r.date }} {{ r.version !== '-' ? r.version : '' }} 并发{{ r.base_info['分析并发数'] || '-' }}/{{ r.base_info['下载并发数'] || '-' }}
          </el-checkbox>
        </el-checkbox-group>
        <el-button type="primary" style="margin-top:12px" :disabled="tuning.comparing.length < 2" @click="generateTuningConclusion">生成对比结论</el-button>
        <div v-if="tuning.conclusion" style="margin-top:12px;padding:12px;background:#f8f9fa;border-radius:6px;white-space:pre-wrap;font-size:13px;line-height:1.8">{{ tuning.conclusion }}</div>
      </el-card>
    </template>
  </div>
</template>

<script lang="ts">
// @ts-nocheck
import { ElMessage } from 'element-plus';
import * as echarts from 'echarts';
import { api } from '../composables/utils';

// 解析 "X分Y秒" / "X秒" 格式为秒数
function parseDur(s: string): number {
  if (!s || s === '-') return 0;
  const m = String(s).match(/(\d+)\s*分\s*(\d+)\s*秒?/);
  if (m) return parseInt(m[1]) * 60 + parseInt(m[2]);
  const m2 = String(s).match(/(\d+)\s*分$/);
  if (m2) return parseInt(m2[1]) * 60;
  return parseFloat(String(s).replace(/[^\d.]/g, '')) || 0;
}

export default {
  name: 'ConfigTuningPanel',
  props: {
    embedded: { type: Boolean, default: false },
  },
  data() {
    return {
      tuning: {
        source: 'pc', loading: false, batches: [], selected: [],
        versionLabels: {}, analyzing: false, results: [], comparing: [], conclusion: '',
      },
    };
  },
  methods: {
    async loadTuningBatches() {
      this.tuning.loading = true;
      this.tuning.results = [];
      this.tuning.comparing = [];
      this.tuning.conclusion = '';
      try {
        const body = await api(`/api/tuning/batch_list?source=${this.tuning.source}`);
        this.tuning.batches = body.data || [];
        this.tuning.selected = [];
      } catch (e) { ElMessage.error('加载批次列表失败: ' + (e.message || e)); }
      finally { this.tuning.loading = false; }
    },
    async analyzeTuning() {
      if (!this.tuning.selected.length) return ElMessage.warning('请选择至少一个批次');
      this.tuning.analyzing = true;
      this.tuning.conclusion = '';
      try {
        const body = await api('/api/tuning/analyze', {
          method: 'POST', body: JSON.stringify({
            batch_ids: this.tuning.selected,
            version_labels: this.tuning.versionLabels,
          }),
        });
        this.tuning.results = body.data?.batches || [];
        this.$nextTick(() => this.renderTuningCharts());
      } catch (e) { ElMessage.error('分析失败: ' + (e.message || e)); }
      finally { this.tuning.analyzing = false; }
    },
    renderTuningCharts() {
      const results = this.tuning.results;
      if (!results.length) return;
      const labels = results.map(r =>
        `${r.date} ${r.version !== '-' ? r.version + ' ' : ''}并发${r.base_info['分析并发数'] || '-'}/${r.base_info['下载并发数'] || '-'}`);
      const colors = ['#409eff', '#67c23a', '#e6a23c', '#f56c6c', '#909399'];
      // 图1：分析耗时对比
      const el1 = this.$refs.tuningChart1;
      if (el1) {
        const chart1 = echarts.init(el1 as HTMLElement);
        chart1.setOption({
          title: { text: '分析耗时对比', left: 'center', textStyle: { fontSize: 14 } },
          tooltip: { trigger: 'axis' },
          xAxis: { type: 'category', data: labels, axisLabel: { rotate: 20, fontSize: 11 } },
          yAxis: { type: 'value', name: '秒', axisLabel: { formatter: '{value}s' } },
          series: [
            { name: '平均耗时', type: 'bar', data: results.map(r => parseDur(r.avg_analysis_time)), itemStyle: { color: colors[0] } },
            { name: '中位数耗时', type: 'bar', data: results.map(r => parseDur(r.median_analysis_time)), itemStyle: { color: colors[1] } },
          ],
          grid: { left: 60, right: 20, bottom: 60 },
        });
      }
      // 图2：成功率对比
      const el2 = this.$refs.tuningChart2;
      if (el2) {
        const chart2 = echarts.init(el2 as HTMLElement);
        chart2.setOption({
          title: { text: '分析成功率对比', left: 'center', textStyle: { fontSize: 14 } },
          tooltip: { trigger: 'axis', formatter: '{b}: {c}%' },
          xAxis: { type: 'category', data: labels, axisLabel: { rotate: 20, fontSize: 11 } },
          yAxis: { type: 'value', name: '%', min: 0, max: 100 },
          series: [{
            name: '成功率', type: 'bar',
            data: results.map(r => parseFloat(r.success_rate) || 0),
            itemStyle: { color: function(params) { return params.value >= 80 ? '#67c23a' : params.value >= 60 ? '#e6a23c' : '#f56c6c'; } },
          }],
          grid: { left: 60, right: 20, bottom: 60 },
        });
      }
      // 图3：执行数量 vs 成功率（散点图）
      const el3 = this.$refs.tuningChart3;
      if (el3) {
        const chart3 = echarts.init(el3 as HTMLElement);
        chart3.setOption({
          title: { text: '执行数量 vs 成功率', left: 'center', textStyle: { fontSize: 14 } },
          tooltip: { trigger: 'item', formatter: function(p) {
            return `${p.data[3]}<br/>执行数量: ${p.data[0]}<br/>成功率: ${p.data[1]}%`;
          } },
          xAxis: { type: 'value', name: '执行数量' },
          yAxis: { type: 'value', name: '成功率%', min: 0, max: 100 },
          series: [{
            type: 'scatter', symbolSize: 16,
            data: results.map((r, i) => [r.total, parseFloat(r.success_rate) || 0, r.date, labels[i]]),
            itemStyle: { color: '#409eff' },
            label: { show: true, formatter: function(p) { return p.data[2]; }, position: 'top', fontSize: 10 },
          }],
          grid: { left: 60, right: 40, bottom: 40 },
        });
      }
    },
    generateTuningConclusion() {
      const selected = this.tuning.results.filter(r => this.tuning.comparing.includes(r.batch_id));
      if (selected.length < 2) return;
      const lines: string[] = [];
      lines.push(`对比 ${selected.length} 个批次的配置参数：\n`);
      selected.forEach((r, i) => {
        const bi = r.base_info;
        lines.push(`${i + 1}. ${r.date} ${r.version !== '-' ? '(' + r.version + ') ' : ''}- 分析并发:${bi['分析并发数'] || '-'}, 下载并发:${bi['下载并发数'] || '-'}, 模型:${bi['模型'] || '-'}`);
        lines.push(`   执行${r.total}条, 成功${r.success}条(${r.success_rate}), 平均耗时${r.avg_analysis_time}, 中位数耗时${r.median_analysis_time}`);
      });
      lines.push('');
      // 成功率对比
      const rates = selected.map(r => parseFloat(r.success_rate) || 0);
      const maxRate = Math.max(...rates);
      const minRate = Math.min(...rates);
      const bestIdx = rates.indexOf(maxRate);
      const worstIdx = rates.indexOf(minRate);
      lines.push(`【成功率】最高: ${maxRate}% (${selected[bestIdx].date}), 最低: ${minRate}% (${selected[worstIdx].date}), 差值: ${(maxRate - minRate).toFixed(1)}%`);
      // 耗时对比
      const avgTimes = selected.map(r => parseDur(r.avg_analysis_time));
      if (avgTimes.some(t => t > 0)) {
        const maxTime = Math.max(...avgTimes);
        const minTime = Math.min(...avgTimes);
        const fastIdx = avgTimes.indexOf(minTime);
        const slowIdx = avgTimes.indexOf(maxTime);
        lines.push(`【平均耗时】最快: ${selected[fastIdx].avg_analysis_time} (${selected[fastIdx].date}), 最慢: ${selected[slowIdx].avg_analysis_time} (${selected[slowIdx].date})`);
      }
      // 配置差异分析
      const configs = selected.map(r => `${r.base_info['分析并发数']}/${r.base_info['下载并发数']}/${r.base_info['模型']}`);
      const uniqueConfigs = [...new Set(configs)];
      if (uniqueConfigs.length === 1) {
        lines.push(`\n【结论】所有批次配置相同(${uniqueConfigs[0]})，成功率差异可能源于数据分布或网络环境。`);
      } else {
        lines.push(`\n【配置差异】共 ${uniqueConfigs.length} 种不同配置组合`);
        uniqueConfigs.forEach((c, i) => lines.push(`  配置${i + 1}: 分析并发/下载并发/模型 = ${c}`));
        lines.push(`\n综合以上数据，成功率最高且耗时最短的配置组合表现最佳。`);
      }
      this.tuning.conclusion = lines.join('\n');
    },
  },
};
</script>
