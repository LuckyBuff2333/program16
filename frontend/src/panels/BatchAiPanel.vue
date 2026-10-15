<template>
  <div class="test-panel">
    <div style="color:#e6302e;font-size:12px;margin-bottom:8px">※ 请在内网环境下执行测试</div>
    <el-tabs v-model="activeTab" type="border-card" class="batch-tabs">

      <!-- ==================== 批量执行 ==================== -->
      <el-tab-pane label="批量执行" name="batch">
        <!-- ① 查询条件 -->
        <div class="exec-section">
          <div class="section-label">查询条件</div>
          <div class="input-row">
            <el-input v-model="batchAi.jql" placeholder="JQL 查询语句" clearable>
              <template #prepend>JQL</template>
            </el-input>
          </div>
          <div class="preset-bar">
            <el-button size="small" :type="batchAi.jql===p?void 0:'info'"
              v-for="(p,i) in batchAi.jqlPresets" :key="i"
              @click="batchAi.jql=p">{{ batchAi.jqlLabels[i] }}</el-button>
          </div>
        </div>

        <!-- ② 执行模式 -->
        <div class="exec-section">
          <div class="section-label">执行模式</div>
          <div class="action-bar">
            <div class="action-left">
              <el-radio-group v-model="batchAi.execMode" size="default">
                <el-radio value="pc" border @change="setBatchMeta('batchAi','pc')">PC</el-radio>
                <el-radio value="online" border @change="setBatchMeta('batchAi','online')">线上</el-radio>
              </el-radio-group>
              <el-divider direction="vertical" />
              <el-input-number v-model="batchAi.sampleCount" :min="1" :max="200" size="default" style="width:110px" controls-position="right"></el-input-number>
              <span class="field-hint">抽取数量</span>
            </div>
          </div>
          <div class="continuous-bar">
            <el-checkbox v-model="batchAi.continuous">持续执行</el-checkbox>
            <template v-if="batchAi.continuous">
              <span class="param-label">间隔</span>
              <el-input-number v-model="batchAi.interval" :min="1" :max="120" size="small" style="width:90px" controls-position="right"></el-input-number>
              <span class="param-hint">min</span>
              <span class="param-label">轮数</span>
              <el-input-number v-model="batchAi.rounds" :min="2" :max="100" size="small" style="width:90px" controls-position="right"></el-input-number>
            </template>
          </div>
        </div>

        <!-- ③ 过滤选项 -->
        <div v-if="batchAi.execMode === 'pc'" class="exec-section">
          <div class="filter-bar">
            <div class="section-label">过滤选项</div>
            <div class="filter-row">
              <el-checkbox v-model="batchAi.filterExistingSuccess">过滤已存在记录成功case</el-checkbox>
            </div>
          </div>
        </div>
        <div v-else-if="batchAi.execMode === 'online'" class="exec-section">
          <div class="filter-bar">
            <div class="section-label">过滤选项</div>
            <div class="filter-row">
              <el-checkbox v-model="batchAi.filterAiPreliminary">过滤有AI字段数据</el-checkbox>
            </div>
          </div>
        </div>

        <!-- ④ 测试环境设置 -->
        <div class="exec-section">
          <div class="env-settings">
            <div class="section-label">测试环境设置</div>
            <div v-if="batchAi.execMode === 'pc'" class="params-grid">
              <div class="param-item">
                <span class="param-label">分析并发</span>
                <el-input-number v-model="batchAi.analysisConcurrency" :min="1" :max="50" size="small" style="width:90px" controls-position="right"></el-input-number>
              </div>
              <div class="param-item">
                <span class="param-label">下载并发</span>
                <el-input-number v-model="batchAi.downloadConcurrency" :min="1" :max="20" size="small" style="width:90px" controls-position="right"></el-input-number>
              </div>
              <div class="param-item">
                <span class="param-label">模型</span>
                <el-input v-model="batchAi.model" size="small" style="width:150px"></el-input>
              </div>
              <div class="param-item">
                <span class="param-label">触发来源</span>
                <el-input v-model="batchAi.triggerSource" size="small" style="width:90px" disabled></el-input>
              </div>
              <div class="param-item">
                <span class="param-label required-label">软件版本</span>
                <el-input v-model="batchAi.softwareVersion" size="small" style="width:120px" placeholder="必填" :class="{ 'is-error': !batchAi.softwareVersion }"></el-input>
              </div>
            </div>
            <div v-else-if="batchAi.execMode === 'online'" class="params-grid">
              <div class="param-item">
                <span class="param-label">分析并发</span>
                <el-input-number v-model="batchAi.analysisConcurrency" :min="1" :max="20" size="small" style="width:90px" controls-position="right"></el-input-number>
              </div>
              <div class="param-item">
                <span class="param-label">下载并发</span>
                <el-input-number v-model="batchAi.downloadConcurrency" :min="1" :max="10" size="small" style="width:90px" controls-position="right"></el-input-number>
              </div>
              <div class="param-item">
                <span class="param-label">模型</span>
                <el-input v-model="batchAi.model" size="small" style="width:150px"></el-input>
              </div>
              <div class="param-item">
                <span class="param-label">触发来源</span>
                <el-input v-model="batchAi.triggerSource" size="small" style="width:90px" disabled></el-input>
              </div>
              <div class="param-item">
                <span class="param-label required-label">软件版本</span>
                <el-input v-model="batchAi.softwareVersion" size="small" style="width:120px" placeholder="必填" :class="{ 'is-error': !batchAi.softwareVersion }"></el-input>
              </div>
            </div>
            <div v-else style="font-size:12px;color:#909399">请先选择执行环境（PC 或线上）</div>
            <div v-if="batchAi.execMode" class="env-save-bar">
              <el-button size="small" type="primary" @click="saveEnvSettings">保存设置</el-button>
              <el-tag v-if="batchAi.envSavedMsg" type="success" size="small">{{ batchAi.envSavedMsg }}</el-tag>
            </div>
          </div>
        </div>

        <!-- ⑤ 执行按钮 -->
        <div class="execute-bar">
          <el-button type="primary" size="large" :loading="running.batchOneClick" :disabled="!batchAi.execMode || !batchAi.softwareVersion" @click="batchAiOneClick">
            {{ batchAi.continuous ? `持续执行（${batchAi.rounds} 轮）` : '一键执行' }}
          </el-button>
          <el-button v-if="running.batchOneClick && batchAi.continuous" type="danger" size="large" @click="batchAiAbort && batchAiAbort.abort()">停止</el-button>
        </div>
        <el-alert v-if="batchAi.oneClickMsg" :type="batchAi.oneClickError ? 'error' : 'success'" :closable="false" :title="batchAi.oneClickMsg" style="margin-top:10px"></el-alert>
        <div v-if="batchAi.currentRound > 0 && batchAi.continuousRunning" class="round-info">
          <el-tag type="info">当前轮次: {{ batchAi.currentRound }} / {{ batchAi.rounds }}</el-tag>
          <el-tag v-if="batchAi.preSample" :type="batchAi.preSample.ready ? 'success' : (batchAi.preSample.error ? 'danger' : 'warning')" style="margin-left:6px">
            下一轮预提取: {{ batchAi.preSample.ready ? '✅ 就绪' : (batchAi.preSample.error ? '❌ 失败' : '⏳ 提取中') }}
          </el-tag>
        </div>
        <div v-if="running.batchOneClick || batchAi.sampleStats" class="progress-card">
          <div v-if="batchAi.sampleStats" class="stats-row">
            <el-tag type="info" size="small">搜索: {{ batchAi.sampleStats.searched || 0 }}</el-tag>
            <el-tag type="success" size="small">过滤后: {{ batchAi.sampleStats.filtered || 0 }}</el-tag>
            <el-tag type="warning" size="small">抽样: {{ batchAi.sampleStats.sampled || 0 }}</el-tag>
            <el-tag v-if="batchAi.sampleStats.extract_time" type="success" size="small">提取时间: {{ batchAi.sampleStats.extract_time }}</el-tag>
            <el-tag v-if="batchAi.sampleStats.extract_failed" type="warning" size="small">失败跳过: {{ batchAi.sampleStats.extract_failed }}</el-tag>
          </div>
          <div v-if="batchAi.selected.length" class="selected-tags">
            <el-tag v-for="b in batchAi.selected.slice(0,20)" :key="b"
              :type="batchAi.triggerTimes[b] ? 'success' : 'info'" size="small">
              {{ b }}<span v-if="batchAi.triggerTimes[b]" class="time-hint">({{ batchAi.triggerTimes[b] }})</span>
            </el-tag>
            <el-tag v-if="batchAi.selected.length > 20" type="info" size="small">...还有 {{ batchAi.selected.length - 20 }} 条</el-tag>
          </div>
        </div>
        <el-table v-if="batchAi.runResults.length" :data="batchAi.runResults" size="small" stripe border max-height="260" style="margin-top:10px">
          <el-table-column type="index" label="#" width="45"></el-table-column>
          <el-table-column prop="jira号" label="Jira号" width="130"></el-table-column>
          <el-table-column label="结果" width="80">
            <template #default="{row}"><el-tag :type="row['执行结果']==='成功'?'success':'danger'" size="small">{{ row['执行结果'] }}</el-tag></template>
          </el-table-column>
          <el-table-column prop="触发时间" label="触发时间" width="160" show-overflow-tooltip></el-table-column>
          <el-table-column prop="执行时间" label="执行时间" width="160" show-overflow-tooltip></el-table-column>
          <el-table-column prop="备注" label="备注" show-overflow-tooltip></el-table-column>
        </el-table>
        <el-alert v-if="batchAi.runDoneMsg" type="success" :closable="false" :title="batchAi.runDoneMsg" style="margin-top:10px"></el-alert>
      </el-tab-pane>

      <!-- ==================== 单个执行 ==================== -->
      <el-tab-pane label="单个执行" name="single">
        <div class="exec-section">
          <div class="section-label">输入 Jira 号</div>
          <el-input v-model="aiDirect.bugidsRaw" type="textarea" :rows="3"
            placeholder="支持换行、逗号、空格分隔，如：VCU-538942, VCU-200273" @change="parseAiDirectBugids"></el-input>
          <el-tag v-if="aiDirect.parsed.length" type="info" size="small" style="margin-top:8px">已解析 {{ aiDirect.parsed.length }} 个 Jira 号（已去重）</el-tag>
        </div>

        <div v-if="aiDirect.parsed.length" class="exec-section">
          <div class="filter-row">
            <el-checkbox v-model="aiDirect.filterPcSuccess" size="small">过滤 PC 已成功</el-checkbox>
            <el-checkbox v-model="aiDirect.filterOnlineSuccess" size="small">过滤线上已成功</el-checkbox>
            <el-button v-if="aiDirect.filterPcSuccess || aiDirect.filterOnlineSuccess" type="warning" size="small" :loading="aiDirect.filterLoading" @click="applyAiDirectFilter">应用过滤</el-button>
            <el-tag v-if="aiDirect.filterInfo" type="success" size="small">{{ aiDirect.filterInfo }}</el-tag>
          </div>
        </div>

        <div class="exec-section">
          <div class="action-bar">
            <div class="action-left">
              <el-radio-group v-model="aiDirect.execMode" size="default">
                <el-radio value="pc" border @change="setBatchMeta('aiDirect','pc')">PC</el-radio>
                <el-radio value="online" border @change="setBatchMeta('aiDirect','online')">线上</el-radio>
              </el-radio-group>
            </div>
            <div class="action-right">
              <el-button type="primary" size="large" :loading="running.aiDirectRun" :disabled="!aiDirect.parsed.length || !aiDirect.execMode"
                @click="runAiDirectOneClick">执行（{{ aiDirect.parsed.length }} 条）</el-button>
              <el-button v-if="running.aiDirectRun" type="danger" size="large" @click="stopAiDirectAnalyze">停止</el-button>
              <el-tag v-if="aiDirect.runTotal" type="info" size="small">{{ aiDirect.runDone }} / {{ aiDirect.runTotal }}</el-tag>
            </div>
          </div>

        </div>

        <el-table v-if="aiDirect.timeRows.length" :data="aiDirect.timeRows" size="small" stripe border max-height="200" style="margin-top:10px">
          <el-table-column type="index" label="#" width="45"></el-table-column>
          <el-table-column prop="jira号" label="Jira号" width="130"></el-table-column>
          <el-table-column prop="触发时间" label="触发时间" width="180">
            <template #default="{row}"><span :style="row['触发时间']?'':'color:#909399'">{{ row['触发时间'] || '未提取到' }}</span></template>
          </el-table-column>
          <el-table-column prop="来源" label="来源" width="100">
            <template #default="{row}">
              <el-tag v-if="row['来源']==='本地'" type="success" size="small">本地缓存</el-tag>
              <el-tag v-else-if="row['来源']==='新提取'" type="warning" size="small">新提取</el-tag>
              <el-tag v-else type="info" size="small">无</el-tag>
            </template>
          </el-table-column>
        </el-table>
        <el-table v-if="aiDirect.runResults.length" :data="aiDirect.runResults" size="small" stripe border max-height="260" style="margin-top:10px">
          <el-table-column type="index" label="#" width="45"></el-table-column>
          <el-table-column prop="jira号" label="Jira号" width="130"></el-table-column>
          <el-table-column prop="执行结果" label="结果" width="80">
            <template #default="{row}"><el-tag :type="row['执行结果']==='成功'?'success':'danger'" size="small">{{ row['执行结果'] }}</el-tag></template>
          </el-table-column>
          <el-table-column prop="备注" label="接口返回验证" min-width="220" show-overflow-tooltip></el-table-column>
          <el-table-column prop="触发时间" label="触发时间" width="160" show-overflow-tooltip></el-table-column>
          <el-table-column prop="执行时间" label="执行时间" width="160" show-overflow-tooltip></el-table-column>
        </el-table>
        <el-alert v-if="aiDirect.runDoneMsg" type="success" :closable="false" :title="aiDirect.runDoneMsg" style="margin-top:10px"></el-alert>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script lang="ts">
