<template>
  <div class="test-panel">
    <div class="section-title">PC VS 线上跟进执行</div>
    <el-alert type="info" :closable="false"
      title="对比 PC 执行成功 vs 线上执行成功，找出线上缺失/失败的 Jira，支持批量在线上重新执行"></el-alert>
    <!-- 步骤1：对比 -->
    <el-card shadow="never" style="margin-top:12px">
      <template #header><span style="font-weight:700">① 对比 PC vs 线上执行</span></template>
      <el-button type="primary" :loading="onlineFollowup.comparing" @click="compareOnlineFollowup">开始对比</el-button>
      <el-button size="small" @click="loadOnlineFollowup">加载历史</el-button>
      <el-tag v-if="onlineFollowup.date" style="margin-left:8px">数据日期: {{ onlineFollowup.date }}</el-tag>
      <div v-if="onlineFollowup.msg" style="margin-top:6px;font-size:13px"
        :style="{color: onlineFollowup.error ? '#f56c6c' : '#67c23a'}">{{ onlineFollowup.msg }}</div>
      <div v-if="onlineFollowup.pcSuccessCount" style="margin-top:8px;display:flex;gap:12px;flex-wrap:wrap">
        <el-tag type="info">PC成功: {{ onlineFollowup.pcSuccessCount }}</el-tag>
        <el-tag type="success">线上成功: {{ onlineFollowup.onlineSuccessCount }}</el-tag>
        <el-tag type="danger">差集: {{ onlineFollowup.diffCount }}</el-tag>
      </div>
    </el-card>
    <!-- 步骤2：差集表格 -->
    <el-card v-if="onlineFollowup.diffRecords.length" shadow="never" style="margin-top:12px">
      <template #header><span style="font-weight:700">② PC成功但线上缺失/失败（{{ onlineFollowup.diffRecords.length }} 条）</span></template>
      <el-table :data="onlineFollowup.diffRecords" size="small" stripe border max-height="360"
        @selection-change="rows => onlineFollowup.selectedDiff = rows">
        <el-table-column type="selection" width="40"></el-table-column>
        <el-table-column type="index" label="#" width="45"></el-table-column>
        <el-table-column prop="jira号" label="Jira号" width="130"></el-table-column>
        <el-table-column prop="pc分析完成时间" label="PC完成时间" width="160"></el-table-column>
        <el-table-column prop="触发时间" label="触发时间" width="160">
          <template #default="{row}"><span v-if="row['触发时间']" style="color:#67c23a">{{ row['触发时间'] }}</span><span v-else style="color:#c0c4cc">-</span></template>
        </el-table-column>
        <el-table-column prop="线上状态" label="线上状态" width="100">
          <template #default="{row}">
            <el-tag :type="row['线上状态']==='线上未执行'?'warning':'danger'" size="small">{{ row['线上状态'] }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="线上错误信息" label="线上错误信息" min-width="200" show-overflow-tooltip>
          <template #default="{row}"><span v-if="row['线上错误信息']" style="color:#f56c6c">{{ row['线上错误信息'] }}</span><span v-else style="color:#c0c4cc">-</span></template>
        </el-table-column>
      </el-table>
    </el-card>
    <!-- 步骤3：批量线上执行 -->
    <el-card v-if="onlineFollowup.diffRecords.length" shadow="never" style="margin-top:12px">
      <template #header><span style="font-weight:700">③ 批量在线上执行</span></template>
      <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
        <el-tag>已选: {{ onlineFollowup.selectedDiff.length }} 条</el-tag>
        <el-form-item label="每批数量" style="margin-bottom:0">
          <el-input-number v-model="onlineFollowup.batchSize" :min="1" :max="100" style="width:110px"></el-input-number>
        </el-form-item>
        <el-button type="primary" :loading="onlineFollowup.running"
          :disabled="!onlineFollowup.selectedDiff.length" @click="runOnlineFollowup">开始执行</el-button>
        <el-button type="success" :loading="onlineFollowup.writingTriggerTime"
          :disabled="!onlineFollowup.selectedDiff.length" @click="writeTriggerTimeBatch">一键写入触发时间</el-button>
        <el-checkbox v-model="onlineFollowup.skipCloudCache">跳过云端缓存</el-checkbox>
        <el-tag v-if="onlineFollowup.runTotal">进度: {{ onlineFollowup.runDone }}/{{ onlineFollowup.runTotal }}</el-tag>
      </div>
      <el-table v-if="onlineFollowup.runResults.length" :data="onlineFollowup.runResults" size="small" stripe border max-height="260" style="margin-top:10px">
        <el-table-column type="index" label="#" width="45"></el-table-column>
        <el-table-column prop="jira号" label="Jira号" width="130"></el-table-column>
        <el-table-column label="结果" width="80">
          <template #default="{row}"><el-tag :type="row['执行结果']==='成功'?'success':'danger'" size="small">{{ row['执行结果'] }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="触发时间" label="触发时间" width="160"></el-table-column>
        <el-table-column prop="备注" label="备注" min-width="200" show-overflow-tooltip></el-table-column>
      </el-table>
      <div v-if="onlineFollowup.runMsg" style="margin-top:6px;font-size:13px;color:#67c23a">{{ onlineFollowup.runMsg }}</div>
    </el-card>
  </div>
</template>

<script lang="ts">
// @ts-nocheck
import { ElMessage, ElMessageBox } from 'element-plus';
import { api } from '../composables/utils';
export default {
  name: 'OnlineFollowupPanel',
  data() {
    return {
      onlineFollowup: {
        comparing: false, msg: '', error: false, date: '',
        pcSuccessCount: 0, onlineSuccessCount: 0, diffCount: 0,
        diffRecords: [], selectedDiff: [],
        batchSize: 10, running: false, runResults: [], runDone: 0, runTotal: 0, runMsg: '',
        writingTriggerTime: false, skipCloudCache: false,
      },
    };
  },
  methods: {
    async compareOnlineFollowup() {
      this.onlineFollowup.comparing = true;
      this.onlineFollowup.msg = ''; this.onlineFollowup.error = false;
      try {
        const body = await api('/api/test/online_followup_compare', { method: 'POST' });
        const d = body.data;
        this.onlineFollowup.date = d.date;
        this.onlineFollowup.pcSuccessCount = d.pc_success_count;
        this.onlineFollowup.onlineSuccessCount = d.online_success_count;
        this.onlineFollowup.diffCount = d.diff_count;
        this.onlineFollowup.diffRecords = d.diff_records || [];
        this.onlineFollowup.selectedDiff = [];
        this.onlineFollowup.msg = body.message;
      } catch (e) {
        this.onlineFollowup.msg = '对比失败: ' + e.message;
        this.onlineFollowup.error = true;
      } finally { this.onlineFollowup.comparing = false; }
    },
    async loadOnlineFollowup() {
      try {
        const body = await api('/api/test/online_followup_load');
        const d = body.data;
        if (!d) { this.onlineFollowup.msg = '无历史对比数据'; return; }
        this.onlineFollowup.date = d.date;
        this.onlineFollowup.pcSuccessCount = d.pc_success_count;
        this.onlineFollowup.onlineSuccessCount = d.online_success_count;
        this.onlineFollowup.diffCount = d.diff_count;
        this.onlineFollowup.diffRecords = d.diff_records || [];
        this.onlineFollowup.selectedDiff = [];
        this.onlineFollowup.msg = body.message;
      } catch (e) { this.onlineFollowup.msg = '加载失败: ' + e.message; this.onlineFollowup.error = true; }
    },
    async runOnlineFollowup() {
      const selected = this.onlineFollowup.selectedDiff;
      if (!selected.length) return ElMessage.warning('请先勾选要执行的记录');
      const bugids = selected.slice(0, this.onlineFollowup.batchSize).map(r => r['jira号']);
      this.onlineFollowup.running = true;
      this.onlineFollowup.runResults = []; this.onlineFollowup.runDone = 0;
      this.onlineFollowup.runTotal = bugids.length; this.onlineFollowup.runMsg = '';
      try {
        const resp = await fetch('/api/test/prod_batch_run', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ bugids, skip_existing: false, skip_cloud_cache: this.onlineFollowup.skipCloudCache }),
        });
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
              if (evt.type === 'progress') {
                this.onlineFollowup.runDone = evt.index;
                this.onlineFollowup.runResults.push({ 'jira号': evt.bugid, '执行结果': evt.status === 'success' ? '成功' : '失败', '触发时间': evt.exec_time || '', '备注': evt.msg || '' });
              } else if (evt.type === 'done') {
                this.onlineFollowup.runMsg = evt.message || '执行完成';
              }
            } catch (e) { /* ignore */ }
          }
        }
        this.onlineFollowup.runMsg = `执行完成: ${this.onlineFollowup.runDone}/${this.onlineFollowup.runTotal}`;
      } catch (e) {
        this.onlineFollowup.runMsg = '执行失败: ' + e.message;
      } finally { this.onlineFollowup.running = false; }
    },
    async writeTriggerTimeBatch() {
      const selected = this.onlineFollowup.selectedDiff;
      if (!selected.length) return ElMessage.warning('请先勾选要写入的记录');
      const withTime = selected.filter(r => r['触发时间']);
      if (!withTime.length) return ElMessage.warning('勾选的记录均无触发时间');
      const triggerTimes = {};
      withTime.forEach(r => { triggerTimes[r['jira号']] = r['触发时间']; });
      const noTimeCount = selected.length - withTime.length;
      const skipCache = this.onlineFollowup.skipCloudCache;
      const skipMsg = skipCache ? '云端已有的自动跳过，仅写入缺失的' : '将强制覆盖云端所有触发时间';
      try {
        await ElMessageBox.confirm(
          `将把 ${withTime.length} 个有触发时间的记录写入云端缓存（${skipMsg}），不会重新提取。${noTimeCount ? '\n另有 ' + noTimeCount + ' 条无触发时间将被忽略。' : ''}`,
          '确认写入触发时间', { type: 'info', confirmButtonText: '确认写入', cancelButtonText: '取消' }
        );
      } catch { return; }
      this.onlineFollowup.writingTriggerTime = true;
      try {
        const body = await api('/api/test/write_trigger_time', {
          method: 'POST',
          body: JSON.stringify({ trigger_times: triggerTimes, skip_cloud_cache: skipCache })
        });
        const d = body.data || {};
        const parts = [];
        if (d.written_count) parts.push(`写入 ${d.written_count} 条`);
        if (d.skipped_count) parts.push(`跳过已有 ${d.skipped_count} 条`);
        if (d.failed_count) parts.push(`失败 ${d.failed_count} 条`);
        ElMessage.success(`写入完成: ${parts.join(', ') || '无变化'}`);
      } catch (e) {
        ElMessage.error('写入失败: ' + (e.message || '未知错误'));
      } finally { this.onlineFollowup.writingTriggerTime = false; }
    },
  },
};
</script>
