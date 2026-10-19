<template>
  <div class="regression-page">
    <div class="section-title">回归测试</div>

    <!-- 区域 A：筛选栏 -->
    <el-card shadow="never">
      <template #header><span style="font-weight:700">① 加载云端批次</span></template>
      <div class="filter-bar">
        <div class="param-item">
          <span class="param-label">批次日期起</span>
          <el-date-picker v-model="afterTime" type="datetime" value-format="YYYY-MM-DD HH:mm:ss"
            placeholder="不填则加载全部批次" clearable style="width:220px" size="small"></el-date-picker>
        </div>
        <el-button type="primary" size="small" :loading="loadingBatches" @click="loadBatches">加载批次</el-button>
        <el-tag v-if="batches.length" type="info" size="small">{{ batches.length }} 个批次</el-tag>
      </div>
      <el-alert v-if="batchMsg" :type="batchError ? 'error' : 'success'" :closable="false" :title="batchMsg" style="margin-top:8px"></el-alert>
    </el-card>

    <!-- 区域 B：批次列表 -->
    <el-card v-if="batches.length" shadow="never">
      <template #header>
        <div style="display:flex;align-items:center;justify-content:space-between">
          <span style="font-weight:700">② 选择批次</span>
          <div>
            <el-button size="small" @click="selectAll">全选</el-button>
            <el-button size="small" @click="invertSelection">反选</el-button>
          </div>
        </div>
      </template>
      <div class="batch-list">
        <div v-for="b in batches" :key="b.batch_id" class="batch-item">
          <div class="batch-row">
            <el-checkbox :model-value="checkedSet.has(b.batch_id)" @change="(val: boolean) => toggleBatch(b, val)" />
            <button class="expand-btn" @click="toggleExpand(b.batch_id)">
              <span :class="expandedSet.has(b.batch_id) ? 'arrow-down' : 'arrow-right'">{{ expandedSet.has(b.batch_id) ? '▼' : '▶' }}</span>
            </button>
            <span class="batch-name">{{ b.date }} / {{ b.name }}</span>
            <el-tag size="small" type="info">总数 {{ b.total }}</el-tag>
            <el-tag size="small" type="danger">失败 {{ b.fail_count }}</el-tag>
            <el-tag size="small" :type="b.source === '线上' ? 'warning' : (b.source === 'PC' ? '' : 'info')">{{ b.source || '-' }}</el-tag>
          </div>
          <div v-if="expandedSet.has(b.batch_id)" class="batch-detail">
            <el-tag v-for="j in b.failed_jiras" :key="j" size="small" style="margin:2px" type="danger">{{ j }}</el-tag>
            <span v-if="!b.failed_jiras.length" style="color:#c0c4cc;font-size:12px">无失败记录</span>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 区域 C：汇总栏 -->
    <el-card v-if="selectedJiras.length" shadow="never">
      <template #header>
        <div style="display:flex;align-items:center;justify-content:space-between">
          <span style="font-weight:700">③ 汇总与抽样</span>
          <el-tag type="success">已选 {{ checkedSet.size }} 批次 / {{ selectedJiras.length }} 个失败 Jira</el-tag>
        </div>
      </template>
      <div class="sample-bar">
        <span class="param-label">抽取个数</span>
        <el-input-number v-model="sampleCount" :min="0" :max="2000" :step="1" style="width:130px" controls-position="right" size="small"></el-input-number>
        <span style="font-size:12px;color:#909399">0 = 全部</span>
      </div>
      <div style="margin-top:10px;max-height:180px;overflow-y:auto">
        <el-tag v-for="j in selectedJiras" :key="j" closable size="small" style="margin:2px" @close="removeJira(j)">{{ j }}</el-tag>
      </div>
    </el-card>

    <!-- 区域 D：执行栏 -->
    <el-card v-if="selectedJiras.length" shadow="never">
      <template #header><span style="font-weight:700">④ 回归执行</span></template>
      <div class="exec-bar">
        <el-radio-group v-model="execMode" size="small">
          <el-radio-button label="pc">PC</el-radio-button>
          <el-radio-button label="online">线上</el-radio-button>
        </el-radio-group>
        <div class="param-item">
          <span class="param-label">间隔(分钟)</span>
          <el-input-number v-model="intervalMin" :min="0" :max="120" style="width:100px" controls-position="right" size="small"></el-input-number>
        </div>
        <div class="param-item">
          <span class="param-label">轮次</span>
          <el-input-number v-model="totalRounds" :min="1" :max="50" style="width:90px" controls-position="right" size="small"></el-input-number>
        </div>
        <el-button v-if="!executing" type="primary" @click="startRegression">开始回归执行</el-button>
        <el-button v-if="executing" type="danger" @click="stopRegression">停止执行</el-button>
      </div>
      <!-- 执行进度 -->
      <div v-if="execLogs.length || execSummary" class="exec-progress">
        <div v-if="execSummary" class="exec-summary">
          <el-tag :type="execSummary.type">{{ execSummary.text }}</el-tag>
          <span v-if="execSummary.detail" style="margin-left:8px;color:#606266;font-size:12px">{{ execSummary.detail }}</span>
        </div>
        <el-progress v-if="execProgress > 0" :percentage="execProgress" :stroke-width="10" style="margin-top:6px"></el-progress>
        <div class="exec-log" v-if="execLogs.length">
          <div v-for="(log, idx) in execLogs.slice(-30)" :key="idx" :style="logStyle(log)">{{ log }}</div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script lang="ts">
