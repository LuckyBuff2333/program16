<template>
  <div class="test-panel">
    <div class="section-title">ADP 测试</div>
    <el-alert type="info" :closable="false"
      title="调用 ADP v2 进行日志分析：dpportal 查附件 → ADP SSE 分析 → 提取结果 → 写入飞书多维表格。"></el-alert>

    <el-tabs v-model="activeTab" type="border-card" class="adp-tabs" style="margin-top:12px">
      <!-- ====== Tab 1: 批量执行 ====== -->
      <el-tab-pane label="批量执行" name="batch">
        <!-- 上传 + 配置 -->
        <el-card shadow="never">
          <div style="display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap">
            <div style="flex:1;min-width:260px">
              <div style="margin-bottom:8px;font-size:13px;color:#606266">
                上传 Excel/CSV（自动识别列：Jira号、问题触发时间点、问题描述）
              </div>
              <el-upload ref="uploadRef" :auto-upload="false" :show-file-list="false"
                accept=".xlsx,.xls,.csv" :on-change="onFileChange">
                <el-button type="primary" plain>选择文件</el-button>
              </el-upload>
              <div v-if="batch.fileName" style="margin-top:6px;font-size:12px;color:#909399">
                {{ batch.fileName }} — 解析到 {{ batch.items.length }} 条，
                已识别列: {{ batch.colMap.summary }}
              </div>
            </div>
            <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap">
              <span style="font-size:13px;color:#606266">每批</span>
              <el-input-number v-model="batch.batchSize" :min="1" :max="10" size="small" style="width:90px"></el-input-number>
              <el-checkbox v-model="batch.continuous" size="small">连续执行</el-checkbox>
              <el-button type="success" size="small" :loading="batch.enriching"
                :disabled="!batch.items.length" @click="enrichItems">
                补全缺失字段
              </el-button>
            </div>
          </div>
        </el-card>

        <!-- 预览表格 -->
        <el-table v-if="batch.items.length" :data="batch.items" size="small" stripe border
          max-height="320" style="margin-top:12px">
          <el-table-column type="index" width="45" label="#"></el-table-column>
          <el-table-column prop="bugid" label="Jira号" width="140">
            <template #default="{ row }">
              <span style="font-weight:600;color:#409eff">{{ row.bugid }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="trigger_time" label="问题发生时间锚点" width="170">
            <template #default="{ row }">
              <span :style="{ color: row.trigger_time ? '#67c23a' : '#f56c6c' }">
                {{ row.trigger_time || '缺失' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="description" label="问题描述" min-width="280" show-overflow-tooltip>
            <template #default="{ row }">
              <span :style="{ color: row.description ? '#606266' : '#f56c6c' }">
                {{ row.description || '缺失' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="来源" width="80" align="center">
            <template #default="{ row }">
              <el-tag v-if="row._source === 'excel'" type="success" size="small">Excel</el-tag>
              <el-tag v-else-if="row._source === 'api'" type="warning" size="small">API</el-tag>
              <el-tag v-else type="info" size="small">-</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="80" align="center">
            <template #default="{ row }">
              <el-tag v-if="row._status === 'done'" type="success" size="small">成功</el-tag>
              <el-tag v-else-if="row._status === 'fail'" type="danger" size="small">失败</el-tag>
              <el-tag v-else-if="row._status === 'running'" type="warning" size="small">执行中</el-tag>
              <el-tag v-else type="info" size="small">待执行</el-tag>
            </template>
          </el-table-column>
        </el-table>

        <!-- 执行按钮 + 进度 -->
        <div v-if="batch.items.length" style="margin-top:14px;display:flex;gap:12px;align-items:center">
          <el-button type="primary" :loading="batch.running" @click="runBatch">
            {{ batch.continuous ? '连续执行全部' : '执行一批' }}
          </el-button>
          <el-button @click="batch.items = []; batch.fileName = ''; batch.results = []">清空</el-button>
          <span v-if="batch.progress" style="font-size:13px;color:#606266">
            批次 {{ batch.progress.current }}/{{ batch.progress.total }}
            | 成功 {{ batch.progress.success }} | 失败 {{ batch.progress.fail }}
          </span>
        </div>
        <el-progress v-if="batch.progress && batch.progress.total"
          :percentage="Math.round((batch.progress.current / batch.progress.total) * 100)"
          :status="batch.running ? '' : (batch.progress.fail === 0 ? 'success' : 'warning')"
          style="margin-top:8px"></el-progress>
        <div v-if="batch.running && batch.runningItems && batch.runningItems.length" class="running-strip" style="margin-top:8px">
          <span style="font-size:12px;color:#606266;margin-right:8px">正在分析：</span>
          <el-tag v-for="key in batch.runningItems" :key="key" type="warning" effect="plain" size="small" class="running-tag">
            <span class="running-dot"></span>{{ key }}
          </el-tag>
        </div>

        <!-- 批量结果 -->
        <el-table v-if="batch.results.length" :data="batch.results" size="small" stripe border
          max-height="300" style="margin-top:14px" row-key="jira_key">
          <el-table-column type="expand">
            <template #default="{ row }">
              <div v-if="row.text_preview || row.report_path" style="padding:12px 20px">
                <div style="font-size:12px;color:#606266;margin-bottom:6px">
                  分析文本预览<span v-if="row.text_len">（共 {{ row.text_len }} 字符）</span>
                  <a v-if="row.report_path" :href="reportHref(row)" target="_blank"
                     style="color:#409eff;margin-left:8px">查看完整报告</a>
                </div>
                <pre style="max-height:300px;overflow:auto;background:#f5f7fa;padding:10px;border-radius:4px;font-size:12px;white-space:pre-wrap;word-break:break-all">{{ row.text_preview }}</pre>
              </div>
              <div v-else style="padding:12px 20px;color:#909399;font-size:12px">无分析文本</div>
            </template>
          </el-table-column>
          <el-table-column prop="jira_key" label="Jira号" width="130">
            <template #default="{ row }">
              <span style="font-weight:600;color:#409eff">{{ row.jira_key }}</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="60" align="center">
            <template #default="{ row }">
              <el-tag :type="row.ok ? 'success' : 'danger'" size="small">{{ row.ok ? '成功' : '失败' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="失败类型" width="160" show-overflow-tooltip>
            <template #default="{ row }">
              <span v-if="row.fail_type" :style="{ color: row.fail_type.includes('超时') ? '#e6a23c' : '#f56c6c' }">{{ row.fail_type }}</span>
              <span v-else style="color:#c0c4cc">-</span>
            </template>
          </el-table-column>
          <el-table-column label="问题模块" width="120" show-overflow-tooltip>
            <template #default="{ row }">{{ row.results?.['agent分析的问题模块'] || '-' }}</template>
          </el-table-column>
          <el-table-column label="Root Cause" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">{{ row.results?.['agent分析的root cause'] || row.error || '-' }}</template>
          </el-table-column>
          <el-table-column label="报告链接" width="160">
            <template #default="{ row }">
              <a v-if="row.results?.['_report_url']" :href="row.results['_report_url']" target="_blank" style="color:#409eff;font-size:12px">
                {{ row.results['_html_file'] || '查看报告' }}
              </a>
              <span v-else style="color:#909399">-</span>
            </template>
          </el-table-column>
          <el-table-column label="置信度" width="60">
            <template #default="{ row }">{{ row.results?.['置信度'] || '-' }}</template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ====== Tab 2: 单个执行 ====== -->
      <el-tab-pane label="单个执行" name="single">
        <el-card shadow="never">
          <div style="display:flex;gap:10px;align-items:center">
            <el-input v-model="single.bugid" placeholder="输入 Jira 号，如 VCU-12345"
              style="max-width:280px" @keydown.enter="runSingle" clearable></el-input>
            <el-button type="primary" :loading="single.running" @click="runSingle">执行</el-button>
            <el-button @click="resetSingle">重置</el-button>
          </div>
          <!-- 进度步骤 -->
          <div v-if="single.steps.length" style="margin-top:14px">
            <el-steps :active="singleStepIndex" finish-status="success" align-center>
              <el-step v-for="s in single.steps" :key="s.name" :title="s.label" :status="stepStatus(s)"></el-step>
            </el-steps>
          </div>
          <!-- Jira 信息 -->
          <div v-if="single.jiraInfo" style="margin-top:12px">
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="Jira 号"><span style="font-weight:600;color:#409eff">{{ single.bugid }}</span></el-descriptions-item>
              <el-descriptions-item label="触发时间">{{ single.jiraInfo.trigger_time || '-' }}</el-descriptions-item>
              <el-descriptions-item label="描述" :span="2">{{ single.jiraInfo.description || '-' }}</el-descriptions-item>
            </el-descriptions>
          </div>
          <!-- 分析结果 -->
          <div v-if="single.result" style="margin-top:12px">
            <el-descriptions :column="2" border size="small" title="ADP 分析结果">
              <el-descriptions-item label="完成状态">
                <el-tag :type="single.result['完成状态'] === '完成' ? 'success' : 'warning'" size="small">
                  {{ single.result['完成状态'] || '-' }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item v-if="single.failType" label="失败类型">
                <span style="color:#f56c6c;font-weight:600">{{ single.failType }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="耗时">
                <span v-if="single.running && single.elapsed && !single.result" style="color:#e6a23c">
                  分析中... {{ single.elapsed }}s
                </span>
                <span v-else>{{ single.elapsed ? single.elapsed + 's' : '-' }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="置信度">{{ single.result['置信度'] || '-' }}</el-descriptions-item>
              <el-descriptions-item label="问题模块">{{ single.result['agent分析的问题模块'] || '-' }}</el-descriptions-item>
              <el-descriptions-item label="Root Cause" :span="2">
                <span style="white-space:pre-wrap">{{ single.result['agent分析的root cause'] || '-' }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="报告链接" :span="2">
                <div v-if="single.result && single.result['_report_url']">
                  <a :href="single.result['_report_url']" target="_blank" style="color:#409eff;word-break:break-all">
                    {{ single.result['_html_file'] || '查看报告' }}
                  </a>
                  <div style="font-size:11px;color:#909399;word-break:break-all;margin-top:2px">{{ single.result['_report_url'] }}</div>
                </div>
                <span v-else style="white-space:pre-wrap;word-break:break-all;font-size:12px">{{ single.result ? (single.result['报告链接（分析报告、可观测报告）'] || '-') : '-' }}</span>
              </el-descriptions-item>
            </el-descriptions>
            <div style="margin-top:8px">
              <el-tag :type="single.feishuOk ? 'success' : 'danger'" size="small">
                飞书写入: {{ single.feishuOk ? '成功' : '失败' }}
              </el-tag>
              <el-tag type="info" size="small" style="margin-left:8px">附件: {{ single.attachmentCount }} 个</el-tag>
            </div>
            <!-- 报告文件链接 -->
            <div v-if="single.fileUrls && single.fileUrls.length" style="margin-top:8px">
              <div style="font-size:12px;color:#606266;margin-bottom:4px">报告文件：</div>
              <div v-for="(f, i) in single.fileUrls" :key="i" style="font-size:12px;margin-bottom:2px">
                <a v-if="f.url" :href="f.url" target="_blank" style="color:#409eff">{{ f.name || f.url }}</a>
                <span v-else>{{ f.name }}</span>
              </div>
            </div>
            <!-- 分析文本：只展示预览，完整内容按需打开落盘报告（失败时也有快照） -->
            <div v-if="single.textLen || single.reportPath" style="margin-top:10px">
              <div style="font-size:12px;color:#606266;margin-bottom:4px">
                分析文本预览<span v-if="single.textLen">（共 {{ single.textLen }} 字符，此处仅显示前 2000 字）</span><span v-else>（无返回内容）</span>
                <a v-if="single.reportPath" :href="single.reportDocUrl || adpReportUrl(single.bugid)" target="_blank"
                   style="color:#409eff;margin-left:8px">查看完整报告</a>
              </div>
              <pre v-if="single.textPreview" style="max-height:300px;overflow:auto;background:#f5f7fa;padding:12px;border-radius:4px;font-size:12px;white-space:pre-wrap;word-break:break-all">{{ single.textPreview }}</pre>
            </div>
          </div>
          <el-alert v-if="single.error" type="error" :title="single.error" show-icon style="margin-top:12px"></el-alert>
        </el-card>
      </el-tab-pane>

      <!-- ====== Tab 3: 表格查找执行 ====== -->
      <el-tab-pane label="表格查找执行" name="lookup">
        <el-card shadow="never">
          <div v-if="lookup.tables.length" style="margin-bottom:8px;display:flex;align-items:center;gap:8px">
            <span style="font-size:13px;color:#606266">当前查找表格：</span>
            <el-select v-model="lookup.tableId" size="small" style="width:280px" @change="onLookupTableChange">
              <el-option v-for="t in lookup.tables" :key="t.table_id" :label="t.name" :value="t.table_id"></el-option>
            </el-select>
          </div>
          <el-alert type="info" :closable="false" show-icon
            title="根据 Jira 号从 ADP 多维表格查找记录，读取描述和触发时间（缺失则用 Jira API 补全），调用 ADP 分析后写回该行（跳过一致性判定）。"></el-alert>
          <!-- 模式切换 -->
          <div style="display:flex;gap:16px;align-items:center;margin-top:12px">
            <el-radio-group v-model="lookup.mode" size="small">
              <el-radio-button label="manual">手动输入</el-radio-button>
              <el-radio-button label="auto">自动查找</el-radio-button>
            </el-radio-group>
            <template v-if="lookup.mode === 'auto'">
              <span style="font-size:13px;color:#606266">抽取数量</span>
              <el-input-number v-model="lookup.limit" :min="1" :max="500" :step="1" step-strictly size="small" style="width:100px"></el-input-number>
              <el-checkbox v-model="lookup.filterAiPreliminary" size="small" style="margin-left:8px">过滤AI初步分析结果</el-checkbox>
            </template>
          </div>
          <div style="display:flex;gap:10px;align-items:flex-start;margin-top:12px">
            <template v-if="lookup.mode === 'manual'">
              <el-input v-model="lookup.input" type="textarea" :rows="3"
                placeholder="输入 Jira 号（多个用逗号、空格或换行分隔）&#10;如: VCU-123456, VCU-234567"
                style="flex:1"></el-input>
            </template>
            <template v-else>
              <el-alert type="warning" :closable="false" style="flex:1"
                title="自动查找模式：从多维表格中按顺序查找无报告的记录，抽取指定数量执行分析。"></el-alert>
            </template>
            <div style="display:flex;flex-direction:column;gap:8px">
              <el-button type="primary" :loading="lookup.running" @click="runLookup">
                {{ lookup.mode === 'auto' ? '自动查找并执行' : '查找并执行' }}
              </el-button>
              <el-button type="danger" :disabled="!lookup.running" @click="stopLookup">停止</el-button>
              <el-button @click="lookup.input = ''; lookup.results = []">清空</el-button>
            </div>
          </div>
        </el-card>

        <!-- 错误提示 -->
        <el-alert v-if="lookup.error" type="error" :title="lookup.error" show-icon
          closable style="margin-top:12px" @close="lookup.error = ''"></el-alert>
        <!-- 进度 -->
        <div v-if="lookup.progress" style="margin-top:12px;display:flex;gap:12px;align-items:center;flex-wrap:wrap">
          <el-tag v-if="lookup.progress.tableName" type="" size="small" effect="plain" style="font-weight:600">
            {{ lookup.progress.tableName }}
          </el-tag>
          <el-tag type="info" size="small">多维表格: {{ lookup.progress.totalRecords }}</el-tag>
          <el-tag v-if="lookup.mode === 'auto' && lookup.progress.noReportTotal != null" type="warning" size="small">
            无报告: {{ lookup.progress.noReportTotal }}
          </el-tag>
          <el-tag v-if="lookup.progress.aiFiltered > 0" type="info" size="small">
            AI已分析: {{ lookup.progress.aiFiltered }}
          </el-tag>
          <el-tag type="success" size="small">匹配: {{ lookup.progress.matched }}</el-tag>
          <span style="font-size:13px;color:#606266">
            已处理 {{ lookup.results.length }}/{{ lookup.progress.total }}
            | 成功 <span style="color:#67c23a;font-weight:600">{{ lookup.progress.success }}</span>
            | 失败 <span style="color:#f56c6c;font-weight:600">{{ lookup.progress.fail }}</span>
            <template v-if="lookup.progress.timeout">
              | 超时 <span style="color:#e6a23c;font-weight:600">{{ lookup.progress.timeout }}</span>
            </template>
            <template v-if="lookup.progress.skip">
              | 跳过 <span style="color:#909399;font-weight:600">{{ lookup.progress.skip }}</span>
            </template>
            <template v-if="lookup.progress.totalElapsed">
              | 总耗时 <span style="color:#409eff;font-weight:600">{{ formatDuration(lookup.progress.totalElapsed) }}</span>
            </template>
          </span>
        </div>
        <el-progress v-if="lookup.progress && lookup.progress.total"
          :percentage="Math.round((lookup.results.length / lookup.progress.total) * 100)"
          :status="lookup.running ? '' : (lookup.progress.fail === 0 ? 'success' : 'warning')"
          style="margin-top:8px"></el-progress>
        <!-- 当前并发组 -->
        <div v-if="lookup.running && lookup.runningItems.length" class="running-strip" style="margin-top:8px">
          <span style="font-size:12px;color:#606266;margin-right:8px">正在分析：</span>
          <el-tag v-for="key in lookup.runningItems" :key="key" type="warning" effect="plain" size="small" class="running-tag">
            <span class="running-dot"></span>{{ key }}
          </el-tag>
        </div>

        <!-- 结果表格 -->
        <el-table v-if="lookup.results.length" :data="lookup.results" size="small" stripe border
          max-height="360" style="margin-top:14px" row-key="jira_key">
          <el-table-column type="expand">
            <template #default="{ row }">
              <div v-if="row.text_preview || row.report_path" style="padding:12px 20px">
                <div style="font-size:12px;color:#606266;margin-bottom:6px">
                  分析文本预览<span v-if="row.text_len">（共 {{ row.text_len }} 字符）</span>
                  <a v-if="row.report_path" :href="reportHref(row)" target="_blank"
                     style="color:#409eff;margin-left:8px">查看完整报告</a>
                </div>
                <pre style="max-height:300px;overflow:auto;background:#f5f7fa;padding:10px;border-radius:4px;font-size:12px;white-space:pre-wrap;word-break:break-all">{{ row.text_preview }}</pre>
              </div>
              <div v-else style="padding:12px 20px;color:#909399;font-size:12px">无分析文本</div>
            </template>
          </el-table-column>
          <el-table-column prop="jira_key" label="Jira号" width="130">
            <template #default="{ row }">
              <span style="font-weight:600;color:#409eff">{{ row.jira_key }}</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="70" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.skipped" type="info" size="small">跳过</el-tag>
              <el-tag v-else-if="row.has_html" type="success" size="small">成功</el-tag>
              <el-tag v-else-if="row.timed_out" type="warning" size="small">超时</el-tag>
              <el-tag v-else type="danger" size="small">失败</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="失败类型" width="160" show-overflow-tooltip>
            <template #default="{ row }">
              <span v-if="row.fail_type" :style="{ color: row.fail_type.includes('超时') ? '#e6a23c' : '#f56c6c' }">{{ row.fail_type }}</span>
              <span v-else style="color:#c0c4cc">-</span>
            </template>
          </el-table-column>
          <el-table-column label="表格命中" width="70" align="center">
            <template #default="{ row }">
              <el-tag :type="row.bt_found ? 'success' : 'warning'" size="small">{{ row.bt_found ? '是' : '否' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="来源" width="70" align="center">
            <template #default="{ row }">
              <el-tag :type="row.desc_source === 'bitable' ? 'success' : (row.desc_source === 'api' ? 'warning' : 'info')" size="small">
                {{ row.desc_source === 'bitable' ? '表格' : (row.desc_source === 'api' ? 'API' : '-') }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="问题模块" width="110" show-overflow-tooltip>
            <template #default="{ row }">{{ row.results?.['agent分析的问题模块'] || '-' }}</template>
          </el-table-column>
          <el-table-column label="Root Cause" min-width="160" show-overflow-tooltip>
            <template #default="{ row }">{{ row.results?.['agent分析的root cause'] || row.error || '-' }}</template>
          </el-table-column>
          <el-table-column label="报告链接" width="160">
            <template #default="{ row }">
              <a v-if="row.results?.['_report_url']" :href="row.results['_report_url']" target="_blank" style="color:#409eff;font-size:12px">
                {{ row.results['_html_file'] || '查看报告' }}
              </a>
              <span v-else style="color:#909399">-</span>
            </template>
          </el-table-column>
          <el-table-column label="置信度" width="60">
            <template #default="{ row }">{{ row.results?.['置信度'] || '-' }}</template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script>
import * as XLSX from 'xlsx';

export default {
  name: 'AdpTestPanel',
  data() {
    return {
      activeTab: 'batch',
      single: {
        bugid: '', running: false, steps: [], jiraInfo: null,
        result: null, error: '', elapsed: 0, feishuOk: false, attachmentCount: 0,
        textPreview: '', textLen: 0, reportPath: '', reportDocUrl: '', failType: '', fileUrls: [],
      },
      batch: {
        items: [], fileName: '', batchSize: 2, continuous: false,
        running: false, enriching: false, progress: null, results: [], runningItems: [],
        colMap: { jira: '', trigger_time: '', description: '', summary: '' },
      },
      lookup: {
        input: '', running: false, progress: null, results: [], currentBatch: null, runningItems: [],
        mode: 'manual', limit: 10, filterAiPreliminary: false, abortCtrl: null, error: '', tableName: '',
        tables: [], tableId: '',
      },
    };
  },
  computed: {
    singleStepIndex() {
      const done = this.single.steps.filter(s => s.status === 'done').length;
      return Math.min(done, this.single.steps.length);
    },
  },
  mounted() {
    fetch('/api/config').then(r => r.json()).then(d => {
      const adp = (d.data || {}).adp || {};
      this.lookup.tableName = adp.bitable_table_name || '';
      fetch('/api/test/adp_tables').then(r => r.json()).then(res => {
        this.lookup.tables = (res.data || []);
        const cfgId = adp.bitable_table_id || '';
        const hit = this.lookup.tables.find((t) => t.table_id === cfgId);
        this.lookup.tableId = hit ? cfgId : ((this.lookup.tables[0] || {}).table_id || '');
        this.onLookupTableChange(this.lookup.tableId);
      }).catch(() => {});
    }).catch(() => {});
  },
  methods: {
    /** 格式化耗时（秒 → 可读字符串） */
    formatDuration(sec) {
      if (!sec || sec < 0) return '-';
      if (sec < 60) return `${Math.round(sec)}秒`;
      const m = Math.floor(sec / 60);
      const s = Math.round(sec % 60);
      if (m < 60) return s > 0 ? `${m}分${s}秒` : `${m}分钟`;
      const h = Math.floor(m / 60);
      const rm = m % 60;
      return rm > 0 ? `${h}小时${rm}分` : `${h}小时`;
    },
    /** 打开某条 ADP 分析报告的完整文本（优先飞书长期链接，服务关闭也可访问） */
    adpReportUrl(key) {
      return `/api/test/adp_report?jira_key=${encodeURIComponent(key || '')}`;
    },
    reportHref(row) {
      return (row && row.report_doc_url) || this.adpReportUrl(row && row.jira_key);
    },
    stepStatus(s) {
      if (s.status === 'done') return 'success';
      if (s.status === 'fail') return 'error';
      if (s.status === 'running') return 'process';
      return 'wait';
    },
    resetSingle() {
      Object.assign(this.single, {
        steps: [], jiraInfo: null, result: null, error: '', elapsed: 0,
        feishuOk: false, attachmentCount: 0,
        textPreview: '', textLen: 0, reportPath: '', reportDocUrl: '', failType: '', fileUrls: [],
      });
    },

    // ===== 单个执行 =====
    async runSingle() {
      if (!this.single.bugid.trim()) return;
      this.single.running = true;
      this.resetSingle();
      const allSteps = [
        { name: 'jira_info', label: '获取Jira信息', status: 'wait' },
        { name: 'attachments', label: '查询附件', status: 'wait' },
        { name: 'adp_analysis', label: 'ADP分析', status: 'wait' },
        { name: 'extract', label: '提取结果', status: 'wait' },
        { name: 'save_local', label: '保存本地', status: 'wait' },
        { name: 'write_feishu', label: '写入飞书', status: 'wait' },
      ];
      this.single.steps = allSteps;
      try {
        const resp = await fetch('/api/test/adp_single', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ bugid: this.single.bugid.trim() }),
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
              const d = JSON.parse(line.slice(6));
              if (d.type === 'step') {
                const step = this.single.steps.find(s => s.name === d.step);
                if (step) step.status = d.status;
                if (d.step === 'jira_info' && d.status === 'done') {
                  this.single.jiraInfo = { description: d.description, trigger_time: d.trigger_time };
                }
                if (d.step === 'attachments' && d.count != null) this.single.attachmentCount = d.count;
                if (d.step === 'adp_analysis' && d.elapsed != null) this.single.elapsed = d.elapsed;
                if (d.step === 'write_feishu') this.single.feishuOk = d.status === 'done';
              } else if (d.type === 'keepalive') {
                // ADP 分析心跳：显示进行中的耗时
                if (d.elapsed) this.single.elapsed = d.elapsed;
              } else if (d.type === 'done') {
                this.single.result = d.results || null;
                if (d.error) this.single.error = d.error;
                if (d.ok !== undefined) this.single.feishuOk = d.ok;
                this.single.textPreview = d.text_preview || '';
      this.single.textLen = d.text_len || 0;
      this.single.reportPath = d.report_path || '';
      this.single.reportDocUrl = d.report_doc_url || '';
      this.single.failType = d.fail_type || '';
                this.single.fileUrls = d.file_urls || [];
              }
            } catch { /* skip */ }
          }
        }
      } catch (e) {
        this.single.error = `请求失败: ${e.message}`;
      }
      this.single.running = false;
    },

    // ===== Excel 解析 =====
    onFileChange(file) {
      const raw = file.raw || file;
      this.batch.fileName = raw.name;
      const reader = new FileReader();
      reader.onload = (e) => {
        try {
          const wb = XLSX.read(e.target.result, { type: 'array' });
          const ws = wb.Sheets[wb.SheetNames[0]];
          const rows = XLSX.utils.sheet_to_json(ws, { defval: '' });
          if (!rows.length) { this.$message.warning('Excel 为空'); return; }
          // 自动匹配列名
          const keys = Object.keys(rows[0]);
          const findCol = (...candidates) => {
            for (const k of keys) {
              const lk = k.toLowerCase().replace(/[\s_]/g, '');
              for (const c of candidates) {
                if (lk.includes(c.toLowerCase().replace(/[\s_]/g, ''))) return k;
              }
            }
            return '';
          };
          const jiraCol = findCol('jira号', 'Jira链接', 'jira_key', 'Jira号', 'jira');
          const ttCol = findCol('问题触发时间点', '触发时间', 'trigger_time', '问题发生时间', '时间锚点');
          const descCol = findCol('描述', 'description', '问题描述');
          this.batch.colMap = {
            jira: jiraCol, trigger_time: ttCol, description: descCol,
            summary: [jiraCol, ttCol, descCol].filter(Boolean).join(', ') || '未识别',
          };
          this.batch.items = rows.map(r => this._parseRow(r, jiraCol, ttCol, descCol)).filter(r => r.bugid);
        } catch (err) {
          this.$message.error(`Excel 解析失败: ${err.message}`);
        }
      };
      reader.readAsArrayBuffer(raw);
    },
    _parseRow(row, jiraCol, ttCol, descCol) {
      let bugid = String(jiraCol ? row[jiraCol] : '').trim();
      const m = bugid.match(/([A-Z]+-\d+)/);
      if (m) bugid = m[1];
      return {
        bugid,
        trigger_time: String(ttCol ? row[ttCol] : '').trim(),
        description: String(descCol ? row[descCol] : '').trim(),
        _source: 'excel', _status: 'pending',
      };
    },

    // ===== 补全缺失字段（调 Jira API）=====
    async enrichItems() {
      const missing = this.batch.items.filter(it => !it.description || !it.trigger_time);
      if (!missing.length) { this.$message.success('所有字段已完整，无需补全'); return; }
      this.batch.enriching = true;
      try {
        const bugids = missing.map(it => it.bugid);
        const resp = await fetch('/api/test/adp_enrich', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ bugids }),
        });
        const data = await resp.json();
        if (data.code !== 200 && data.code !== 0) {
          this.$message.error(data.msg || '补全失败'); return;
        }
        const enrichMap = {};
        (data.data || []).forEach(r => { enrichMap[r.bugid] = r; });
        let filledDesc = 0, filledTime = 0;
        for (const item of this.batch.items) {
          const e = enrichMap[item.bugid];
          if (!e) continue;
          if (!item.description && e.description) { item.description = e.description; item._source = 'api'; filledDesc++; }
          if (!item.trigger_time && e.trigger_time) { item.trigger_time = e.trigger_time; item._source = 'api'; filledTime++; }
        }
        this.$message.success(`补全完成: 描述 +${filledDesc}, 触发时间 +${filledTime}`);
      } catch (e) {
        this.$message.error(`补全请求失败: ${e.message}`);
      }
      this.batch.enriching = false;
    },

    // ===== 表格查找执行 =====
    onLookupTableChange(tid) {
      const t = (this.lookup.tables || []).find((x) => x.table_id === tid);
      this.lookup.tableName = t ? t.name : '';
    },
    async runLookup() {
      const isAuto = this.lookup.mode === 'auto';
      const text = this.lookup.input.trim();
      let bugids = [];
      if (!isAuto) {
        if (!text) return;
        bugids = text.split(/[,，\s]+/).map(s => s.trim()).filter(Boolean);
        if (!bugids.length) return;
      }
      this.lookup.running = true;
      this.lookup.results = [];
      this.lookup.currentBatch = null;
      this.lookup.runningItems = [];
      this.lookup.error = '';
      this.lookup.abortCtrl = new AbortController();
      this.lookup.progress = { total: isAuto ? this.lookup.limit : bugids.length, totalRecords: 0, matched: 0, success: 0, fail: 0, timeout: 0, skip: 0, noReportTotal: null, aiFiltered: 0, totalElapsed: 0, tableName: '' };
      try {
        const body = isAuto
          ? { mode: 'auto', limit: this.lookup.limit, filter_ai_preliminary: this.lookup.filterAiPreliminary,
              table_id: this.lookup.tableId, table_name: this.lookup.tableName }
          : { bugids, table_id: this.lookup.tableId, table_name: this.lookup.tableName };
        const resp = await fetch('/api/test/adp_lookup', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
          signal: this.lookup.abortCtrl.signal,
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
              const d = JSON.parse(line.slice(6));
              if (d.type === 'step' && d.step === 'read_bitable') {
                if (d.status === 'done') {
                  this.lookup.progress.totalRecords = d.total_records;
                  this.lookup.progress.matched = d.matched;
                  if (d.table_name) this.lookup.progress.tableName = d.table_name;
                  if (d.mode === 'auto') {
                    this.lookup.progress.noReportTotal = d.no_report_total;
                    this.lookup.progress.total = d.matched;
                  }
                  if (d.ai_filtered != null) this.lookup.progress.aiFiltered = d.ai_filtered;
                } else if (d.status === 'fail') {
                  this.lookup.error = `多维表格读取失败: ${d.error || '未知错误'}（请检查 adp 配置段）`;
                }
              } else if (d.type === 'item_start') {
                if (!this.lookup.runningItems.includes(d.jira_key)) this.lookup.runningItems.push(d.jira_key);
              } else if (d.type === 'item_done') {
                this.lookup.results.push(d);
                this.lookup.runningItems = this.lookup.runningItems.filter(k => k !== d.jira_key);
                if (d.skipped) this.lookup.progress.skip++;
                else if (d.has_html) this.lookup.progress.success++;
                else if (d.timed_out) this.lookup.progress.timeout++;
                else this.lookup.progress.fail++;
              } else if (d.type === 'item_timeout') {
                // 单条超时（等待其自然收尾，不立即计入失败）
              } else if (d.type === 'keepalive') {
                this.lookup.runningItems = d.running || [];
              } else if (d.type === 'done') {
                // 完成：记录总耗时与超时数
                if (d.total_elapsed) this.lookup.progress.totalElapsed = d.total_elapsed;
                if (typeof d.timeout === 'number') this.lookup.progress.timeout = d.timeout;
                this.lookup.runningItems = [];
              }
            } catch { /* skip */ }
          }
        }
      } catch (e) {
        if (e.name === 'AbortError') {
          this.$message.warning('已停止查找');
        } else {
          this.$message.error(`查找执行失败: ${e.message}`);
        }
      }
      // SSE 连接关闭但无结果时提示
      if (this.lookup.results.length === 0 && !this.lookup.error && this.lookup.progress && this.lookup.progress.totalRecords === 0) {
        this.lookup.error = 'SSE 连接已关闭但未收到数据，请检查后端日志和 adp 配置段是否完整';
      }
      this.lookup.running = false;
      this.lookup.runningItems = [];
      this.lookup.abortCtrl = null;
    },
    stopLookup() {
      fetch('/api/test/adp_lookup/stop', { method: 'POST', headers: { 'Content-Type': 'application/json' } });
      if (this.lookup.abortCtrl) this.lookup.abortCtrl.abort();
    },
    // ===== 批量执行 =====
    async runBatch() {
      if (!this.batch.items.length) return;
      this.batch.running = true;
      this.batch.results = [];
      this.batch.progress = { current: 0, total: 0, success: 0, fail: 0 };
      this.batch.items.forEach(it => { it._status = 'pending'; });
      try {
        const items = this.batch.items.map(it => ({
          bugid: it.bugid, description: it.description, trigger_time: it.trigger_time,
        }));
        const resp = await fetch('/api/test/adp_batch', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ items, batch_size: this.batch.batchSize, continuous: this.batch.continuous }),
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
              const d = JSON.parse(line.slice(6));
              if (d.type === 'start') {
                this.batch.progress.total = d.total_batches;
              } else if (d.type === 'batch_start') {
                this.batch.progress.current = d.batch;
              } else if (d.type === 'item_done') {
                this.batch.results.push(d);
                const row = this.batch.items.find(it => it.bugid === d.jira_key);
                if (row) row._status = d.ok ? 'done' : 'fail';
                this.batch.runningItems = this.batch.runningItems.filter(k => k !== d.jira_key);
                if (d.ok) this.batch.progress.success++;
                else this.batch.progress.fail++;
              } else if (d.type === 'done') {
                this.batch.progress.current = this.batch.progress.total;
              } else if (d.type === 'keepalive') {
                this.batch.runningItems = d.running || [];
              } else if (d.type === 'item_start') {
                if (!this.batch.runningItems.includes(d.jira_key)) this.batch.runningItems.push(d.jira_key);
                const row = this.batch.items.find(it => it.bugid === d.jira_key);
                if (row) row._status = 'running';
              }
            } catch { /* skip */ }
          }
        }
      } catch (e) {
        this.$message.error(`批量请求失败: ${e.message}`);
      }
      this.batch.running = false;
      this.batch.runningItems = [];
    },
  },
};
</script>

<style scoped>
.test-panel { padding: 0; }
.section-title { font-size: 16px; font-weight: 600; margin-bottom: 10px; color: #303133; }
.adp-tabs { border-radius: 8px; }
.adp-tabs :deep(.el-tabs__content) { padding: 16px; overflow: visible; }
/* 执行中动画条 */
.running-strip {
  display: flex; align-items: center; flex-wrap: wrap; gap: 6px;
  padding: 8px 12px; background: #fdf6ec; border-radius: 6px; border: 1px solid #faecd8;
}
.running-tag {
  animation: running-pulse 1.8s ease-in-out infinite;
}
.running-dot {
  display: inline-block; width: 6px; height: 6px; border-radius: 50%;
  background: #e6a23c; margin-right: 5px; vertical-align: middle;
  animation: dot-blink 1s ease-in-out infinite;
}
@keyframes running-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.55; }
}
@keyframes dot-blink {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.3; transform: scale(0.7); }
}
</style>
