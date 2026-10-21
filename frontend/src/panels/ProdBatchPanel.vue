<template>
  <div class="test-panel">
    <div class="section-title">线上AI日志分析批量执行</div>
    <el-alert type="info" :closable="false"
      title="支持两种输入方式：① 直接输入Jira号 ② 从功能11的未分析CSV中选择。提取触发时间(优先云端) → 去重 → 批量调用线上AI分析接口"></el-alert>
    <!-- 方式1：直接输入Jira号 -->
    <el-card shadow="never" style="margin-top:12px">
      <template #header><span style="font-weight:600;font-size:13px">方式一：直接输入Jira号</span></template>
      <el-input v-model="prodBatch.directInput" type="textarea" :rows="3"
        placeholder="输入Jira号，支持逗号/分号/空格分隔，如: VCU-540049, VCU-540050"></el-input>
      <el-tag v-if="prodBatch.directInput.trim()" type="info" style="margin-top:6px">
        已输入 {{ prodBatch.directInput.replace(/[，;；\s]+/g, ',').split(',').filter(Boolean).length }} 个
      </el-tag>
      <div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap">
        <el-button size="small" type="primary" plain
          @click="prodBatch.jqlInput = 'issuetype = bug AND status != closed AND created >= &quot;2026/09/01&quot;'">
          9.1新增非close
        </el-button>
        <el-input v-model="prodBatch.jqlInput" size="small" placeholder="JQL查询" style="width:400px" @keyup.enter="prodJqlSearchFill"></el-input>
        <el-button size="small" type="success" :loading="prodBatch.jqlSearching" @click="prodJqlSearchFill">搜索并填入</el-button>
      </div>
      <el-tag v-if="prodBatch.jqlSearchMsg" :type="prodBatch.jqlSearchMsg.includes('失败') ? 'danger' : 'success'" style="margin-top:4px" size="small">{{ prodBatch.jqlSearchMsg }}</el-tag>
    </el-card>
    <!-- 方式2：选择CSV文件 -->
    <el-card shadow="never" style="margin-top:12px">
      <template #header><span style="font-weight:600;font-size:13px">方式二：从CSV文件选择</span></template>
      <el-button type="primary" :loading="running.prodLoadCsv" @click="prodLoadCsvFiles">加载文件列表</el-button>
      <div v-if="prodBatch.csvFiles.length" style="margin-top:10px">
        <div style="font-size:12px;color:#909399;margin-bottom:4px">未分析文件：</div>
        <el-checkbox-group v-model="prodBatch.selectedCsvs">
          <el-checkbox v-for="f in prodBatch.csvFiles" :key="f.path" :label="f.path" style="display:block;margin-bottom:4px">
            {{ f.name }} ({{ f.count }} 条)
          </el-checkbox>
        </el-checkbox-group>
      </div>
      <el-tag type="info" style="margin-top:6px" v-if="prodBatch.selectedCsvs.length">已选 {{ prodBatch.selectedCsvs.length }} 个文件</el-tag>
    </el-card>
    <!-- 执行 -->
    <el-card shadow="never" style="margin-top:12px" v-if="prodBatch.selectedCsvs.length || prodBatch.directInput.trim()">
      <template #header><span style="font-weight:600;font-size:13px">提取触发时间 + 去重 + 批量执行</span></template>
      <el-checkbox v-model="prodBatch.skipExisting" @change="onProdFilterAllChange" style="margin-bottom:8px;display:block">重复过滤（跳过多维表格中 parseFullTicket已成功 + 人工审核无效bug）</el-checkbox>
      <div style="display:flex;gap:16px;margin-bottom:8px;flex-wrap:wrap">
        <el-checkbox v-model="prodBatch.filterPcOnly" @change="onProdFilterSourceChange">过滤PC正确和通用失败的</el-checkbox>
        <el-checkbox v-model="prodBatch.filterOnlineOnly" @change="onProdFilterSourceChange">过滤线上正确和通用失败的</el-checkbox>
      </div>
      <el-form inline style="margin-bottom:8px">
        <el-form-item label="抽取数量" style="margin-bottom:0">
          <el-input-number v-model="prodBatch.maxCount" :min="0" :step="100" :precision="0" style="width:160px" placeholder="0=不限制"></el-input-number>
        </el-form-item>
        <span style="font-size:12px;color:#909399">（0=不限制，按去重后全量执行）</span>
      </el-form>
      <!-- 执行参数 -->
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap;font-size:12px;color:#606266">
        <span>分析并发:</span><el-input-number v-model="prodBatch.analysisConcurrency" :min="1" :max="50" size="small" style="width:80px" controls-position="right"></el-input-number>
        <span>下载并发:</span><el-input-number v-model="prodBatch.downloadConcurrency" :min="1" :max="20" size="small" style="width:80px" controls-position="right"></el-input-number>
        <span>模型:</span><el-input v-model="prodBatch.model" size="small" style="width:140px"></el-input>
        <span>触发来源:</span><el-input v-model="prodBatch.triggerSource" size="small" style="width:80px"></el-input>
      </div>
      <el-form inline style="margin-bottom:8px">
        <el-form-item style="margin-bottom:0"><el-checkbox v-model="prodBatch.continuous">持续执行</el-checkbox></el-form-item>
        <template v-if="prodBatch.continuous">
          <el-form-item label="间隔(min)" style="margin-bottom:0">
            <el-input-number v-model="prodBatch.interval" :min="1" :max="120" :step="1" :precision="0" style="width:110px"></el-input-number>
          </el-form-item>
          <el-form-item label="执行轮数" style="margin-bottom:0">
            <el-input-number v-model="prodBatch.rounds" :min="2" :max="100" :step="1" :precision="0" style="width:110px"></el-input-number>
          </el-form-item>
        </template>
      </el-form>
      <el-button type="danger" :loading="running.prodBatchRun" @click="prodBatchRun">
        {{ prodBatch.continuous ? `持续执行（${prodBatch.rounds} 轮）` : '开始执行' }}
      </el-button>
      <el-button v-if="running.prodBatchRun" type="warning" @click="prodBatchAbort && prodBatchAbort.abort()">停止</el-button>
      <div v-if="prodBatch.currentRound > 0 && prodBatch.continuous" style="margin-top:6px">
        <el-tag type="info">当前轮次: {{ prodBatch.currentRound }} / {{ prodBatch.rounds }}</el-tag>
        <el-tag v-if="prodBatch.continuousRunning" type="warning" style="margin-left:6px">{{ prodBatch.stage || '执行中' }}</el-tag>
      </div>
      <el-alert v-if="prodBatch.msg" :type="prodBatch.error ? 'error' : 'success'" :closable="false" :title="prodBatch.msg" style="margin-top:8px"></el-alert>
      <div v-if="prodBatch.stage && !(prodBatch.continuous && prodBatch.continuousRunning)" style="margin-top:8px">
        <el-tag type="warning">{{ prodBatch.stage }}</el-tag>
      </div>
      <el-table v-if="prodBatch.results.length" :data="prodBatch.results" size="small" stripe border max-height="300" style="margin-top:10px">
        <el-table-column type="index" label="#" width="45"></el-table-column>
        <el-table-column prop="jira号" label="Jira号" width="130"></el-table-column>
        <el-table-column label="结果" width="80">
          <template #default="{row}"><el-tag :type="row['执行结果']==='成功'?'success':'danger'" size="small">{{ row['执行结果'] }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="触发时间" label="触发时间" width="160" show-overflow-tooltip></el-table-column>
        <el-table-column prop="执行时间" label="执行时间" width="160" show-overflow-tooltip></el-table-column>
        <el-table-column prop="备注" label="备注" show-overflow-tooltip></el-table-column>
      </el-table>
      <el-tag v-if="prodBatch.doneMsg" type="success" style="margin-top:8px">{{ prodBatch.doneMsg }}</el-tag>
      <a v-if="prodBatch.cloudUrl" :href="prodBatch.cloudUrl" target="_blank" style="margin-left:8px;font-size:12px">查看云端记录</a>
    </el-card>
  </div>