// @ts-nocheck
import { ElMessage } from 'element-plus';
import { api } from '../composables/utils';

export default {
  name: 'RegressionPage',
  data() {
    return {
      // 区域 A
      afterTime: '',
      loadingBatches: false,
      batches: [] as any[],
      batchMsg: '',
      batchError: false,
      // 区域 B
      checkedSet: new Set<string>(),
      expandedSet: new Set<string>(),
      // 区域 C/D
      sampleCount: 0,
      execMode: 'pc',
      intervalMin: 0,
      totalRounds: 1,
      // 执行状态
      executing: false,
      execLogs: [] as string[],
      execSummary: null as any,
      execProgress: 0,
    };
  },
  computed: {
    selectedJiras(): string[] {
      const s = new Set<string>();
      for (const b of this.batches) {
        if (this.checkedSet.has(b.batch_id)) {
          for (const j of b.failed_jiras) s.add(j);
        }
      }
      return [...s].sort();
    },
  },
  methods: {
    async loadBatches() {
      this.loadingBatches = true;
      this.batchMsg = '正在加载...'; this.batchError = false;
      this.batches = []; this.checkedSet.clear(); this.expandedSet.clear();
      try {
        const resp = await fetch('/api/test/regression_batches', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ after_time: this.afterTime || '' }),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const reader = resp.body!.getReader();
        const decoder = new TextDecoder();
        let buf = '';
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          const lines = buf.split('\n');
          buf = lines.pop()!;
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            try {
              const msg = JSON.parse(line.slice(6));
              if (msg.type === 'progress') {
                this.batchMsg = msg.message;
              } else if (msg.type === 'done') {
                this.batches = msg.batches || [];
                this.batchMsg = msg.message;
                ElMessage.success(msg.message);
              }
            } catch { /* ignore parse error */ }
          }
        }
      } catch (e: any) {
        this.batchMsg = e.message || '加载失败';
        this.batchError = true;
      } finally { this.loadingBatches = false; }
    },
    toggleBatch(b: any, checked: boolean) {
      if (checked) this.checkedSet.add(b.batch_id);
      else this.checkedSet.delete(b.batch_id);
      this.checkedSet = new Set(this.checkedSet); // 触发响应式更新
    },
    toggleExpand(id: string) {
      if (this.expandedSet.has(id)) this.expandedSet.delete(id);
      else this.expandedSet.add(id);
      this.expandedSet = new Set(this.expandedSet);
    },
    selectAll() {
      this.batches.forEach(b => this.checkedSet.add(b.batch_id));
      this.checkedSet = new Set(this.checkedSet);
    },
    invertSelection() {
      const next = new Set<string>();
      this.batches.forEach(b => { if (!this.checkedSet.has(b.batch_id)) next.add(b.batch_id); });
      this.checkedSet = next;
    },
    removeJira(jira: string) {
      // 从所有勾选批次中移除该 jira：取消包含该 jira 的批次的勾选
      for (const b of this.batches) {
        if (this.checkedSet.has(b.batch_id) && b.failed_jiras.includes(jira)) {
          this.checkedSet.delete(b.batch_id);
        }
      }
      this.checkedSet = new Set(this.checkedSet);
    },
    async startRegression() {
      if (!this.selectedJiras.length) return ElMessage.warning('请先选择批次');
      this.executing = true;
      this.execLogs = [];
      this.execSummary = null;
      this.execProgress = 0;
      try {
        const resp = await fetch('/api/test/regression_run', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            bugids: this.selectedJiras,
            sample_count: this.sampleCount || 0,
            exec_mode: this.execMode,
            interval_min: this.intervalMin,
            total_rounds: this.totalRounds,
          }),
        });
        const reader = resp.body!.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let doneCount = 0;
        let totalCount = 0;
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
              this.handleSSEEvent(evt, { doneCount: () => doneCount, totalCount: () => totalCount, setDone: (v: number) => { doneCount = v; }, setTotal: (v: number) => { totalCount = v; } });
            } catch { /* ignore */ }
          }
        }
      } catch (e: any) {
        if (e.name === 'AbortError') {
          this.execLogs.push('[已中止]');
        } else {
          ElMessage.error('回归执行失败: ' + (e.message || ''));
        }
      } finally {
        this.executing = false;
      }
    },
    handleSSEEvent(evt: any, counters: any) {
      switch (evt.type) {
        case 'search':
          this.execLogs.push(`[候选] 共 ${evt.total} 个 Jira 号`);
          counters.setTotal(evt.total);
          break;
        case 'sample':
          this.execLogs.push(`[第${evt.round}轮] 抽样 ${evt.total} 个`);
          break;
        case 'round':
          this.execLogs.push(`--- 第 ${evt.round}/${evt.total_rounds} 轮 ---`);
          break;
        case 'progress': {
          const status = evt.status === '成功' ? '✓' : '✗';
          this.execLogs.push(`${status} ${evt.bugid} (${evt.index}/${evt.total})`);
          counters.setDone(evt.index);
          if (counters.totalCount() > 0) {
            this.execProgress = Math.round(evt.index / counters.totalCount() * 100);
          }
          break;
        }
        case 'waiting':
          this.execLogs.push(`[等待] ${evt.interval_min} 分钟后进入下一轮...`);
          break;
        case 'stopped':
          this.execSummary = { type: 'warning', text: '已停止', detail: `成功 ${evt.success} / 失败 ${evt.fail}，第 ${evt.round} 轮` };
          this.execLogs.push(`[已停止] ${evt.message}`);
          break;
        case 'done':
          this.execSummary = {
            type: evt.success > 0 ? 'success' : 'info',
            text: `完成: ${evt.success}/${evt.total} 成功`,
            detail: evt.cloud_url ? `云端: ${evt.cloud_url}` : '',
          };
          this.execProgress = 100;
          this.execLogs.push(`[完成] ${evt.success}/${evt.total} 成功，${evt.rounds} 轮`);
          if (evt.cloud_url) this.execLogs.push(`[云端] ${evt.cloud_url}`);
          break;
        case 'error':
          this.execSummary = { type: 'danger', text: '执行错误', detail: evt.message };
          this.execLogs.push(`[错误] ${evt.message}`);
          break;
      }
    },
    async stopRegression() {
      try {
        await api('/api/test/regression_stop', { method: 'POST', body: '{}' });
        ElMessage.warning('已发送停止信号');
      } catch (e: any) {
        ElMessage.error('停止失败: ' + e.message);
      }
    },
    logStyle(log: string): string {
      if (log.startsWith('[错误]') || log.includes('✗')) return 'color:#f56c6c';
      if (log.startsWith('[已停止]')) return 'color:#e6a23c';
      if (log.startsWith('[完成]') || log.includes('✓')) return 'color:#67c23a';
      if (log.startsWith('---')) return 'color:#409eff;font-weight:600';
      return 'color:#606266';
    },
  },
};
</script>