// @ts-nocheck
import { ElMessage } from 'element-plus';
import { api } from '../composables/utils';
export default {
  name: 'BatchAiPanel',
  data() {
    return {
      activeTab: 'batch',
      running: { batchSearch: false, batchExtract: false, batchFilter: false, batchSample: false, batchRun: false, batchOneClick: false, aiDirectExtract: false, aiDirectRun: false, batchAssess: false },
      batchAiAbort: null,
      aiDirectAbort: null,
      batchAiExtractAbort: null,
      aiDirect: {
        bugidsRaw: '', parsed: [],
        extracting: false, triggerTimes: {}, timeRows: [],
        runResults: [], runTotal: 0, runDone: 0, runDoneMsg: '',
        execMode: '',
        analysisConcurrency: 10, downloadConcurrency: 4, model: 'deepseek-v-pro', triggerSource: 'PC', softwareVersion: '',
        filterPcSuccess: false, filterOnlineSuccess: false,
        filterLoading: false, filterInfo: '',
      },
      batchAi: { jql: 'issuetype = bug AND text ~ "远控" AND text ~ "VCU"', jqlPresets: ['issuetype = bug AND text ~ "远控" AND text ~ "VCU"', 'issuetype = bug AND text ~ "coreservice" AND text ~ "VCU"', 'issuetype = bug AND text ~ "SGM_Navigation750" AND text ~ "VCU"', 'issuetype = bug AND text ~ "VCU" AND created >= "2026/08/15" AND created <= now() AND status != CLOSED', 'issuetype = bug AND text ~ "SGM_Navigation750" AND created >= "2026/08/25" AND status = closed', 'issuetype = bug AND text ~ "远控" AND created >= "2026/08/25" AND status = closed', 'issuetype = bug AND text ~ "coreservice" AND created >= "2026/08/25" AND status = closed', 'issuetype = bug AND created >= "2026/08/25" AND status = closed AND (text ~ "RES1.1" OR text ~ "RES1.0")', 'issuetype = bug AND status != closed AND created >= "2026/09/01"'], jqlLabels: ['远控', 'coreservice', '导航', 'VCU近期未关闭', '8.25后已关闭导航', '8.25后远控', '8.25后coreservice', '8.25后RES1.0/1.1', '9.1新增非close'], sampleCount: 5, filterAllExisting: false, filterPcOnly: false, filterOnlineOnly: false, filterAiPreliminary: false, filterExistingSuccess: false, skipTimeExtraction: false, execMode: '', analysisConcurrency: 10, downloadConcurrency: 4, model: 'deepseek-v-pro', triggerSource: 'PC', softwareVersion: '', envSavedMsg: '', rows: [], searchMsg: '', searchError: false, extractMsg: '', extractError: false, filteredKeys: [], filterMsg: '', filterError: false, selected: [], sampleMsg: '', sampleError: false, sampleStats: null, triggerTimes: {}, runResults: [], runTotal: 0, runDone: 0, runDoneMsg: '', oneClickMsg: '', oneClickError: false, extractProgress: 0, extractTotal: 0, extractLocalHit: 0, qualityAssess: null, qualityAssessErr: '', continuous: false, interval: 6, rounds: 10, currentRound: 0, continuousRunning: false, preSample: null },
    };
  },
  methods: {
    async batchAiSearch() {
      if (!this.batchAi.jql.trim()) return ElMessage.warning('请输入 JQL');
      this.running.batchSearch = true;
      this.batchAi.searchMsg = ''; this.batchAi.searchError = false;
      this.batchAi.rows = []; this.batchAi.selected = []; this.batchAi.runResults = []; this.batchAi.runDoneMsg = '';
      this.batchAi.extractMsg = ''; this.batchAi.triggerTimes = {}; this.batchAi.csvTriggerTimes = {}; this.batchAi.filteredKeys = []; this.batchAi.filterMsg = '';
      try {
        const body = await api('/api/test/batch_ai_search', { method: 'POST', body: JSON.stringify({ jql: this.batchAi.jql }) });
        this.batchAi.rows = body.data.rows;
        this.batchAi.searchMsg = body.message;
      } catch (e) { this.batchAi.searchMsg = e.message || '搜索失败'; this.batchAi.searchError = true; } finally { this.running.batchSearch = false; }
    },
    onFilterAllChange(val) { if (val) { this.batchAi.filterPcOnly = false; this.batchAi.filterOnlineOnly = false; } },
    onFilterSourceChange() { if (this.batchAi.filterPcOnly || this.batchAi.filterOnlineOnly) { this.batchAi.filterAllExisting = false; } },
    async batchAiFilter() {
      if (!this.batchAi.rows.length) return ElMessage.warning('请先执行步骤1');
      this.running.batchFilter = true; this.batchAi.filterMsg = ''; this.batchAi.filterError = false; this.batchAi.filteredKeys = [];
      try {
        const keys = this.batchAi.rows.map(r => r.key);
        const body = await api('/api/test/batch_ai_filter', { method: 'POST', body: JSON.stringify({
          keys, filter_all: this.batchAi.filterAllExisting, filter_pc_only: this.batchAi.filterPcOnly,
          filter_online_only: this.batchAi.filterOnlineOnly, filter_ai_preliminary: this.batchAi.filterAiPreliminary,
          filter_existing_success: this.batchAi.filterExistingSuccess
        }) });
        this.batchAi.filteredKeys = body.data.filtered || [];
        this.batchAi.filterMsg = body.message;
      } catch (e) { this.batchAi.filterMsg = e.message || '过滤失败'; this.batchAi.filterError = true; } finally { this.running.batchFilter = false; }
    },
    async batchAiSample(silent = false) {
      if (!this.batchAi.filteredKeys.length && !this.batchAi.rows.length) {
        if (!silent) ElMessage.warning('请先执行步骤1和步骤3');
        return null;
      }
      if (!silent) {
        this.running.batchSample = true;
        this.batchAi.sampleMsg = ''; this.batchAi.sampleError = false;
        this.batchAi.selected = []; this.batchAi.runResults = []; this.batchAi.runDoneMsg = ''; this.batchAi.sampleStats = null;
      }
      const sampleAbort = AbortSignal.timeout(600000);
      try {
        const keys = this.batchAi.filteredKeys.length ? this.batchAi.filteredKeys : this.batchAi.rows.map(r => r.key);
        const body = await api('/api/test/batch_ai_sample', { method: 'POST', body: JSON.stringify({ keys, count: this.batchAi.sampleCount, csv_trigger_times: this.batchAi.csvTriggerTimes }), signal: sampleAbort });
        const result = { selected: body.data.selected, trigger_times: body.data.trigger_times || {},
          sampleStats: { selected: body.data.selected_count || 0, cloud_picked: body.data.cloud_picked || 0, csv_hit: body.data.csv_hit || 0, new_extracted: body.data.new_extracted || 0, extract_failed: body.data.extract_failed || 0 },
          message: body.message };
        if (!silent) { this.batchAi.selected = result.selected; this.batchAi.triggerTimes = result.trigger_times; this.batchAi.sampleStats = result.sampleStats; this.batchAi.sampleMsg = result.message; }
        return result;
      } catch (e) {
        if (!silent) { this.batchAi.sampleMsg = e.message || '抽取失败'; this.batchAi.sampleError = true; }
        return null;
      } finally { if (!silent) this.running.batchSample = false; }
    },
    async batchAiRun() {
      if (!this.batchAi.selected.length) return ElMessage.warning('请先执行步骤3');
      this.running.batchRun = true;
      this.batchAi.runResults = []; this.batchAi.runTotal = this.batchAi.selected.length; this.batchAi.runDone = 0; this.batchAi.runDoneMsg = '';
      this.batchAiAbort = new AbortController();
      try {
        const resp = await fetch('/api/test/batch_ai_run', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ bugids: this.batchAi.selected, trigger_times: this.batchAi.triggerTimes,
            analysis_concurrency: this.batchAi.analysisConcurrency, download_concurrency: this.batchAi.downloadConcurrency,
            model: this.batchAi.model, trigger_source: this.batchAi.triggerSource, software_version: this.batchAi.softwareVersion }),
          signal: this.batchAiAbort.signal,
        });
        const reader = resp.body.getReader(); const decoder = new TextDecoder(); let buffer = '';
        while (true) {
          const { done, value } = await reader.read(); if (done) break;
          buffer += decoder.decode(value, { stream: true }); const lines = buffer.split('\n'); buffer = lines.pop() || '';
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            try {
              const evt = JSON.parse(line.slice(6));
              if (evt.type === 'progress') {
                this.batchAi.runDone = evt.index;
                this.batchAi.runResults.push({ 'jira号': evt.bugid, '执行结果': evt.status === 'success' ? '成功' : '失败', '报告长度': evt.report_len || 0, '备注': evt.msg || '', '触发时间': evt.exec_time || '', '执行时间': evt.analysis_time || '' });
              } else if (evt.type === 'done') {
                let doneMsg = `全部完成: ${evt.success}/${evt.total} 成功`;
                if (evt.skipped) doneMsg += `，已跳过 ${evt.skipped} 条`;
                doneMsg += `，已写入 ${evt.csv_path}`;
                this.batchAi.runDoneMsg = doneMsg;
              }
            } catch (e) { /* ignore */ }
          }
        }
      } catch (e) { if (e.name === 'AbortError') ElMessage.warning('已停止'); else ElMessage.error('批量执行失败: ' + e.message); }
      finally { this.running.batchRun = false; }
    },
    async batchAiRunOnline() {
      if (!this.batchAi.selected.length) return ElMessage.warning('请先执行抽样');
      this.running.batchRun = true;
      this.batchAi.runResults = []; this.batchAi.runTotal = this.batchAi.selected.length; this.batchAi.runDone = 0; this.batchAi.runDoneMsg = '';
      this.batchAiAbort = new AbortController();
      try {
        const resp = await fetch('/api/test/prod_batch_run', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ bugids: this.batchAi.selected, trigger_times: this.batchAi.triggerTimes, skip_existing: false,
            exec_mode: this.batchAi.execMode,
            analysis_concurrency: this.batchAi.analysisConcurrency, download_concurrency: this.batchAi.downloadConcurrency,
            model: this.batchAi.model, trigger_source: this.batchAi.triggerSource, software_version: this.batchAi.softwareVersion }),
          signal: this.batchAiAbort.signal,
        });
        const reader = resp.body.getReader(); const decoder = new TextDecoder(); let buffer = '';
        while (true) {
          const { done, value } = await reader.read(); if (done) break;
          buffer += decoder.decode(value, { stream: true }); const lines = buffer.split('\n'); buffer = lines.pop() || '';
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            try {
              const evt = JSON.parse(line.slice(6));
              if (evt.type === 'progress') {
                this.batchAi.runDone = evt.index;
                this.batchAi.runResults.push({ 'jira号': evt.bugid, '执行结果': evt.status === 'success' ? '成功' : '失败', '触发时间': evt.exec_time || '', '执行时间': evt.analysis_time || '', '备注': evt.msg || '' });
              } else if (evt.type === 'done') { this.batchAi.runDoneMsg = evt.message || '线上执行完成'; }
            } catch (e) { /* ignore */ }
          }
        }
      } catch (e) { if (e.name === 'AbortError') ElMessage.warning('已停止'); else ElMessage.error('线上批量执行失败: ' + e.message); }
      finally { this.running.batchRun = false; }
    },

    setBatchMeta(target, mode) {
      const defaults = mode === 'online'
        ? { analysisConcurrency: 5, downloadConcurrency: 2, model: 'deepseek-v-pro', triggerSource: '线上' }
        : { analysisConcurrency: 10, downloadConcurrency: 4, model: 'deepseek-v-pro', triggerSource: 'PC' };
      Object.assign(this[target], defaults);
      this.loadEnvSettings(mode);
    },
    saveEnvSettings() {
      const mode = this.batchAi.execMode;
      if (!mode) return;
      const data = {
        analysisConcurrency: this.batchAi.analysisConcurrency,
        downloadConcurrency: this.batchAi.downloadConcurrency,
        model: this.batchAi.model,
        triggerSource: this.batchAi.triggerSource,
        softwareVersion: this.batchAi.softwareVersion,
      };
      localStorage.setItem(`envSettings_${mode}`, JSON.stringify(data));
      this.batchAi.envSavedMsg = '已保存';
      setTimeout(() => { this.batchAi.envSavedMsg = ''; }, 2000);
    },
    loadEnvSettings(mode) {
      try {
        const raw = localStorage.getItem(`envSettings_${mode || this.batchAi.execMode}`);
        if (!raw) return;
        const data = JSON.parse(raw);
        if (data.analysisConcurrency) this.batchAi.analysisConcurrency = data.analysisConcurrency;
        if (data.downloadConcurrency) this.batchAi.downloadConcurrency = data.downloadConcurrency;
        if (data.model) this.batchAi.model = data.model;
        if (data.triggerSource) this.batchAi.triggerSource = data.triggerSource;
        if (data.softwareVersion !== undefined) this.batchAi.softwareVersion = data.softwareVersion;
      } catch (e) { /* ignore */ }
    },
    async batchAiOneClick() {
      this.running.batchOneClick = true;
      this.batchAi.oneClickMsg = ''; this.batchAi.oneClickError = false; this.batchAi.continuousRunning = false;
      this.batchAiAbort = new AbortController();
      try {
        if (!this.batchAi.softwareVersion.trim()) throw new Error('请填写软件版本');
        if (!this.batchAi.jql.trim()) throw new Error('请输入 JQL'); await this.batchAiSearch();
        if (!this.batchAi.rows.length) throw new Error('候选列表为空');
        const hasAnyFilter = this.batchAi.filterAllExisting || this.batchAi.filterPcOnly || this.batchAi.filterOnlineOnly || this.batchAi.filterAiPreliminary || this.batchAi.filterExistingSuccess;
        if (hasAnyFilter) { await this.batchAiFilter(false); if (!this.batchAi.filteredKeys.length) throw new Error('已无未执行的内容'); }
        else { this.batchAi.filteredKeys = this.batchAi.rows.map(r => r.key); }
        const runOneRound = async (roundLabel = '') => {
          await this.batchAiSample();
          if (!this.batchAi.selected.length) throw new Error(`${roundLabel}抽样结果为空`);
          if (this.batchAi.execMode === 'online') { await this.batchAiRunOnline(); } else { await this.batchAiRun(); }
        };
        if (!this.batchAi.continuous) {
          await runOneRound();
          const modeLabel = this.batchAi.execMode === 'online' ? '线上' : 'PC';
          this.batchAi.oneClickMsg = `${modeLabel}一键执行完成: ${this.batchAi.runDone}/${this.batchAi.runTotal} 成功`;
        } else {
          this.batchAi.continuousRunning = true;
          const totalRounds = this.batchAi.rounds;
          const intervalMs = this.batchAi.interval * 60 * 1000;
          this.batchAi.currentRound = 1;
          try { await runOneRound('[1/' + totalRounds + '] '); }
          catch (e) {
            if (e.name === 'AbortError') { this.batchAi.oneClickMsg = `持续执行已停止（完成 0/${totalRounds} 轮）`; this.batchAi.oneClickError = false; }
            else { this.batchAi.oneClickMsg = `[1/${totalRounds}] 执行中断: ${e.message}`; this.batchAi.oneClickError = true; }
            this.batchAi.continuousRunning = false; return;
          }
          for (let i = 2; i <= totalRounds; i++) {
            if (this.batchAiAbort && this.batchAiAbort.signal.aborted) { this.batchAi.oneClickMsg = `持续执行已停止（完成 ${i - 2}/${totalRounds} 轮）`; this.batchAi.oneClickError = false; break; }
            this.batchAi.preSample = { ready: false, selected: [], trigger_times: {}, sampleStats: null, error: null };
            this.batchAi.oneClickMsg = `第 ${i - 1} 轮完成，正在预提取第 ${i}/${totalRounds} 轮触发时间...`;
            const preSamplePromise = this.batchAiSample(true).then(result => {
              if (result) { this.batchAi.preSample = { ready: true, selected: result.selected, trigger_times: result.trigger_times, sampleStats: result.sampleStats, error: null }; }
              else { this.batchAi.preSample = { ready: false, selected: [], trigger_times: {}, sampleStats: null, error: '预提取失败' }; }
            });
            const waitUntil = Date.now() + intervalMs;
            let aborted = false;
            while (Date.now() < waitUntil) {
              if (this.batchAiAbort && this.batchAiAbort.signal.aborted) { aborted = true; break; }
              const remainSec = Math.ceil((waitUntil - Date.now()) / 1000);
              const mm = Math.floor(remainSec / 60); const ss = remainSec % 60;
              const preStatus = this.batchAi.preSample.ready ? '✅ 就绪' : (this.batchAi.preSample.error ? '❌ 失败' : '⏳ 提取中');
              this.batchAi.oneClickMsg = `等待间隔（${mm}:${String(ss).padStart(2, '0')}）| 第 ${i} 轮预提取: ${preStatus}`;
              await new Promise(r => setTimeout(r, 1000));
            }
            if (aborted) { this.batchAi.oneClickMsg = `持续执行已停止（完成 ${i - 1}/${totalRounds} 轮）`; this.batchAi.oneClickError = false; break; }
            await preSamplePromise;
            this.batchAi.currentRound = i;
            if (this.batchAi.preSample.error || !this.batchAi.preSample.selected.length) { this.batchAi.oneClickMsg = `[${i}/${totalRounds}] 预提取失败或结果为空，跳过本轮`; this.batchAi.oneClickError = true; break; }
            this.batchAi.selected = this.batchAi.preSample.selected;
            this.batchAi.triggerTimes = this.batchAi.preSample.trigger_times;
            this.batchAi.sampleStats = this.batchAi.preSample.sampleStats;
            this.batchAi.preSample = null;
            try {
              if (this.batchAi.execMode === 'online') { await this.batchAiRunOnline(); } else { await this.batchAiRun(); }
            } catch (e) {
              if (e.name === 'AbortError') { this.batchAi.oneClickMsg = `持续执行已停止（完成 ${i - 1}/${totalRounds} 轮）`; this.batchAi.oneClickError = false; }
              else { this.batchAi.oneClickMsg = `[${i}/${totalRounds}] 执行中断: ${e.message}`; this.batchAi.oneClickError = true; }
              break;
            }
          }
          this.batchAi.continuousRunning = false; this.batchAi.preSample = null;
          if (!this.batchAi.oneClickError && !this.batchAi.oneClickMsg.includes('已停止')) { this.batchAi.oneClickMsg = `持续执行完成：共 ${totalRounds} 轮`; }
        }
      } catch (e) { this.batchAi.oneClickMsg = '一键执行中断: ' + e.message; this.batchAi.oneClickError = true; }
      finally { this.running.batchOneClick = false; }
    },
    parseAiDirectBugids() {
      const ids = this.aiDirect.bugidsRaw.split(/[\s,，;；]+/).map(s => s.trim()).filter(Boolean);
      this.aiDirect.parsed = [...new Set(ids)];
      this.aiDirect.timeRows = []; this.aiDirect.triggerTimes = {}; this.aiDirect.filterInfo = '';
    },
    async applyAiDirectFilter() {
      if (!this.aiDirect.parsed.length) return;
      this.aiDirect.filterLoading = true; this.aiDirect.filterInfo = '';
      try {
        const body = await api('/api/test/filter_success_jiras', { method: 'POST', body: JSON.stringify({ bugids: this.aiDirect.parsed }) });
        const data = body.data || {};
        const pcSet = new Set(data.pc_success || []); const onlineSet = new Set(data.online_success || []);
        const before = this.aiDirect.parsed.length; const exclude = new Set();
        if (this.aiDirect.filterPcSuccess) pcSet.forEach(k => exclude.add(k));
        if (this.aiDirect.filterOnlineSuccess) onlineSet.forEach(k => exclude.add(k));
        this.aiDirect.parsed = this.aiDirect.parsed.filter(k => !exclude.has(k));
        for (const k of exclude) delete this.aiDirect.triggerTimes[k];
        this.aiDirect.filterInfo = `过滤前 ${before} 条，排除 ${exclude.size} 条已成功，剩余 ${this.aiDirect.parsed.length} 条`;
      } catch (e) { ElMessage.error('过滤失败: ' + (e.message || '')); } finally { this.aiDirect.filterLoading = false; }
    },
    async _extractTimesSSE(keys) {
      const resp = await fetch('/api/test/batch_ai_extract_times', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ keys }) });
      const reader = resp.body.getReader(); const decoder = new TextDecoder(); let buffer = '', result = {};
      while (true) {
        const { done, value } = await reader.read(); if (done) break;
        buffer += decoder.decode(value, { stream: true }); const lines = buffer.split('\n'); buffer = lines.pop() || '';
        for (const line of lines) { if (!line.startsWith('data: ')) continue; try { const evt = JSON.parse(line.slice(6)); if (evt.type === 'done') result = evt; } catch (e) { /* ignore */ } }
      }
      return result;
    },
    async runAiDirectExtract() {
      if (!this.aiDirect.parsed.length) { this.parseAiDirectBugids(); }
      if (!this.aiDirect.parsed.length) return ElMessage.warning('请先输入 Jira 号');
      this.running.aiDirectExtract = true;
      try {
        const evt = await this._extractTimesSSE(this.aiDirect.parsed);
        const times = evt.trigger_times || {}; const sources = evt.sources || {};
        this.aiDirect.triggerTimes = times;
        this.aiDirect.timeRows = this.aiDirect.parsed.map(k => ({ 'jira号': k, '触发时间': times[k] || '', '来源': sources[k] || '' }));
        ElMessage.success(`提取完成: ${Object.keys(times).length}/${this.aiDirect.parsed.length} 有触发时间`);
      } catch (e) { ElMessage.error('提取触发时间失败: ' + (e.message || '')); } finally { this.running.aiDirectExtract = false; }
    },
    async runAiDirectAnalyze() {
      if (!this.aiDirect.parsed.length) { this.parseAiDirectBugids(); }
      if (!this.aiDirect.parsed.length) return ElMessage.warning('请先输入 Jira 号');
      if (!Object.keys(this.aiDirect.triggerTimes).length) { await this.runAiDirectExtract(); }
      this.running.aiDirectRun = true; this.aiDirect.runResults = []; this.aiDirect.runTotal = this.aiDirect.parsed.length; this.aiDirect.runDone = 0; this.aiDirect.runDoneMsg = '';
      this.aiDirectAbort = new AbortController();
      try {
        const resp = await fetch('/api/test/batch_ai_run', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ bugids: this.aiDirect.parsed, trigger_times: this.aiDirect.triggerTimes,
            analysis_concurrency: this.aiDirect.analysisConcurrency, download_concurrency: this.aiDirect.downloadConcurrency,
            model: this.aiDirect.model, trigger_source: this.aiDirect.triggerSource }),
          signal: this.aiDirectAbort.signal,
        });
        const reader = resp.body.getReader(); const decoder = new TextDecoder(); let buffer = '';
        while (true) {
          const { done, value } = await reader.read(); if (done) break;
          buffer += decoder.decode(value, { stream: true }); const lines = buffer.split('\n'); buffer = lines.pop() || '';
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            try {
              const evt = JSON.parse(line.slice(6));
              if (evt.type === 'progress') {
                this.aiDirect.runDone = evt.index;
                this.aiDirect.runResults.push({ 'jira号': evt.bugid, '执行结果': evt.status === 'success' ? '成功' : '失败', '备注': evt.msg || '', '触发时间': evt.exec_time || '', '执行时间': evt.analysis_time || '' });
              } else if (evt.type === 'done') {
                let doneMsg = `执行完成: ${evt.success}/${evt.total} 成功`;
                if (evt.csv_path) doneMsg += `，已写入 ${evt.csv_path}`;
                this.aiDirect.runDoneMsg = doneMsg;
              }
            } catch (e) { /* ignore */ }
          }
        }
      } catch (e) { if (e.name === 'AbortError') ElMessage.warning('已停止'); else ElMessage.error('触发分析失败: ' + e.message); }
      finally { this.running.aiDirectRun = false; }
    },
    async runAiDirectOneClick() {
      const now = Date.now();
      if (this.aiDirect._lastClickTime && (now - this.aiDirect._lastClickTime) < 60000) {
        const remain = Math.ceil((60000 - (now - this.aiDirect._lastClickTime)) / 1000);
        return ElMessage.warning(`请勿重复点击，${remain}秒后可再次执行`);
      }
      this.aiDirect._lastClickTime = now;
      if (!this.aiDirect.parsed.length) { this.parseAiDirectBugids(); }
      if (!this.aiDirect.parsed.length) return ElMessage.warning('请先输入 Jira 号');
      if (!this.aiDirect.execMode) return ElMessage.warning('请选择执行模式');
      try { await this.runAiDirectExtract(); } catch (e) { return ElMessage.error('获取触发时间失败: ' + (e.message || '')); }
      this.running.aiDirectRun = true; this.aiDirect.runResults = []; this.aiDirect.runTotal = this.aiDirect.parsed.length; this.aiDirect.runDone = 0; this.aiDirect.runDoneMsg = '';
      this.aiDirectAbort = new AbortController();
      try {
        const isOnline = this.aiDirect.execMode === 'online';
        const url = isOnline ? '/api/test/prod_batch_run' : '/api/test/batch_ai_run';
        const body = { bugids: this.aiDirect.parsed, trigger_times: this.aiDirect.triggerTimes,
          analysis_concurrency: this.aiDirect.analysisConcurrency, download_concurrency: this.aiDirect.downloadConcurrency,
          model: this.aiDirect.model, trigger_source: this.aiDirect.triggerSource };
        if (isOnline) body.skip_existing = false;
        const resp = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: this.aiDirectAbort.signal });
        const reader = resp.body.getReader(); const decoder = new TextDecoder(); let buffer = '';
        while (true) {
          const { done, value } = await reader.read(); if (done) break;
          buffer += decoder.decode(value, { stream: true }); const lines = buffer.split('\n'); buffer = lines.pop() || '';
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            try {
              const evt = JSON.parse(line.slice(6));
              if (evt.type === 'progress') {
                this.aiDirect.runDone = evt.index;
                this.aiDirect.runResults.push({ 'jira号': evt.bugid || evt['Jira号'] || '', '执行结果': evt.status === 'success' ? '成功' : '失败', '备注': evt.msg || '', '触发时间': evt.exec_time || '', '执行时间': evt.analysis_time || '' });
              } else if (evt.type === 'done') {
                this.aiDirect.runDoneMsg = evt.message || `完成: ${this.aiDirect.runDone}/${this.aiDirect.runTotal}`;
                if (evt.interrupted) this.aiDirect.runDoneMsg += '（已中断）';
              }
            } catch (e) { /* ignore */ }
          }
        }
      } catch (e) { if (e.name === 'AbortError') ElMessage.warning('已停止'); else ElMessage.error('执行失败: ' + e.message); }
      finally { this.running.aiDirectRun = false; }
    },
    stopAiDirectAnalyze() { if (this.aiDirectAbort) this.aiDirectAbort.abort(); }
  },
};
</script>