</template>

<script lang="ts">
// @ts-nocheck
import { ElMessage } from 'element-plus';
import { api } from '../composables/utils';
export default {
  name: 'ProdBatchPanel',
  data() {
    return {
      running: { prodLoadCsv: false, prodBatchRun: false },
      prodBatch: {
        csvFiles: [], selectedCsvs: [], directInput: '',
        skipExisting: true, filterPcOnly: false, filterOnlineOnly: false, maxCount: 0, msg: '', error: false, stage: '',
        results: [], doneMsg: '', cloudUrl: '',
        analysisConcurrency: 5, downloadConcurrency: 2, model: 'deepseek-v-pro', triggerSource: '线上',
        jqlInput: 'issuetype = bug AND status != closed AND created >= "2026/09/01"',
        jqlSearching: false, jqlSearchMsg: '',
        continuous: false, interval: 6, rounds: 10, currentRound: 0, continuousRunning: false,
      },
      prodBatchAbort: null,
    };
  },
  methods: {
    onProdFilterAllChange(val) {
      if (val) { this.prodBatch.filterPcOnly = false; this.prodBatch.filterOnlineOnly = false; }
    },
    onProdFilterSourceChange() {
      if (this.prodBatch.filterPcOnly || this.prodBatch.filterOnlineOnly) { this.prodBatch.skipExisting = false; }
    },
    async prodJqlSearchFill() {
      const jql = this.prodBatch.jqlInput.trim();
      if (!jql) return ElMessage.warning('请输入 JQL');
      this.prodBatch.jqlSearching = true;
      this.prodBatch.jqlSearchMsg = '';
      try {
        const resp = await api('/api/test/batch_ai_search', { method: 'POST', body: JSON.stringify({ jql }) });
        const rows = resp.data?.rows || [];
        if (!rows.length) { this.prodBatch.jqlSearchMsg = '搜索无 VCU 结果'; return; }
        const keys = rows.map(r => r.key).join(', ');
        this.prodBatch.directInput = keys;
        this.prodBatch.jqlSearchMsg = `搜索到 ${resp.data.total} 条，VCU ${resp.data.vcu_count} 条，已填入`;
      } catch (e) {
        this.prodBatch.jqlSearchMsg = '搜索失败: ' + (e.message || e);
      } finally { this.prodBatch.jqlSearching = false; }
    },
    async prodLoadCsvFiles() {
      this.running.prodLoadCsv = true;
      try {
        const resp = await api('/api/test/prod_csv_files');
        this.prodBatch.csvFiles = resp.data?.unanalyzed || [];
        this.prodBatch.selectedCsvs = [];
        if (!this.prodBatch.csvFiles.length) ElMessage.warning('data/unanalyzed/ 下无 CSV 文件');
      } catch (e) { ElMessage.error('加载失败: ' + e.message); }
      finally { this.running.prodLoadCsv = false; }
    },
    async _prodBatchRunOnce(directIds, roundLabel, executedSet) {
      this.prodBatch.msg = ''; this.prodBatch.error = false; this.prodBatch.stage = '';
      this.prodBatch.doneMsg = ''; this.prodBatch.cloudUrl = '';
      this.prodBatchAbort = new AbortController();
      const roundExecuted = new Set();  // 本轮执行的 Jira 号
      try {
        const resp = await fetch('/api/test/prod_batch_run', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ bugids: directIds, csv_files: this.prodBatch.selectedCsvs, skip_existing: this.prodBatch.skipExisting, max_count: this.prodBatch.maxCount,
            filter_pc_only: this.prodBatch.filterPcOnly, filter_online_only: this.prodBatch.filterOnlineOnly,
            analysis_concurrency: this.prodBatch.analysisConcurrency, download_concurrency: this.prodBatch.downloadConcurrency,
            model: this.prodBatch.model, trigger_source: this.prodBatch.triggerSource }),
          signal: this.prodBatchAbort.signal,
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
              if (evt.type === 'start') {
                const skipInfo = evt.skipped ? `，重复跳过 ${evt.skipped}` : '';
                const maxInfo = evt.max_count ? `，抽取上限 ${evt.max_count}` : '';
                this.prodBatch.stage = `${roundLabel}开始执行：共 ${evt.total} 条（去重 ${evt.dedup}${skipInfo}${maxInfo}，原始 ${evt.raw}）`;
              } else if (evt.type === 'extract_progress') {
                this.prodBatch.stage = `${roundLabel}提取触发时间：${evt.current}/${evt.total}，命中 ${evt.hit}`;
              } else if (evt.type === 'extract_done') {
                this.prodBatch.stage = `${roundLabel}触发时间提取完成：有 ${evt.with_time}/${evt.total}，无 ${evt.without_time}`;
              } else if (evt.type === 'progress') {
                const row = { 'jira号': evt.bugid, '执行结果': evt.status === 'success' ? '成功' : '失败', '触发时间': evt.exec_time, '执行时间': evt.analysis_time, '备注': evt.msg };
                this.prodBatch.results.push(row);
                // 记录本轮已执行的 Jira 号（无论成功失败都记录，避免重复提交）
                if (evt.bugid) roundExecuted.add(evt.bugid);
                this.prodBatch.stage = `${roundLabel}执行中：${evt.index}/${evt.total}`;
              } else if (evt.type === 'done') {
                this.prodBatch.doneMsg = evt.message;
                this.prodBatch.cloudUrl = evt.cloud_url || '';
                this.prodBatch.msg = `${roundLabel}批量执行完成`; this.prodBatch.error = false;
                this.prodBatch.stage = '';
              } else if (evt.type === 'error') {
                this.prodBatch.msg = `${roundLabel}${evt.message}`; this.prodBatch.error = true;
                this.prodBatch.stage = '';
              }
            } catch (e) { /* ignore */ }
          }
        }
      } catch (e) {
        if (e.name !== 'AbortError') { this.prodBatch.msg = `${roundLabel}执行失败: ${e.message}`; this.prodBatch.error = true; }
        else { throw e; }
      } finally {
        // 将本轮执行的 Jira 号合并到跨轮去重集合
        if (executedSet && roundExecuted.size > 0) {
          for (const id of roundExecuted) executedSet.add(id);
        }
      }
    },
    async prodBatchRun() {
      const directIds = this.prodBatch.directInput.replace(/[，;；\s]+/g, ',').split(',').map(s => s.trim()).filter(Boolean);
      if (!directIds.length && !this.prodBatch.selectedCsvs.length) return ElMessage.warning('请输入Jira号或选择CSV文件');
      this.running.prodBatchRun = true;
      this.prodBatch.results = [];
      this.prodBatch.continuousRunning = false;
      if (!this.prodBatch.continuous) {
        this.prodBatch.currentRound = 0;
        try { await this._prodBatchRunOnce(directIds, ''); }
        catch (e) {
          if (e.name === 'AbortError') { this.prodBatch.msg = '已停止执行'; this.prodBatch.error = false; }
          else { this.prodBatch.msg = `执行失败: ${e.message}`; this.prodBatch.error = true; }
        }
      } else {
        this.prodBatch.continuousRunning = true;
        const totalRounds = this.prodBatch.rounds;
        const intervalMs = this.prodBatch.interval * 60 * 1000;
        // 跨轮去重：记录已执行的 Jira 号，后续轮次不再重复提交
        const executedSet = new Set();
        let remainingIds = [...directIds];
        for (let i = 1; i <= totalRounds; i++) {
          this.prodBatch.currentRound = i;
          const roundLabel = `[${i}/${totalRounds}] `;
          // 过滤本轮已执行的
          if (executedSet.size > 0) {
            remainingIds = remainingIds.filter(id => !executedSet.has(id));
          }
          if (!remainingIds.length && !this.prodBatch.selectedCsvs.length) {
            this.prodBatch.msg = `所有 ${executedSet.size} 条已在前几轮执行完毕，提前结束（完成 ${i - 1}/${totalRounds} 轮）`;
            this.prodBatch.error = false; break;
          }
          const idsForRound = remainingIds.length ? remainingIds : directIds;
          try { await this._prodBatchRunOnce(idsForRound, roundLabel, executedSet); }
          catch (e) {
            this.prodBatch.msg = `持续执行已停止（完成 ${i - 1}/${totalRounds} 轮，已执行 ${executedSet.size} 条）`;
            this.prodBatch.error = false; break;
          }
          if (i < totalRounds) {
            const waitUntil = Date.now() + intervalMs;
            this.prodBatch.stage = `等待下一轮（${this.prodBatch.interval} 分钟后开始第 ${i + 1}/${totalRounds} 轮，已执行 ${executedSet.size} 条）`;
            while (Date.now() < waitUntil) {
              if (this.prodBatchAbort && this.prodBatchAbort.signal.aborted) break;
              const remainSec = Math.ceil((waitUntil - Date.now()) / 1000);
              const mm = Math.floor(remainSec / 60);
              const ss = remainSec % 60;
              this.prodBatch.stage = `等待下一轮（${mm}:${String(ss).padStart(2, '0')} 后开始第 ${i + 1}/${totalRounds} 轮，已执行 ${executedSet.size} 条）`;
              await new Promise(r => setTimeout(r, 1000));
            }
          }
        }
        this.prodBatch.continuousRunning = false;
        if (!this.prodBatch.error && !this.prodBatch.msg.includes('已停止') && !this.prodBatch.msg.includes('提前结束')) {
          this.prodBatch.msg = `持续执行完成：共 ${this.prodBatch.currentRound} 轮，累计执行 ${executedSet.size} 条不重复`;
        }
      }
      this.running.prodBatchRun = false;
    },
  },
};
</script>