<style scoped>
.regression-page { padding: 16px; }
.regression-page .el-card { margin-top: 12px; }
.section-title { font-size: 16px; font-weight: 700; margin-bottom: 10px; }
.filter-bar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.param-item { display: flex; align-items: center; gap: 6px; }
.param-label { font-size: 12px; color: #606266; white-space: nowrap; }
.sample-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.exec-bar { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }

/* 批次列表 */
.batch-list { max-height: 400px; overflow-y: auto; }
.batch-item { border-bottom: 1px solid #ebeef5; }
.batch-item:last-child { border-bottom: none; }
.batch-row { display: flex; align-items: center; gap: 8px; padding: 8px 4px; cursor: default; }
.batch-row:hover { background: #f5f7fa; }
.expand-btn { background: none; border: none; cursor: pointer; font-size: 11px; color: #909399; padding: 2px 4px; line-height: 1; }
.expand-btn:hover { color: #409eff; }
.arrow-right, .arrow-down { font-size: 10px; }
.batch-name { flex: 1; font-size: 13px; color: #303133; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.batch-detail { padding: 4px 12px 10px 44px; background: #fafafa; border-bottom: 1px solid #ebeef5; }

/* 执行进度 */
.exec-progress { margin-top: 12px; }
.exec-summary { display: flex; align-items: center; }
.exec-log { margin-top: 8px; max-height: 240px; overflow-y: auto; padding: 8px; background: #f5f7fa; border-radius: 6px; font-size: 12px; font-family: "Consolas", "Microsoft YaHei", monospace; line-height: 1.8; }
</style>
