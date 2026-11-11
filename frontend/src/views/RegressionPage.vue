<template>
  <div class="regression-page">
    <div class="section-title">回归测试</div>
    <el-tabs v-model="activeTab" type="border-card" class="regression-tabs">

      <!-- ============ Tab1: 批次测试 ============ -->
      <el-tab-pane label="批次测试" name="batch">
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
            <el-checkbox v-model="filterAiPreliminary" size="small" style="margin-left:12px">过滤AI初步分析结果</el-checkbox>
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
      </el-tab-pane>

      <!-- ============ Tab2: 日期测试 ============ -->
      <el-tab-pane label="日期测试" name="date">
        <!-- 区域 A：筛选栏 -->
        <el-card shadow="never">
          <template #header><span style="font-weight:700">① 选择分析开始时间</span></template>
          <div class="filter-bar">
            <div class="param-item">
              <span class="param-label">分析开始时间起</span>
              <el-date-picker v-model="dateCutoff" type="datetime" value-format="YYYY-MM-DD HH:mm:ss"
                placeholder="选择起始时间" clearable style="width:220px" size="small"></el-date-picker>
            </div>
            <el-button type="primary" size="small" :loading="dateLoading" @click="loadDateFailures">加载</el-button>
            <el-tag v-if="dateBatches.length" type="info" size="small">{{ dateTotalFail }} 条失败 / {{ dateBatches.length }} 个日期</el-tag>
          </div>
          <el-alert v-if="dateMsg" :type="dateError ? 'error' : 'success'" :closable="false" :title="dateMsg" style="margin-top:8px"></el-alert>
        </el-card>

        <!-- 区域 B：按日期展开的失败记录 -->
        <el-card v-if="dateBatches.length" shadow="never">
          <template #header>
            <div style="display:flex;align-items:center;justify-content:space-between">
              <span style="font-weight:700">② 失败记录</span>
              <div>
                <el-button size="small" @click="dateSelectAll">全选</el-button>
                <el-button size="small" @click="dateInvertSelection">反选</el-button>
              </div>
            </div>
          </template>
          <el-collapse v-model="dateCollapseActive" class="date-collapse">
            <el-collapse-item v-for="d in dateBatches" :key="d.date" :name="d.date">
              <template #title>
                <span style="font-weight:600">{{ d.date }}</span>
                <el-tag size="small" type="danger" style="margin-left:8px">{{ d.total }} 条</el-tag>
              </template>
              <!-- 时间添加为 组 -->
              <div v-if="d.with_time_add.length" class="date-group">
                <div class="group-label">时间添加为（{{ d.with_time_add.length }}）</div>
                <div v-for="item in d.with_time_add" :key="item.jira" class="record-item">
                  <el-checkbox :model-value="dateCheckedSet.has(item.jira)"
                    @change="(val: boolean) => dateToggleItem(item.jira, val)" />
                  <span class="record-jira">{{ item.jira }}</span>
                  <el-tag size="small" :type="dateFilteredSet.has(item.jira) ? 'info' : 'warning'" class="record-reason">
                    {{ item.reason || '-' }}
                  </el-tag>
                  <el-tag v-if="dateFilteredSet.has(item.jira)" size="small" type="info" style="margin-left:4px">已过滤</el-tag>
                </div>
              </div>
              <!-- 其他 组 -->
              <div v-if="d.other.length" class="date-group">
                <div class="group-label">其他（{{ d.other.length }}）</div>
                <div v-for="item in d.other" :key="item.jira" class="record-item">
                  <el-checkbox :model-value="dateCheckedSet.has(item.jira)"
                    @change="(val: boolean) => dateToggleItem(item.jira, val)" />
                  <span class="record-jira">{{ item.jira }}</span>
                  <el-tag size="small" :type="dateFilteredSet.has(item.jira) ? 'info' : ''" class="record-reason">
                    {{ item.reason || '-' }}
                  </el-tag>
                  <el-tag v-if="dateFilteredSet.has(item.jira)" size="small" type="info" style="margin-left:4px">已过滤</el-tag>
                </div>
              </div>
            </el-collapse-item>
          </el-collapse>
        </el-card>

        <!-- 区域 C：过滤与汇总 -->
        <el-card v-if="dateAllJiras.length" shadow="never">
          <template #header>
            <div style="display:flex;align-items:center;justify-content:space-between">
              <span style="font-weight:700">③ 过滤与抽样</span>
              <el-tag type="success">已选 {{ dateCheckedSet.size }} 条 / 有效 {{ dateEffectiveJiras.length }} 条</el-tag>
            </div>
          </template>
          <div class="sample-bar">
            <el-checkbox v-model="dateFilterAi" size="small" @change="onDateFilterAiChange">过滤AI初步分析结果</el-checkbox>
            <span v-if="dateFilterLoading" style="color:#909399;font-size:12px">查询中...</span>
            <span v-if="dateFilterDone" style="color:#67c23a;font-size:12px">已排除 {{ dateFilteredSet.size }} 条</span>
          </div>
          <div class="sample-bar" style="margin-top:8px">
            <span class="param-label">抽取个数</span>
            <el-input-number v-model="dateSampleCount" :min="0" :max="2000" :step="1" style="width:130px" controls-position="right" size="small"></el-input-number>
            <span style="font-size:12px;color:#909399">0 = 全部</span>
          </div>
          <div style="margin-top:10px;max-height:180px;overflow-y:auto">
            <el-tag v-for="j in dateEffectiveJiras" :key="j" closable size="small" style="margin:2px" @close="dateRemoveJira(j)">{{ j }}</el-tag>
          </div>
        </el-card>

        <!-- 区域 D：执行栏 -->
        <el-card v-if="dateEffectiveJiras.length" shadow="never">
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
            <el-button v-if="!executing" type="primary" @click="startDateRegression">开始回归执行</el-button>
            <el-button v-if="executing" type="danger" @click="stopRegression">停止执行</el-button>
          </div>
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
      </el-tab-pane>

      <!-- ============ Tab3: 表单查找 ============ -->
      <el-tab-pane label="表单查找" name="form_lookup">
        <!-- Step 1: 表单查询 -->
        <el-card shadow="never">
          <template #header><span style="font-weight:700">① 表单查询</span></template>
          <div class="filter-bar">
            <div class="param-item">
              <span class="param-label">创建日期</span>
              <el-date-picker v-model="form.date" type="date" value-format="YYYY-MM-DD"
                placeholder="选择日期" style="width:160px" size="small"></el-date-picker>
            </div>
            <el-button size="small" @click="form.date = todayStr()">今日</el-button>
            <el-button size="small" @click="form.date = yesterdayStr()">昨日</el-button>
            <el-button type="primary" size="small" :loading="form.loading" @click="formQuery">查询</el-button>
            <el-checkbox v-model="form.filterProblemTime" size="small">查询问题发生时间</el-checkbox>
            <el-tag v-if="form.rows.length" type="info" size="small">{{ form.rows.length }} 条</el-tag>
          </div>
          <div v-if="form.queried" class="form-stats">
            <el-tag size="small">总数 {{ form.rows.length }}</el-tag>
            <el-tag size="small" type="success">有缓存 {{ formStats.cached }}</el-tag>
            <el-tag size="small" type="warning">待提取 {{ formStats.pending }}</el-tag>
            <el-tag size="small" type="info">有AI分析 {{ formStats.aiCount }}</el-tag>
            <el-tag v-if="form.filterProblemTime" size="small" type="danger">有问题时间 {{ formStats.problemTimeCount }}</el-tag>
          </div>
          <el-table v-if="form.rows.length" :data="form.rows" size="small" style="margin-top:10px" max-height="360"
            :row-class-name="formRowClass">
            <el-table-column prop="jira号" label="Jira号" width="150"></el-table-column>
            <el-table-column prop="创建日期" label="创建日期" width="160"></el-table-column>
            <el-table-column v-if="form.filterProblemTime" prop="问题发生时间" label="问题发生时间" width="180">
              <template #default="{ row }">
                <span :style="{ color: row['问题发生时间'] ? '#67c23a' : '#c0c4cc' }">
                  {{ row['问题发生时间'] || '—' }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="问题发生时间" min-width="180">
              <template #default="{ row }">
                <el-tag v-if="row.has_cached_time" size="small" type="success">{{ row.cached_time }}</el-tag>
                <el-tag v-else size="small" type="warning">待提取</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="AI初步分析结果" label="AI分析" width="120">
              <template #default="{ row }">
                <el-tag :type="row.AI初步分析结果 && row.AI初步分析结果 !== '-' ? 'success' : 'info'" size="small">
                  {{ row.AI初步分析结果 ? '有' : '无' }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <!-- Step 2: 提取问题发生时间 -->
        <el-card v-if="form.rows.length" shadow="never">
          <template #header><span style="font-weight:700">② 提取问题发生时间</span></template>
          <div class="exec-bar">
            <el-tag type="warning" size="small">待提取 {{ formStats.pending }} 条</el-tag>
            <el-button v-if="!form.extracting" type="primary" size="small" :disabled="formStats.pending === 0"
              @click="formExtract">提取问题发生时间</el-button>
            <el-button v-if="form.extracting" type="warning" size="small" @click="formStop">停止提取</el-button>
          </div>
          <div v-if="form.extractProgress > 0" style="margin-top:8px">
            <el-progress :percentage="form.extractProgress" :stroke-width="10"></el-progress>
          </div>
        </el-card>

        <!-- Step 3: 抽样与执行 -->
        <el-card v-if="form.withTimeBugids.length" shadow="never">
          <template #header><span style="font-weight:700">③ 抽样与执行</span></template>
          <div class="exec-bar">
            <span class="param-label">抽取个数</span>
            <el-input-number v-model="form.sampleCount" :min="0" :max="2000" :step="1"
              style="width:130px" controls-position="right" size="small"></el-input-number>
            <span style="font-size:12px;color:#909399">0 = 全部（{{ form.withTimeBugids.length }} 条有时间）</span>
            <el-button v-if="!form.executing" type="primary" size="small" @click="formRun">开始执行</el-button>
            <el-button v-if="form.executing" type="danger" size="small" @click="formStop">停止执行</el-button>
          </div>
          <div v-if="form.execProgress > 0 || form.execLogs.length" class="exec-progress">
            <div v-if="form.execSummary" class="exec-summary">
              <el-tag :type="form.execSummary.type">{{ form.execSummary.text }}</el-tag>
              <span v-if="form.execSummary.detail" style="margin-left:8px;color:#606266;font-size:12px">{{ form.execSummary.detail }}</span>
            </div>
            <el-progress v-if="form.execProgress > 0" :percentage="form.execProgress" :stroke-width="10" style="margin-top:6px"></el-progress>
            <div class="exec-log" v-if="form.execLogs.length">
              <div v-for="(log, idx) in form.execLogs.slice(-30)" :key="idx" :style="logStyle(log)">{{ log }}</div>
            </div>
          </div>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="数据更新" name="data_cleanup">
        <DataCleanupPanel />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script lang="ts">
// @ts-nocheck
import { ElMessage } from 'element-plus';
import { api } from '../composables/utils';
import DataCleanupPanel from '../panels/DataCleanupPanel.vue';

export default {
  name: 'RegressionPage',
  components: { DataCleanupPanel },
  data() {
    return {
      activeTab: 'batch',
      // ===== Tab1: 批次测试 =====
      afterTime: '',
      loadingBatches: false,
      batches: [] as any[],
      batchMsg: '',
      batchError: false,
      checkedSet: new Set<string>(),
      expandedSet: new Set<string>(),
      sampleCount: 0,
      filterAiPreliminary: false,
      execMode: 'pc',
      intervalMin: 0,
      totalRounds: 1,
      executing: false,
      execLogs: [] as string[],
      execSummary: null as any,
      execProgress: 0,
      // ===== Tab2: 日期测试 =====
      dateCutoff: '',
      dateLoading: false,
      dateBatches: [] as any[],
      dateTotalFail: 0,
      dateMsg: '',
      dateError: false,
      dateCollapseActive: [] as string[],
      dateCheckedSet: new Set<string>(),
      dateFilterAi: false,
      dateFilterLoading: false,
      dateFilterDone: false,
      dateFilteredSet: new Set<string>(),
      dateSampleCount: 0,
      // ===== Tab3: 表单查找 =====
      form: {
        date: '',
        loading: false,
        filterProblemTime: false,
        rows: [] as any[],
        queried: false,
        extracting: false,
        extractProgress: 0,
        executing: false,
        execLogs: [] as string[],
        execSummary: null as any,
        execProgress: 0,
        sampleCount: 0,
        withTimeBugids: [] as string[],
        triggerTimes: {} as Record<string, string>,
      },
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
    // Tab2: 所有失败记录的 jira 列表
    dateAllJiras(): string[] {
      const s = new Set<string>();
      for (const d of this.dateBatches) {
        for (const item of d.with_time_add) s.add(item.jira);
        for (const item of d.other) s.add(item.jira);
      }
      return [...s].sort();
    },
    // Tab2: 已选且未被AI过滤的 jira 列表
    dateEffectiveJiras(): string[] {
      return [...this.dateCheckedSet]
        .filter(j => !this.dateFilteredSet.has(j))
        .sort();
    },
    // Tab3: 表单查找统计
    formStats(): { cached: number; pending: number; aiCount: number; problemTimeCount: number } {
      const rows = this.form.rows;
      return {
        cached: rows.filter((r: any) => r.has_cached_time).length,
        pending: rows.filter((r: any) => !r.has_cached_time).length,
        aiCount: rows.filter((r: any) => r.AI初步分析结果 && r.AI初步分析结果 !== '-').length,
        problemTimeCount: rows.filter((r: any) => r['问题发生时间'] && r['问题发生时间'].trim()).length,
      };
    },
  },
  methods: {
    // ===== Tab1 方法 =====
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
      this.checkedSet = new Set(this.checkedSet);
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
      for (const b of this.batches) {
        if (this.checkedSet.has(b.batch_id) && b.failed_jiras.includes(jira)) {
          this.checkedSet.delete(b.batch_id);
        }
      }
      this.checkedSet = new Set(this.checkedSet);
    },

    // ===== Tab2 方法 =====
    async loadDateFailures() {
      if (!this.dateCutoff) return ElMessage.warning('请选择分析开始时间起点');
      this.dateLoading = true;
      this.dateMsg = '正在加载...'; this.dateError = false;
      this.dateBatches = []; this.dateCheckedSet.clear(); this.dateCollapseActive = [];
      this.dateFilteredSet.clear(); this.dateFilterDone = false; this.dateFilterAi = false;
      try {
        const body = await api('/api/test/regression_date_load', {
          method: 'POST', body: JSON.stringify({ after_time: this.dateCutoff }),
        });
        const data = body.data || {};
        this.dateBatches = data.dates || [];
        this.dateTotalFail = data.total_fail || 0;
        // 默认展开所有日期
        this.dateCollapseActive = this.dateBatches.map((d: any) => d.date);
        this.dateMsg = body.message || `共 ${this.dateTotalFail} 条失败记录`;
        ElMessage.success(this.dateMsg);
      } catch (e: any) {
        this.dateMsg = e.message || '加载失败';
        this.dateError = true;
      } finally { this.dateLoading = false; }
    },
    dateToggleItem(jira: string, checked: boolean) {
      if (checked) this.dateCheckedSet.add(jira);
      else this.dateCheckedSet.delete(jira);
      this.dateCheckedSet = new Set(this.dateCheckedSet);
    },
    dateSelectAll() {
      for (const j of this.dateAllJiras) this.dateCheckedSet.add(j);
      this.dateCheckedSet = new Set(this.dateCheckedSet);
    },
    dateInvertSelection() {
      const next = new Set<string>();
      for (const j of this.dateAllJiras) {
        if (!this.dateCheckedSet.has(j)) next.add(j);
      }
      this.dateCheckedSet = next;
    },
    dateRemoveJira(jira: string) {
      this.dateCheckedSet.delete(jira);
      this.dateCheckedSet = new Set(this.dateCheckedSet);
    },
    async onDateFilterAiChange(val: boolean) {
      if (!val) {
        this.dateFilteredSet.clear();
        this.dateFilterDone = false;
        return;
      }
      const selected = [...this.dateCheckedSet];
      if (!selected.length) return ElMessage.warning('请先选择记录');
      this.dateFilterLoading = true;
      try {
        const body = await api('/api/test/regression_filter_ai', {
          method: 'POST', body: JSON.stringify({ bugids: selected }),
        });
        const data = body.data || {};
        this.dateFilteredSet = new Set(data.has_ai || []);
        this.dateFilterDone = true;
        ElMessage.success(body.message || `已排除 ${this.dateFilteredSet.size} 条`);
      } catch (e: any) {
        ElMessage.error('查询AI初步分析结果失败: ' + (e.message || ''));
        this.dateFilterAi = false;
      } finally { this.dateFilterLoading = false; }
    },

    // ===== Tab3 方法 =====
    todayStr(): string {
      const d = new Date();
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    },
    yesterdayStr(): string {
      const d = new Date();
      d.setDate(d.getDate() - 1);
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    },
    async formQuery() {
      if (!this.form.date) return ElMessage.warning('请选择日期');
      this.form.loading = true;
      this.form.rows = [];
      this.form.queried = false;
      this.form.withTimeBugids = [];
      this.form.triggerTimes = {};
      this.form.execLogs = [];
      this.form.execSummary = null;
      this.form.execProgress = 0;
      this.form.extractProgress = 0;
      try {
        const body = await api('/api/test/regression_form_query', {
          method: 'POST', body: JSON.stringify({ date: this.form.date, filter_problem_time: this.form.filterProblemTime }),
        });
        const data = body.data || {};
        this.form.rows = data.rows || [];
        this.form.queried = true;
        // 构建 withTimeBugids + triggerTimes
        this.form.withTimeBugids = this.form.rows.filter((r: any) => r.has_cached_time).map((r: any) => r['jira号']);
        const tt: Record<string, string> = {};
        for (const r of this.form.rows) {
          if (r.has_cached_time && r.cached_time) tt[r['jira号']] = r.cached_time;
        }
        this.form.triggerTimes = tt;
        ElMessage.success(body.message || `查询到 ${this.form.rows.length} 条`);
      } catch (e: any) {
        ElMessage.error('查询失败: ' + (e.message || ''));
      } finally { this.form.loading = false; }
    },
    async formExtract() {
      const pendingBugids = this.form.rows.filter((r: any) => !r.has_cached_time).map((r: any) => r['jira号']);
      if (!pendingBugids.length) return ElMessage.info('无需提取，全部已有缓存');
      this.form.extracting = true;
      this.form.extractProgress = 0;
      try {
        const resp = await fetch('/api/test/regression_form_extract', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ bugids: pendingBugids }),
        });
        const reader = resp.body!.getReader();
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
              if (evt.type === 'extracted') {
                this.form.extractProgress = Math.round(evt.done / evt.total * 100);
                // 更新行数据
                const row = this.form.rows.find((r: any) => r['jira号'] === evt.bugid);
                if (row && evt.trigger_time) {
                  row.has_cached_time = true;
                  row.cached_time = evt.trigger_time;
                  // 更新 triggerTimes 和 withTimeBugids
                  this.form.triggerTimes[evt.bugid] = evt.trigger_time;
                  if (!this.form.withTimeBugids.includes(evt.bugid)) {
                    this.form.withTimeBugids.push(evt.bugid);
                  }
                }
                this.formLog(`${evt.trigger_time ? '✓' : '✗'} ${evt.bugid}: ${evt.trigger_time || evt.error || '未提取到'} (${evt.source || ''})`);
              } else if (evt.type === 'done') {
                this.form.extractProgress = 100;
                ElMessage.success(`提取完成: ${evt.hit}/${evt.total} 命中`);
              }
            } catch { /* ignore */ }
          }
        }
      } catch (e: any) {
        ElMessage.error('提取失败: ' + (e.message || ''));
      } finally { this.form.extracting = false; }
    },
    async formRun() {
      const bugids = this.form.withTimeBugids;
      if (!bugids.length) return ElMessage.warning('无有问题发生时间的记录');
      this.form.executing = true;
      this.form.execLogs = [];
      this.form.execSummary = null;
      this.form.execProgress = 0;
      try {
        const resp = await fetch('/api/test/regression_form_run', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            bugids,
            trigger_times: this.form.triggerTimes,
            sample_count: this.form.sampleCount || 0,
          }),
        });
        const reader = resp.body!.getReader();
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
                const status = evt.status === '成功' ? '✓' : '✗';
                this.formLog(`${status} ${evt.bugid} (${evt.index}/${evt.total})`);
                this.form.execProgress = Math.round(evt.index / evt.total * 100);
              } else if (evt.type === 'stopped') {
                this.form.execSummary = { type: 'warning', text: '已停止', detail: `成功 ${evt.success} / 失败 ${evt.fail}` };
                this.formLog(`[已停止] ${evt.message}`);
              } else if (evt.type === 'done') {
                this.form.execSummary = {
                  type: evt.success > 0 ? 'success' : 'info',
                  text: `完成: ${evt.success}/${evt.total} 成功`,
                  detail: evt.cloud_url ? `云端: ${evt.cloud_url}` : '',
                };
                this.form.execProgress = 100;
                this.formLog(`[完成] ${evt.success}/${evt.total} 成功`);
                if (evt.cloud_url) this.formLog(`[云端] ${evt.cloud_url}`);
                ElMessage.success(`执行完成: ${evt.success}/${evt.total} 成功`);
              }
            } catch { /* ignore */ }
          }
        }
      } catch (e: any) {
        ElMessage.error('执行失败: ' + (e.message || ''));
      } finally { this.form.executing = false; }
    },
    async formStop() {
      try {
        await api('/api/test/form_exec/stop', { method: 'POST', body: '{}' });
        ElMessage.warning('已发送停止信号');
      } catch (e: any) {
        ElMessage.error('停止失败: ' + (e.message || ''));
      }
    },
    formLog(msg: string) {
      const now = new Date();
      const hh = String(now.getHours()).padStart(2, '0');
      const mm = String(now.getMinutes()).padStart(2, '0');
      const ss = String(now.getSeconds()).padStart(2, '0');
      this.form.execLogs.push(`[${hh}:${mm}:${ss}] ${msg}`);
    },
    formRowClass({ row }: any): string {
      if (row.has_cached_time) return 'form-row-cached';
      return '';
    },

    // ===== 共用执行方法 =====
    async startRegression() {
      if (!this.selectedJiras.length) return ElMessage.warning('请先选择批次');
      await this._doRegression(this.selectedJiras, this.sampleCount, this.filterAiPreliminary);
    },
    async startDateRegression() {
      if (!this.dateEffectiveJiras.length) return ElMessage.warning('请先选择记录');
      await this._doRegression(this.dateEffectiveJiras, this.dateSampleCount, false);
    },
    async _doRegression(bugids: string[], sampleCount: number, filterAi: boolean) {
      this.executing = true;
      this.execLogs = [];
      this.execSummary = null;
      this.execProgress = 0;
      try {
        const resp = await fetch('/api/test/regression_run', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            bugids,
            sample_count: sampleCount || 0,
            filter_ai_preliminary: filterAi,
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
          this.logLine('[已中止]');
        } else {
          ElMessage.error('回归执行失败: ' + (e.message || ''));
        }
      } finally {
        this.executing = false;
      }
    },
    logLine(msg: string) {
      const now = new Date();
      const hh = String(now.getHours()).padStart(2, '0');
      const mm = String(now.getMinutes()).padStart(2, '0');
      const ss = String(now.getSeconds()).padStart(2, '0');
      this.execLogs.push(`[${hh}:${mm}:${ss}] ${msg}`);
    },
    handleSSEEvent(evt: any, counters: any) {
      switch (evt.type) {
        case 'search':
          this.logLine(`[候选] 共 ${evt.total} 个 Jira 号`);
          counters.setTotal(evt.total);
          break;
        case 'filtered':
          this.logLine(`[过滤] 排除 ${evt.excluded} 条，剩余 ${evt.remaining} 条`);
          ElMessage.info(evt.message || `已过滤 ${evt.excluded} 条`);
          break;
        case 'sample':
          this.logLine(`[第${evt.round}轮] 抽样 ${evt.total} 个，剩余 ${evt.remaining ?? '-'} 个未抽`);
          break;
        case 'exhausted':
          this.logLine(`[结束] ${evt.message}`);
          ElMessage.info(evt.message);
          break;
        case 'round':
          this.logLine(`--- 第 ${evt.round}/${evt.total_rounds} 轮 ---`);
          break;
        case 'progress': {
          const status = evt.status === '成功' ? '✓' : '✗';
          this.logLine(`${status} ${evt.bugid} (${evt.index}/${evt.total})`);
          counters.setDone(evt.index);
          if (counters.totalCount() > 0) {
            this.execProgress = Math.round(evt.index / counters.totalCount() * 100);
          }
          break;
        }
        case 'waiting':
          this.logLine(`[等待] ${evt.interval_min} 分钟后进入下一轮...`);
          break;
        case 'stopped':
          this.execSummary = { type: 'warning', text: '已停止', detail: `成功 ${evt.success} / 失败 ${evt.fail}，第 ${evt.round} 轮` };
          this.logLine(`[已停止] ${evt.message}`);
          break;
        case 'done':
          this.execSummary = {
            type: evt.success > 0 ? 'success' : 'info',
            text: `完成: ${evt.success}/${evt.total} 成功`,
            detail: evt.cloud_url ? `云端: ${evt.cloud_url}` : '',
          };
          this.execProgress = 100;
          this.logLine(`[完成] ${evt.success}/${evt.total} 成功，${evt.rounds} 轮`);
          if (evt.cloud_url) this.logLine(`[云端] ${evt.cloud_url}`);
          break;
        case 'error':
          this.execSummary = { type: 'danger', text: '执行错误', detail: evt.message };
          this.logLine(`[错误] ${evt.message}`);
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
.regression-tabs { background: transparent; border: none; }
.regression-tabs :deep(.el-tabs__content) { padding: 0; }
.regression-tabs :deep(.el-tabs__header) { margin-bottom: 4px; }
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

/* 日期测试 */
.date-collapse { border: none; }
.date-collapse :deep(.el-collapse-item__header) { font-size: 13px; background: #fafafa; padding: 0 12px; }
.date-collapse :deep(.el-collapse-item__wrap) { border-bottom: 1px solid #ebeef5; }
.date-group { margin-bottom: 10px; }
.group-label { font-size: 12px; font-weight: 600; color: #606266; margin-bottom: 4px; padding-left: 4px; border-left: 3px solid #409eff; }
.record-item { display: flex; align-items: center; gap: 8px; padding: 5px 4px; border-bottom: 1px solid #f0f0f0; }
.record-item:last-child { border-bottom: none; }
.record-item:hover { background: #f5f7fa; }
.record-jira { font-size: 13px; font-weight: 500; color: #303133; min-width: 100px; }
.record-reason { max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* 执行进度 */
.exec-progress { margin-top: 12px; }
.exec-summary { display: flex; align-items: center; }
.exec-log { margin-top: 8px; max-height: 240px; overflow-y: auto; padding: 8px; background: #f5f7fa; border-radius: 6px; font-size: 12px; font-family: "Consolas", "Microsoft YaHei", monospace; line-height: 1.8; }

/* 表单查找 */
.form-stats { display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
.form-row-cached { background-color: #f0f9eb !important; }
</style>
