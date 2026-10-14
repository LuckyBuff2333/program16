<template>
  <div class="test-panel">
    <div class="section-title">置信度批量写入（根因语义对比）</div>
    <el-alert type="info" :closable="false"
      title="筛选分析结果=成功的记录，填充 rootcause（从Jira取最新）和 AI问题分析根因（表格有则用，无则从飞书文档提取），用 Diana LLM 做语义相似度对比写回置信度。通用根因写“无法判断”。勾选“仅置信度为空”可跳过已有置信度的记录">
    </el-alert>
    <el-card shadow="never" style="margin-top:12px">
      <el-form inline style="margin-bottom:8px">
        <el-form-item label="分析完成时间起" style="margin-bottom:0">
          <el-date-picker v-model="confidenceBatch.afterTime" type="datetime" value-format="YYYY-MM-DD HH:mm:ss"
            placeholder="不填则不筛选时间" clearable style="width:220px"></el-date-picker>
        </el-form-item>
        <el-form-item style="margin-bottom:0"><el-checkbox v-model="confidenceBatch.onlyEmpty">仅置信度为空</el-checkbox></el-form-item>
        <el-form-item style="margin-bottom:0">
          <el-button type="primary" :loading="confidenceBatch.running" @click="runConfidenceBatchWrite"
            :disabled="confidenceBatch.running">{{ confidenceBatch.running ? '执行中...' : '开始执行' }}</el-button>
        </el-form-item>
      </el-form>
      <div style="font-size:13px;color:#8a93a6;margin-bottom:8px">{{ confidenceBatch.msg || '点击"开始执行"从多维表格读取并逐条对比' }}</div>
      <div v-if="confidenceBatch.total > 0" style="margin-bottom:8px">
        <el-progress :percentage="Math.round(confidenceBatch.currentIndex / confidenceBatch.total * 100)"
          :stroke-width="10" style="margin-bottom:6px"></el-progress>
        <div style="font-size:12px;color:#606266;display:flex;gap:16px;flex-wrap:wrap">
          <span>总数: <b>{{ confidenceBatch.total }}</b></span>
          <span>进度: <b>{{ confidenceBatch.currentIndex }}</b></span>
          <span style="color:#67c23a">达标: <b>{{ confidenceBatch.passed }}</b></span>
          <span style="color:#e6a23c">未达标: <b>{{ confidenceBatch.low }}</b></span>
          <span style="color:#f56c6c">跳过/失败: <b>{{ confidenceBatch.failed }}</b></span>
        </div>
      </div>
      <el-table v-if="confidenceBatch.results.length" :data="confidenceBatch.results" max-height="420"
        size="small" :row-class-name="({row}) => row.status === 'pass' ? 'success-row' : (row.status === 'low' ? 'warning-row' : '')">
        <el-table-column type="index" label="#" width="45"></el-table-column>
        <el-table-column prop="bugid" label="Jira号" width="120"></el-table-column>
        <el-table-column prop="score" label="置信度" width="90" align="center">
          <template #default="{row}">
            <el-tag v-if="row.score === '无法判断'" type="info" size="small">无法判断</el-tag>
            <el-tag v-else :type="row.score >= 0.7 ? 'success' : (row.score >= 0.4 ? 'warning' : 'danger')" size="small">{{ row.score }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="结果" width="70" align="center">
          <template #default="{row}">
            <el-tag :type="row.status === 'pass' ? 'success' : (row.status === 'low' ? 'warning' : 'info')" size="small">
              {{ row.status === 'pass' ? '达标' : (row.status === 'low' ? '未达标' : (row.status === 'skipped' ? '跳过' : '失败')) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="jira_rootcause" label="Jira根因(rootcause)" min-width="200" show-overflow-tooltip></el-table-column>
        <el-table-column prop="ai_rootcause" label="AI问题分析根因" min-width="200" show-overflow-tooltip></el-table-column>
        <el-table-column prop="msg" label="说明" min-width="160" show-overflow-tooltip>
          <template #default="{row}"><span :style="row.status === 'fail' || row.status === 'skipped' ? 'color:#f56c6c' : ''">{{ row.msg || '-' }}</span></template>
        </el-table-column>
      </el-table>
      <div v-if="confidenceBatch.results.length && !confidenceBatch.running" style="margin-top:12px;display:flex;gap:10px;flex-wrap:wrap;align-items:center">
        <el-button type="success" :loading="confidenceBatch.committing" @click="commitConfidenceBatch('pass')">
          达标写入（{{ confidenceBatch.results.filter(r => r.status === 'pass' && r.record_id && r.write_fields).length }}）
        </el-button>
        <el-button type="info" :loading="confidenceBatch.committing" @click="commitConfidenceBatch('invalid')">
          无效写入（{{ confidenceBatch.results.filter(r => r.status === 'invalid' && r.record_id && r.write_fields).length }}）
        </el-button>
        <el-button type="warning" :loading="confidenceBatch.committing" @click="commitConfidenceBatch('low')">
          未达标写入（{{ confidenceBatch.results.filter(r => r.status === 'low' && r.record_id && r.write_fields).length }}）
        </el-button>
        <el-button type="primary" :loading="confidenceBatch.committing" @click="commitConfidenceBatch('all')">
          一键写入（{{ confidenceBatch.results.filter(r => r.record_id && r.write_fields && Object.keys(r.write_fields).length > 0).length }}）
        </el-button>
      </div>
      <el-alert v-if="confidenceBatch.doneMsg" type="success" :closable="false" :title="confidenceBatch.doneMsg" style="margin-top:10px"></el-alert>
    </el-card>
  </div>
</template>

<script lang="ts">
// @ts-nocheck
import { ElMessage } from 'element-plus';
import { api } from '../composables/utils';
export default {
  name: 'ConfidenceBatchPanel',
  data() {
    return {
      confidenceBatch: {
        running: false, committing: false, total: 0, currentIndex: 0, passed: 0, low: 0, failed: 0,
        results: [], msg: '', doneMsg: '', afterTime: '', onlyEmpty: false,
      },
    };
  },
  methods: {
    runConfidenceBatchWrite() {
      const cb = this.confidenceBatch;
      cb.running = true; cb.total = 0; cb.currentIndex = 0; cb.passed = 0; cb.low = 0; cb.failed = 0;
      cb.results = []; cb.msg = '正在从多维表格加载记录...'; cb.doneMsg = '';
      const params = new URLSearchParams();
      if (cb.afterTime) params.set('after_time', cb.afterTime);
      if (cb.onlyEmpty) params.set('only_empty', '1');
      const url = '/api/test/confidence_batch_write' + (params.toString() ? '?' + params.toString() : '');
      const es = new EventSource(url);
      es.onmessage = (evt) => {
        const d = JSON.parse(evt.data);
        if (d.type === 'start') {
          cb.total = d.total;
          const timeHint = d.after_time ? `（时间筛选 ${d.after_time} 之后）` : '';
          cb.msg = `共 ${d.total} 条待处理，阈值 ${d.threshold}${timeHint}`;
        } else if (d.type === 'progress') {
          cb.currentIndex = d.index;
          cb.results.push({ bugid: d.bugid, score: d.score || 0, status: d.status,
            jira_rootcause: d.jira_rootcause || '', ai_rootcause: d.ai_rootcause || '',
            record_id: d.record_id || '', write_fields: d.write_fields || {}, msg: d.msg || '' });
          if (d.status === 'pass' || d.status === 'invalid') cb.passed++;
          else if (d.status === 'low') cb.low++;
          else cb.failed++;
          cb.msg = `处理中 ${d.index}/${d.total}：${d.bugid}`;
        } else if (d.type === 'done') {
          cb.doneMsg = d.msg || '处理完成';
          cb.msg = `已完成: 达标${d.passed || 0}条, 写入${d.updated || 0}条`;
          cb.running = false; es.close();
        } else if (d.type === 'error') { cb.msg = '错误: ' + (d.msg || '未知错误'); cb.running = false; es.close(); }
        else if (d.type === 'cancelled') { cb.msg = '已取消'; cb.running = false; es.close(); }
      };
      es.onerror = () => { cb.msg = '连接中断'; cb.running = false; es.close(); };
    },
    async commitConfidenceBatch(category) {
      const cb = this.confidenceBatch;
      let items;
      if (category === 'pass') items = cb.results.filter(r => r.status === 'pass' && r.record_id && r.write_fields);
      else if (category === 'invalid') items = cb.results.filter(r => r.status === 'invalid' && r.record_id && r.write_fields);
      else if (category === 'low') items = cb.results.filter(r => r.status === 'low' && r.record_id && r.write_fields);
      else items = cb.results.filter(r => r.record_id && r.write_fields && Object.keys(r.write_fields).length > 0);
      if (!items.length) return ElMessage.warning('该类别无待写入记录');
      cb.committing = true;
      try {
        const body = await api('/api/test/confidence_batch_commit', {
          method: 'POST',
          body: JSON.stringify({ items: items.map(r => ({ bugid: r.bugid, record_id: r.record_id, write_fields: r.write_fields })) })
        });
        cb.doneMsg = body.message || '写入完成';
        ElMessage.success(cb.doneMsg);
      } catch (e) { /* 已提示 */ } finally { cb.committing = false; }
    },
  },
};
</script>