<style scoped>
.batch-tabs { border-radius: 8px; }
.batch-tabs :deep(.el-tabs__content) { padding: 16px; overflow: visible; }
.exec-section { margin-bottom: 14px; padding: 12px 14px; background: #f8f9fb; border-radius: 8px; }
.section-label { font-size: 12px; font-weight: 600; color: #606266; margin-bottom: 8px; letter-spacing: 0.5px; }
.input-row { margin-bottom: 8px; }
.preset-bar { display: flex; gap: 6px; flex-wrap: wrap; }
.filter-bar { margin-top: 10px; padding: 10px 14px; background: #fafbfc; border-radius: 6px; border: 1px solid #ebeef5; }
.filter-row { display: flex; gap: 14px; flex-wrap: wrap; align-items: center; }
.action-bar { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; padding: 10px 14px; background: #f8f9fb; border-radius: 8px; }
.action-left { display: flex; align-items: center; gap: 10px; }
.action-right { display: flex; align-items: center; gap: 8px; }
.field-hint { font-size: 12px; color: #909399; }
.params-grid { display: flex; gap: 16px; flex-wrap: wrap; align-items: center; }
.param-item { display: flex; align-items: center; gap: 6px; }
.param-label { font-size: 12px; color: #606266; }
.required-label::before { content: '*'; color: #f56c6c; margin-right: 2px; }
:deep(.is-error .el-input__wrapper) { box-shadow: 0 0 0 1px #f56c6c inset !important; }
.param-hint { font-size: 11px; color: #909399; }
.continuous-bar { display: flex; align-items: center; gap: 8px; margin-top: 10px; padding: 10px 14px; background: #f8f9fb; border-radius: 8px; flex-wrap: wrap; }
.continuous-row { display: flex; align-items: center; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
.progress-card { margin-top: 10px; padding: 10px; background: #f5f7fa; border-radius: 6px; }
.stats-row { display: flex; gap: 8px; flex-wrap: wrap; }
.selected-tags { margin-top: 6px; display: flex; gap: 4px; flex-wrap: wrap; }
.selected-tags .el-tag { margin: 0; }
.time-hint { margin-left: 3px; font-size: 10px; }
.round-info { margin-top: 8px; }
.execute-bar { display: flex; justify-content: center; align-items: center; gap: 12px; margin-top: 16px; padding-top: 14px; border-top: 1px solid #ebeef5; }
.env-settings { margin-top: 12px; padding: 10px 14px; background: #f8f9fb; border-radius: 8px; }
.env-settings .section-label { margin-bottom: 10px; }
.env-save-bar { display: flex; align-items: center; gap: 8px; margin-top: 10px; padding-top: 8px; border-top: 1px dashed #dcdfe6; }
</style>
