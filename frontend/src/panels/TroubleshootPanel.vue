<template>
  <div class="test-panel">
    <div class="section-title">问题排查</div>
    <el-tabs v-model="troubleshootTab" type="border-card" class="troubleshoot-tabs">

      <!-- ==================== 批量排查 ==================== -->
      <el-tab-pane label="批量排查" name="batch">
    <!-- 步骤1：查询多维表格记录 -->
    <el-card shadow="never">
      <template #header><span style="font-weight:700">① 查询多维表格执行记录</span></template>
      <el-form inline>
        <el-form-item label="排查时间">
          <el-date-picker v-model="troubleshoot.afterTime" type="datetime" value-format="YYYY-MM-DD HH:mm:ss"
            placeholder="查询该时间之后执行完成的记录" style="width:220px"></el-date-picker>
        </el-form-item>
        <el-form-item label="分析结果">
          <el-radio-group v-model="troubleshoot.resultFilter">
            <el-radio-button label="">全部</el-radio-button>
            <el-radio-button label="失败">失败</el-radio-button>
            <el-radio-button label="成功">成功</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="触发来源">
          <el-radio-group v-model="troubleshoot.sourceFilter">
            <el-radio-button label="">全部</el-radio-button>
            <el-radio-button label="parseFullTicket">线上</el-radio-button>
            <el-radio-button label="feishu_bot">飞书机器人</el-radio-button>
            <el-radio-button label="jira_analyze">PC</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="troubleshoot.dedup">按jira号去重</el-checkbox>
          <el-checkbox v-model="troubleshoot.noManualReview">人工审核为空</el-checkbox>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="troubleshoot.querying" @click="runTroubleshootQuery">查询</el-button>
          <el-button type="success" :loading="troubleshoot.queryingSuccess" :disabled="!troubleshoot.records.length" @click="querySuccessRecords">查询失败Jira号所有成功记录</el-button>
        </el-form-item>
      </el-form>
      <el-table v-if="troubleshoot.records.length" :data="troubleshoot.records" size="small" stripe border max-height="280">
        <el-table-column type="index" label="#" width="45"></el-table-column>
        <el-table-column prop="jira号" label="Jira号" width="120"></el-table-column>
        <el-table-column prop="分析结果" label="分析结果" width="90">
          <template #default="{row}"><el-tag :type="row['分析结果']==='成功'?'success':'danger'" size="small">{{ row['分析结果'] || '-' }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="分析完成时间" label="分析完成时间" width="160"></el-table-column>
        <el-table-column prop="分析问题时间" label="分析问题时间" width="160"></el-table-column>
        <el-table-column prop="错误信息" label="错误信息" min-width="220" show-overflow-tooltip></el-table-column>
        <el-table-column prop="触发来源" label="触发来源" width="100">
          <template #default="{row}">
            <el-tag v-if="row['触发来源']==='parseFullTicket'" type="warning" size="small">线上</el-tag>
            <el-tag v-else-if="row['触发来源']==='feishu_bot'" type="success" size="small">飞书机器人</el-tag>
            <el-tag v-else-if="row['触发来源']==='jira_analyze'" type="info" size="small">PC</el-tag>
            <span v-else style="color:#c0c4cc">{{ row['触发来源'] || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="人工审核结果" label="人工" width="100" show-overflow-tooltip>
          <template #default="{row}">
            <span v-if="row['人工审核结果']" style="color:#67c23a">{{ row['人工审核结果'] }}</span>
            <span v-else style="color:#c0c4cc">-</span>
          </template>
        </el-table-column>
        <el-table-column label="附件名称" width="180" show-overflow-tooltip>
          <template #default="{row}">
            <span v-if="getMainEntries(row) !== '-'" style="color:#67c23a">{{ getMainEntries(row) }}</span>
            <span v-else style="color:#c0c4cc">-</span>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="troubleshoot.records.length" style="margin-top:10px">
        <el-button type="warning" :loading="troubleshoot.diagRunning" @click="diagnoseAllFailed">
          <template v-if="troubleshoot.diagRunning">诊断中 {{ troubleshoot.diagResults.length }}/{{ getTroubleshootFailedCount() }}…</template>
          <template v-else>批量诊断失败记录（{{ getTroubleshootFailedCount() }} 条）</template>
        </el-button>
        <el-button v-if="troubleshoot.diagRunning" type="danger" @click="stopDiagnose">停止诊断</el-button>
        <el-button type="primary" :loading="troubleshoot.diagRunning"
          :disabled="!getManualReviewCount()" @click="rerunManualReview">
          待人工审核重新执行（{{ getManualReviewCount() }} 条）
        </el-button>
        <el-checkbox v-model="troubleshoot.execOnlyEmptyReview" style="margin-left:8px">仅执行人工审核为空的记录</el-checkbox>
        <el-checkbox v-model="troubleshoot.skipVideoCache" style="margin-left:8px">跳过视频缓存</el-checkbox>
        <el-button type="info" :loading="troubleshoot.preClassifying" @click="preClassifyRecords"
          :disabled="!troubleshoot.records.filter(r => r['分析结果'] === '失败').length">
          批量预归类（{{ troubleshoot.records.filter(r => r['分析结果'] === '失败').length }} 条）
        </el-button>
      </div>
      <!-- 成功记录表格 -->
      <template v-if="troubleshoot.successRecords && troubleshoot.successRecords.length">
        <div style="margin-top:12px;font-weight:600;color:#67c23a;font-size:13px">成功记录（{{ troubleshoot.successRecords.length }} 条）</div>
        <el-table :data="troubleshoot.successRecords" size="small" stripe border max-height="220" style="margin-top:4px">
          <el-table-column type="index" label="#" width="45"></el-table-column>
          <el-table-column prop="jira号" label="Jira号" width="120"></el-table-column>
          <el-table-column prop="分析结果" label="分析结果" width="90">
            <template #default="{row}"><el-tag type="success" size="small">{{ row['分析结果'] }}</el-tag></template>
          </el-table-column>
          <el-table-column prop="分析完成时间" label="分析完成时间" width="160"></el-table-column>
          <el-table-column prop="分析问题时间" label="分析问题时间" width="160"></el-table-column>
          <el-table-column prop="错误信息" label="错误信息" min-width="200" show-overflow-tooltip></el-table-column>
          <el-table-column prop="触发来源" label="触发来源" width="100">
            <template #default="{row}">
              <el-tag v-if="row['触发来源']==='parseFullTicket'" type="warning" size="small">线上</el-tag>
              <el-tag v-else-if="row['触发来源']==='feishu_bot'" type="success" size="small">飞书机器人</el-tag>
              <el-tag v-else-if="row['触发来源']==='jira_analyze'" type="info" size="small">PC</el-tag>
              <span v-else style="color:#c0c4cc">{{ row['触发来源'] || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="人工审核结果" label="人工" width="100" show-overflow-tooltip>
            <template #default="{row}">
              <span v-if="row['人工审核结果']" style="color:#67c23a">{{ row['人工审核结果'] }}</span>
              <span v-else style="color:#c0c4cc">-</span>
            </template>
          </el-table-column>
          <el-table-column label="附件名称" width="180" show-overflow-tooltip>
            <template #default="{row}">
              <span v-if="getMainEntries(row) !== '-'" style="color:#67c23a">{{ getMainEntries(row) }}</span>
              <span v-else style="color:#c0c4cc">-</span>
            </template>
          </el-table-column>
        </el-table>
      </template>
      <el-alert v-if="troubleshoot.successSearched && (!troubleshoot.successRecords || !troubleshoot.successRecords.length)" type="info" :closable="false"
        title="未找到失败 Jira 号对应的成功记录" style="margin-top:8px"></el-alert>
    </el-card>

    <!-- 步骤②a：跳过排查的记录 -->
    <el-card v-if="getSkipDiagResults().length" shadow="never" style="margin-top:12px">
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
          <div style="display:flex;align-items:center;gap:8px">
            <el-tag type="info" size="small" effect="dark">跳过排查</el-tag>
            <span style="font-weight:700">无需深入分析（{{ getFilteredSkipResults().length }}/{{ getSkipDiagResults().length }} 条）</span>
          </div>
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
            <el-select v-model="troubleshoot.skipCategoryFilter" size="small" placeholder="按错误类型筛选" clearable style="width:200px">
              <el-option v-for="c in getSkipCategories()" :key="c" :label="c" :value="c"></el-option>
            </el-select>
            <el-button size="small" type="success" :loading="troubleshoot.writingReview" @click="batchWriteSkipReview"
              :disabled="!getFilteredSkipResults().filter(r => r.report && r.report.human_reason).length">
              批量写入人工审核{{ troubleshoot.skipCategoryFilter ? '（筛选）' : '' }}
            </el-button>
            <el-button size="small" type="primary" :loading="troubleshoot.sendingToDeveloper" @click="sendToDeveloper"
              :disabled="!getFilteredSkipResults().length">
              发送给开发者{{ troubleshoot.skipCategoryFilter ? '（筛选）' : '' }}
            </el-button>
          </div>
        </div>
      </template>
      <el-table :data="getFilteredSkipResults()" size="small" stripe border max-height="320" row-key="bugid">
        <el-table-column type="index" label="#" width="45"></el-table-column>
        <el-table-column prop="bugid" label="Jira号" width="120"></el-table-column>
        <el-table-column prop="category" label="问题归类" width="170">
          <template #default="{row}"><el-tag :type="diagCategoryTagType(row.category)" size="small">{{ row.category }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="err_msg" label="错误信息" min-width="200" show-overflow-tooltip>
          <template #default="{row}">
            <el-popover v-if="row.err_msg" placement="top" :width="400" trigger="hover">
              <template #reference><span class="text-truncate-cell" style="color:#f56c6c">{{ row.err_msg }}</span></template>
              <div style="white-space:pre-wrap;word-break:break-all;user-select:text;cursor:text;font-size:12px">{{ row.err_msg }}</div>
            </el-popover>
            <span v-else style="color:#c0c4cc">-</span>
          </template>
        </el-table-column>
        <el-table-column label="人工审核结果" min-width="200">
          <template #default="{row}">
            <div v-if="troubleshoot.editingSkipBugid === row.bugid" style="display:flex;align-items:center;gap:4px">
              <el-input v-model="troubleshoot.editingSkipReason" size="small" placeholder="输入人工审核结果" autofocus
                @keyup.enter="saveSkipHumanReason(row)"></el-input>
              <el-button size="small" type="success" link @click="saveSkipHumanReason(row)">保存</el-button>
              <el-button size="small" type="info" link @click="troubleshoot.editingSkipBugid=''">取消</el-button>
            </div>
            <div v-else style="display:flex;align-items:center;gap:6px">
              <span v-if="row.report && row.report.human_reason" style="color:#e6a23c;font-weight:600;font-size:12px">{{ row.report.human_reason }}</span>
              <span v-else style="color:#c0c4cc;font-size:12px">-</span>
              <el-button link size="small" type="primary" style="color:#909399;font-size:12px" @click="startEditSkipHuman(row)">编辑</el-button>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="done_time" label="分析完成时间" width="160"></el-table-column>
      </el-table>
    </el-card>

    <!-- 步骤②：诊断归类结果（需分析） -->
    <el-card v-if="getAnalysisDiagResults().length" shadow="never" style="margin-top:12px">
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
          <span style="font-weight:700">② 诊断归类结果（需分析 {{ getAnalysisDiagResults().length }} 条）</span>
          <el-select v-model="troubleshoot.categoryFilter" size="small" placeholder="按归类筛选" clearable style="width:200px">
            <el-option v-for="c in getTroubleshootCategories()" :key="c" :label="c" :value="c"></el-option>
          </el-select>
        </div>
        <div class="diag-action-bar">
          <el-button size="small" type="warning" :loading="troubleshoot.exportingTriggerIssues" @click="exportTriggerTimeIssues"
            :disabled="!troubleshoot.diagResults.filter(r => r.category === '触发时间问题' || r.category?.includes('触发时间')).length">
            生成触发时间问题表格
          </el-button>
          <el-button size="small" type="success" :loading="troubleshoot.writingReview" @click="batchWriteReview"
            :disabled="!getFilteredDiagResults().filter(r => r.report && r.report.human_reason).length">
            批量写入人工审核结果{{ troubleshoot.categoryFilter ? '（筛选）' : '' }}
          </el-button>
          <el-checkbox v-model="troubleshoot.onlyEmptyReview" size="small">仅人工审核结果为空</el-checkbox>
          <el-button size="small" type="primary" :loading="troubleshoot.batchApplyingTime" @click="batchApplyCorrectionTimes"
            :disabled="!getApplicableCorrectionCount()">
            一键应用正确时间（{{ getApplicableCorrectionCount() }}）
          </el-button>
        </div>
      </template>
      <el-table :data="getFilteredDiagResults().filter(r => r.needs_analysis !== false)" size="small" stripe border max-height="320" row-key="bugid">
        <el-table-column type="index" label="#" width="45"></el-table-column>
        <el-table-column prop="bugid" label="Jira号" width="120"></el-table-column>
        <el-table-column prop="category" label="问题归类" width="170">
          <template #default="{row}"><el-tag :type="diagCategoryTagType(row.category)" size="small">{{ row.category }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="done_time" label="分析完成时间" width="160"></el-table-column>
        <el-table-column prop="problem_time" label="错误时间" width="150"></el-table-column>
        <el-table-column prop="detail" label="诊断详情" min-width="260" show-overflow-tooltip></el-table-column>
        <el-table-column label="人工审核结果" min-width="200" show-overflow-tooltip>
          <template #default="{row}">
            <span v-if="row.report && row.report.human_reason" style="color:#e6a23c;font-weight:600">{{ row.report.human_reason }}</span>
            <span v-else style="color:#c0c4cc">-</span>
          </template>
        </el-table-column>
        <el-table-column label="解压后文件名" width="130" align="center">
          <template #default="{row}">
            <el-popover v-if="getDiagEntries(row).length" placement="left" :width="420" trigger="click">
              <template #reference><el-button size="small" link type="primary">查看 {{ getDiagEntries(row).length }} 个</el-button></template>
              <div style="max-height:320px;overflow:auto;font-size:12px;user-select:text">
                <div v-for="(e,i) in getDiagEntries(row)" :key="i"
                  :style="e.matched?'color:#67c23a;font-weight:700':''">{{ e.name }}{{ e.matched ? ' ✔命中错误时间' : '' }}</div>
              </div>
            </el-popover>
            <span v-else>-</span>
          </template>
        </el-table-column>

      </el-table>
    </el-card>

    <!-- 步骤③：报告内容 -->
    <el-card v-if="troubleshoot.diagResults.length" shadow="never" style="margin-top:12px">
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span style="font-weight:700">③ 报告内容</span>
          <el-button size="small" type="primary" link @click="copyAllReports">全部复制</el-button>
        </div>
      </template>
      <div style="max-height:400px;overflow:auto;padding:4px">
        <div v-for="row in getFilteredDiagResults()" :key="row.bugid" style="margin-bottom:16px;border:1px solid #ebeef5;border-radius:8px;padding:12px;background:#fff;position:relative">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <div style="font-weight:700;font-size:15px;color:#303133">{{ row.bugid }}</div>
            <el-button size="small" type="primary" link @click="copyReport(row)">复制</el-button>
          </div>
          <div v-if="row.report" style="font-size:13px;color:#606266;line-height:1.8">
            <div v-if="row.correction_time" style="margin-bottom:4px"><span style="color:#409eff;font-weight:600">修正触发时间：</span><span style="color:#e6a23c;font-weight:600">{{ row.correction_time }}</span></div>
            <div style="margin-bottom:4px"><span style="color:#409eff;font-weight:600">AI分析失败原因：</span><span>{{ row.report.ai_reason || '无' }}</span></div>
            <div style="margin-bottom:4px"><span style="color:#409eff;font-weight:600">人工分析失败原因：</span><span>{{ row.report.human_reason || '无' }}</span></div>
            <div v-if="row.report.retry_result" style="margin-bottom:4px"><span style="color:#409eff;font-weight:600">重试结果：</span><span>{{ row.report.retry_result }}</span></div>
            <div style="margin-bottom:4px"><span style="color:#409eff;font-weight:600">问题归类：</span><span>{{ row.report.final_category || row.category }}</span></div>
          </div>
          <div v-else style="font-size:13px;color:#909399">暂无报告内容</div>
        </div>
      </div>
    </el-card>
      </el-tab-pane>

      <!-- ==================== 单个排查 ==================== -->
      <el-tab-pane label="单个排查" name="single">
    <!-- 模块：单个失败排查 -->
    <el-card shadow="never" style="border:2px solid #409eff">
      <template #header><span style="font-weight:700">单个Jira号排查</span></template>
      <el-alert type="info" :closable="false"
        title="输入 Jira 号（支持模糊搜索）→ 查询多维表格匹配记录 → 选择记录后执行诊断归类"></el-alert>
      <el-form inline style="margin-top:10px">
        <el-form-item label="Jira 号" style="margin-bottom:0">
          <el-input v-model="singleTroubleshoot.keyword" placeholder="如 VCU-541531" style="width:200px"
            @keyup.enter="searchSingleTroubleshoot" clearable></el-input>
        </el-form-item>
        <el-form-item style="margin-bottom:0">
          <el-button type="primary" :loading="singleTroubleshoot.searching" @click="searchSingleTroubleshoot">查询</el-button>
        </el-form-item>
      </el-form>
      <el-alert v-if="singleTroubleshoot.searchMsg" :type="singleTroubleshoot.searchError ? 'error' : 'success'"
        :closable="false" :title="singleTroubleshoot.searchMsg" style="margin-top:8px"></el-alert>
      <el-table v-if="singleTroubleshoot.rows.length" :data="singleTroubleshoot.rows" size="small" stripe border
        max-height="320" highlight-current-row @current-change="onSingleTroubleshootSelect" style="margin-top:10px">
        <el-table-column type="index" label="#" width="45"></el-table-column>
        <el-table-column prop="jira号" label="Jira号" width="120"></el-table-column>
        <el-table-column prop="分析结果" label="分析结果" width="90">
          <template #default="{row}"><el-tag :type="row['分析结果']==='成功'?'success':'danger'" size="small">{{ row['分析结果'] || '-' }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="分析完成时间" label="分析完成时间" width="160"></el-table-column>
        <el-table-column prop="分析问题时间" label="分析问题时间" width="160"></el-table-column>
        <el-table-column prop="错误信息" label="错误信息" min-width="220" show-overflow-tooltip></el-table-column>
        <el-table-column prop="人工审核结果" label="人工" width="100" show-overflow-tooltip>
          <template #default="{row}">
            <span v-if="row['人工审核结果']" style="color:#67c23a">{{ row['人工审核结果'] }}</span>
            <span v-else style="color:#c0c4cc">-</span>
          </template>
        </el-table-column>
        <el-table-column label="附件名称" width="180" show-overflow-tooltip>
          <template #default="{row}">
            <span v-if="getMainEntries(row) !== '-'" style="color:#67c23a">{{ getMainEntries(row) }}</span>
            <span v-else style="color:#c0c4cc">-</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
    <!-- 单个诊断结果 -->
    <el-card v-if="singleTroubleshoot.diagResult" shadow="never" style="margin-top:12px">
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span style="font-weight:700">诊断结果：{{ singleTroubleshoot.diagResult.bugid }}</span>
          <el-tag :type="diagCategoryTagType(singleTroubleshoot.diagResult.category)" size="small">{{ singleTroubleshoot.diagResult.category }}</el-tag>
        </div>
      </template>
      <div style="font-size:13px;line-height:1.7">
        <p v-if="singleTroubleshoot.diagResult.detail"><b>诊断详情：</b>{{ singleTroubleshoot.diagResult.detail }}</p>
        <p v-if="singleTroubleshoot.diagResult.report"><b>AI分析失败原因：</b>{{ singleTroubleshoot.diagResult.report.ai_reason }}</p>
        <p v-if="singleTroubleshoot.diagResult.report"><b>人工分析失败原因：</b>{{ singleTroubleshoot.diagResult.report.human_reason }}</p>
        <p v-if="singleTroubleshoot.diagResult.verify_status">
          <b>验证状态：</b>{{ singleTroubleshoot.diagResult.verify_status }}
          <span v-if="singleTroubleshoot.diagResult.suggested_time">（建议时间：{{ singleTroubleshoot.diagResult.suggested_time }}）</span>
        </p>
      </div>
    </el-card>
      </el-tab-pane>

      <!-- ==================== 按批次排查 ==================== -->
      <el-tab-pane label="按批次排查" name="batch_history">
        <el-card shadow="never">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
            <el-button size="small" @click="loadHistoryBatches" :loading="batchHistory.batchListLoading">刷新批次列表</el-button>
          </div>
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;flex-wrap:wrap">
            <el-select v-model="batchHistory.selectedBatches" multiple size="small" placeholder="选择云端批次（可多选）" filterable style="width:420px"
              :loading="batchHistory.batchListLoading" @change="onBatchHistorySelected">
              <el-option v-for="b in batchHistory.batchList" :key="b.value" :label="b.label" :value="b.value"></el-option>
            </el-select>
            <el-button size="small" :disabled="!batchHistory.selectedBatches.length" :loading="batchHistory.previewLoading" @click="previewBatchHistory">预览</el-button>
            <el-button type="primary" size="small" :disabled="!batchHistory.selectedBatches.length" :loading="batchHistory.jiraLoading" @click="loadHistoryJira">查询多维表格数据</el-button>
            <a v-if="batchHistory.selectedBatchUrl" :href="batchHistory.selectedBatchUrl" target="_blank" style="color:#409eff;font-size:12px;text-decoration:none">查看云端文档 ↗</a>
            <el-button v-if="batchHistory.jiraRows.length" type="success" size="small" :loading="batchHistory.assessing" @click="runBatchHistoryAssess">本批次质量评估</el-button>
          </div>
          <template v-if="batchHistory.jiraRows.length || batchHistory.jiraLoading">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;flex-wrap:wrap">
              <el-select v-model="batchHistory.resultFilter" size="small" placeholder="分析结果" clearable style="width:120px">
                <el-option label="成功" value="成功"></el-option><el-option label="失败" value="失败"></el-option>
              </el-select>
              <el-select v-model="batchHistory.sourceFilter" size="small" placeholder="触发来源" clearable style="width:130px">
                <el-option label="线上" value="parseFullTicket"></el-option><el-option label="飞书机器人" value="feishu_bot"></el-option><el-option label="PC" value="jira_analyze"></el-option>
              </el-select>
              <el-input v-model="batchHistory.keyword" size="small" placeholder="搜索 Jira 号" clearable style="width:160px"></el-input>
              <el-checkbox v-model="batchHistory.manualEmpty" size="small">人工审核为空</el-checkbox>
              <el-tag type="info" size="small">{{ getFilteredBatchHistory().length }} / {{ batchHistory.jiraRows.length }} 条</el-tag>
            </div>
            <el-table :data="getFilteredBatchHistory()" size="small" stripe max-height="400" v-loading="batchHistory.jiraLoading">
              <el-table-column type="index" label="#" width="45"></el-table-column>
              <el-table-column prop="jira号" label="jira号" width="120" sortable show-overflow-tooltip></el-table-column>
              <el-table-column prop="分析结果" label="分析结果" width="90" sortable>
                <template #default="{row}"><el-tag v-if="row['分析结果']" :type="row['分析结果']==='成功'?'success':'danger'" size="small">{{ row['分析结果'] }}</el-tag><span v-else>-</span></template>
              </el-table-column>
              <el-table-column prop="执行结果" label="批量结果" width="90">
                <template #default="{row}"><el-tag v-if="row['执行结果']" :type="row['执行结果']==='成功'?'success':'danger'" size="small" effect="plain">{{ row['执行结果'] }}</el-tag><span v-else>-</span></template>
              </el-table-column>
              <el-table-column prop="触发来源" label="触发来源" width="100" show-overflow-tooltip>
                <template #default="{row}">
                  <el-tag v-if="row['触发来源']" :type="row['触发来源']==='parseFullTicket'?'':row['触发来源']==='feishu_bot'?'warning':'info'" size="small" effect="plain">
                    {{ ({parseFullTicket:'线上',feishu_bot:'飞书机器人',jira_analyze:'PC'})[row['触发来源']] || row['触发来源'] }}
                  </el-tag><span v-else style="color:#c0c4cc">-</span>
                </template>
              </el-table-column>
              <el-table-column prop="错误信息" label="错误信息" min-width="160" show-overflow-tooltip>
                <template #default="{row}">
                  <el-popover v-if="row['错误信息']" placement="top" :width="360" trigger="hover">
                    <template #reference><span class="text-truncate-cell" style="color:#f56c6c">{{ row['错误信息'] }}</span></template>
                    <div style="white-space:pre-wrap;word-break:break-all;user-select:text;cursor:text">{{ row['错误信息'] }}</div>
                  </el-popover><span v-else>-</span>
                </template>
              </el-table-column>
              <el-table-column prop="分析完成时间" label="分析完成时间" width="160" sortable show-overflow-tooltip></el-table-column>
            </el-table>
            <el-card v-if="batchHistory.assessResult" shadow="never" style="margin-top:10px;padding:6px 0">
              <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
                <el-tag type="info">批量执行: {{ batchHistory.assessResult.total }} 个</el-tag>
                <el-tag type="success">成功: {{ batchHistory.jiraRows.filter(r=>r['分析结果']==='成功').length }}</el-tag>
                <el-tag type="danger">失败: {{ batchHistory.jiraRows.filter(r=>r['分析结果']==='失败').length }}</el-tag>
                <el-tag :type="(()=>{const s=batchHistory.jiraRows.filter(r=>r['分析结果']==='成功').length,f=batchHistory.jiraRows.filter(r=>r['分析结果']==='失败').length,d=s+f||1;return s/d>=0.8?'success':'warning'})()">
                  成功率: {{ (()=>{const s=batchHistory.jiraRows.filter(r=>r['分析结果']==='成功').length,f=batchHistory.jiraRows.filter(r=>r['分析结果']==='失败').length,d=s+f||1;return Math.round(s/d*100)})() }}%
                </el-tag>
              </div>
            </el-card>
          </template>
          <el-empty v-if="!batchHistory.jiraRows.length && !batchHistory.jiraLoading && !batchHistory.selectedBatches.length" description="请先选择批次并预览，确认后点击查询多维表格数据" :image-size="40"></el-empty>
        </el-card>
        <!-- 批次预览弹窗 -->
        <el-dialog v-model="batchHistory.previewVisible" title="批次预览" width="70%" destroy-on-close>
          <div style="margin-bottom:10px;font-size:13px;color:#606266">
            <el-tag size="small" type="info">{{ batchHistory.previewBatchLabel }}</el-tag>
            <span style="margin-left:10px">共 {{ batchHistory.previewRows.length }} 条记录</span>
          </div>
          <el-table :data="batchHistory.previewRows" size="small" stripe max-height="360" v-loading="batchHistory.previewLoading">
            <el-table-column type="index" label="#" width="45"></el-table-column>
            <el-table-column prop="jira号" label="Jira号" width="130"></el-table-column>
            <el-table-column prop="执行结果" label="结果" width="80">
              <template #default="{row}"><el-tag :type="row['执行结果']==='成功'?'success':'danger'" size="small">{{ row['执行结果'] }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="报告长度" label="报告长度" width="90"></el-table-column>
            <el-table-column prop="触发时间" label="触发时间" width="160" show-overflow-tooltip></el-table-column>
            <el-table-column prop="执行时间" label="执行时间" width="160" show-overflow-tooltip></el-table-column>
            <el-table-column prop="备注" label="备注" min-width="160" show-overflow-tooltip></el-table-column>
          </el-table>
          <template #footer>
            <el-button size="small" @click="batchHistory.previewVisible=false">关闭</el-button>
            <el-button type="primary" size="small" :loading="batchHistory.jiraLoading" @click="batchHistory.previewVisible=false;loadHistoryJira()">确认并查询多维表格数据</el-button>
          </template>
        </el-dialog>
      </el-tab-pane>
    </el-tabs>

    <!-- 修正建议编辑对话框 -->
    <el-dialog v-model="troubleshoot.correctionEditor.visible" title="编辑修正建议" width="480px" destroy-on-close>
      <div style="margin-bottom:12px"><el-tag type="info" size="small">{{ troubleshoot.correctionEditor.row?.bugid }}</el-tag></div>
      <el-form label-width="100px">
        <el-form-item label="正确时间">
          <el-date-picker v-model="troubleshoot.correctionEditor.time" type="datetime" placeholder="选择日期时间（可选）"
            format="YYYY-MM-DD HH:mm:ss" value-format="YYYY-MM-DD HH:mm:ss"
            @change="onCorrectionTimeChange" style="width:100%"></el-date-picker>
        </el-form-item>
        <el-form-item label="人工审核原因">
          <el-autocomplete v-model="troubleshoot.correctionEditor.humanReason"
            :fetch-suggestions="matchHumanReasonCategories"
            placeholder="输入关键词自动匹配归类（如：无gmlogger、重复、超时）"
            style="width:100%" clearable
            @select="(item) => { troubleshoot.correctionEditor.humanReason = item.value; troubleshoot.correctionEditor.matchedCategory = item.category; }">
            <template #default="{ item }">
              <span>{{ item.value }}</span>
              <el-tag size="small" type="info" style="margin-left:8px">{{ item.category }}</el-tag>
            </template>
          </el-autocomplete>
          <div v-if="troubleshoot.correctionEditor.matchedCategory" style="margin-top:4px;font-size:12px;color:#67c23a">
            ✓ 匹配归类：{{ troubleshoot.correctionEditor.matchedCategory }}
          </div>
        </el-form-item>
        <el-form-item label="备注说明">
          <el-input v-model="troubleshoot.correctionEditor.note" type="textarea" :rows="3" placeholder="输入修正说明（可选）"></el-input>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="troubleshoot.correctionEditor.visible=false">取消</el-button>
        <el-button size="small" type="primary" :loading="troubleshoot.correctionEditor.saving" @click="saveSuggestion">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script lang="ts">
// @ts-nocheck
import { ElMessage, ElMessageBox } from 'element-plus';
import { api, diagCategoryTagType } from '../composables/utils';
export default {
  name: 'TroubleshootPanel',
  components: {},
  data() {
    return {
      troubleshootTab: 'batch',
      troubleshoot: {
        afterTime: '', resultFilter: '失败', sourceFilter: '', dedup: true, noManualReview: false,
        querying: false, records: [], successRecords: [], queryingSuccess: false, successSearched: false,
        diagRunning: false, diagLoadingMap: {}, diagResults: [], categoryFilter: '',
        skipCategoryFilter: '', editingSkipBugid: '', editingSkipReason: '',
        writingReview: false, sendingToDeveloper: false, exportingTriggerIssues: false, batchApplyingTime: false, onlyEmptyReview: false,
        stopFlag: false, abortController: null, skipVideoCache: false, execOnlyEmptyReview: false, preClassifying: false,
        correctionEditor: { visible: false, row: null, time: '', note: '', humanReason: '', matchedCategory: '', saving: false },
        rootCauses: {},
      },
      singleTroubleshoot: {
        keyword: '', searching: false, searchMsg: '', searchError: false,
        rows: [], selectedRow: null, diagnosing: false, diagResult: null,
      },
      batchHistory: {
        batchList: [] as any[], batchListLoading: false, selectedBatches: [] as string[],
        previewVisible: false, previewRows: [] as any[], previewLoading: false, previewBatchLabel: '',
        selectedBatchUrl: '', assessResult: null as any, assessing: false,
        jiraRows: [] as any[], jiraLoading: false,
        resultFilter: '', keyword: '', manualEmpty: false, sourceFilter: '',
      },
    };
  },
  methods: {
    diagCategoryTagType,
    getMainEntries(row) {
      const bugid = row['jira号'] || row['bugid'];
      if (!bugid) return '-';
      const diag = this.troubleshoot.diagResults.find(r => r.bugid === bugid);
      if (diag && diag.main_entries && diag.main_entries.length > 0) return diag.main_entries.join(', ');
      return '-';
    },
    async runTroubleshootQuery() {
      if (!this.troubleshoot.afterTime) { ElMessage.warning('请选择排查时间'); return; }
      this.troubleshoot.querying = true;
      this.troubleshoot.diagResults = [];
      this.troubleshoot.successRecords = [];
      this.troubleshoot.successSearched = false;
      try {
        const body = await api('/api/troubleshoot/records', {
          method: 'POST',
          body: JSON.stringify({
            after_time: this.troubleshoot.afterTime, result_filter: this.troubleshoot.resultFilter,
            source_filter: this.troubleshoot.sourceFilter, dedup: this.troubleshoot.dedup,
            no_manual_review: this.troubleshoot.noManualReview,
          })
        });
        this.troubleshoot.records = (body.data && body.data.rows) || [];
        ElMessage.success(body.message || `查询到 ${this.troubleshoot.records.length} 条`);
      } catch (e) { /* 已由 api() 提示 */ }
      finally { this.troubleshoot.querying = false; }
    },
    async querySuccessRecords() {
      const failedJiras = [...new Set(this.troubleshoot.records.map(r => r['jira号']).filter(Boolean))];
      if (!failedJiras.length) { ElMessage.warning('无失败记录'); return; }
      this.troubleshoot.queryingSuccess = true;
      this.troubleshoot.successRecords = [];
      this.troubleshoot.successSearched = false;
      try {
        const body = await api('/api/troubleshoot/records', {
          method: 'POST',
          body: JSON.stringify({ after_time: this.troubleshoot.afterTime, result_filter: '成功', source_filter: '', dedup: false, no_manual_review: false })
        });
        const allSuccess = (body.data && body.data.rows) || [];
        const failSet = new Set(failedJiras);
        const matched = allSuccess.filter(r => failSet.has(r['jira号']));
        this.troubleshoot.successRecords = matched;
        this.troubleshoot.successSearched = true;
        ElMessage[matched.length ? 'success' : 'info'](
          matched.length ? `找到 ${matched.length} 条成功记录（涉及 ${new Set(matched.map(r => r['jira号'])).size} 个 Jira 号）` : '未找到对应成功记录');
      } catch (e) { /* 已由 api() 提示 */ }
      finally { this.troubleshoot.queryingSuccess = false; }
    },
    async _diagnoseRow(row, force = false, skipVideoCache = false) {
      const bugid = row['jira号'];
      this.troubleshoot.diagLoadingMap = { ...this.troubleshoot.diagLoadingMap, [bugid]: true };
      try {
        let signal;
        const timeoutSig = (() => { try { return AbortSignal.timeout(300000); } catch (_) { return null; } })();
        const abortSig = this.troubleshoot.abortController ? this.troubleshoot.abortController.signal : null;
        if (abortSig && timeoutSig) {
          try { signal = (AbortSignal as any).any([abortSig, timeoutSig]); } catch (_) { signal = abortSig; }
        } else { signal = abortSig || timeoutSig || undefined; }
        const body = await api('/api/troubleshoot/diagnose', {
          method: 'POST',
          body: JSON.stringify({ bugid, err_msg: row['错误信息'] || '', problem_time: row['分析问题时间'] || '', done_time: row['分析完成时间'] || '', force, skip_video_cache: skipVideoCache }),
          signal,
        });
        const d = body.data || {};
        const idx = this.troubleshoot.diagResults.findIndex(r => r.bugid === bugid);
        if (idx >= 0) { this.troubleshoot.diagResults.splice(idx, 1, d); }
        else { this.troubleshoot.diagResults.push(d); }
      } catch (e) {
        if (e && e.name === 'TimeoutError') ElMessage.warning(`${bugid} 诊断超时，请稍后重试`);
        const idx = this.troubleshoot.diagResults.findIndex(r => r.bugid === bugid);
        const fallback = { bugid, category: '诊断超时/异常', problem_time: row['分析问题时间'] || '',
          archive_files: [], detail: `诊断请求异常: ${e?.message || e?.name || '未知错误'}`,
          verify_status: '', suggested_time: '', report: {}, done_time: row['分析完成时间'] || '' };
        if (idx >= 0) { this.troubleshoot.diagResults.splice(idx, 1, fallback); }
        else { this.troubleshoot.diagResults.push(fallback); }
      }
      finally { this.troubleshoot.diagLoadingMap = { ...this.troubleshoot.diagLoadingMap, [bugid]: false }; }
    },
    async diagnoseOne(row) { await this._diagnoseRow(row); },
    async searchSingleTroubleshoot() {
      const st = this.singleTroubleshoot;
      if (!st.keyword.trim()) return ElMessage.warning('请输入 Jira 号');
      st.searching = true; st.searchMsg = ''; st.searchError = false; st.rows = []; st.diagResult = null;
      try {
        const body = await api('/api/troubleshoot/search_jira', {
          method: 'POST', body: JSON.stringify({ keyword: st.keyword.trim() })
        });
        st.rows = (body.data && body.data.rows) || [];
        st.searchMsg = body.message || `找到 ${st.rows.length} 条`;
        if (!st.rows.length) st.searchError = true;
      } catch (e) { st.searchMsg = '查询失败: ' + e.message; st.searchError = true; }
      finally { st.searching = false; }
    },
    onSingleTroubleshootSelect(row) { this.singleTroubleshoot.selectedRow = row; },
    async diagnoseSingleTroubleshoot(row) {
      const st = this.singleTroubleshoot;
      st.diagnosing = true; st.diagResult = null;
      try {
        const body = await api('/api/troubleshoot/diagnose', {
          method: 'POST',
          body: JSON.stringify({ bugid: row['jira号'], err_msg: row['错误信息'] || '', problem_time: row['分析问题时间'] || '', done_time: row['分析完成时间'] || '' })
        });
        st.diagResult = body.data || {};
        ElMessage.success(`${row['jira号']} 诊断完成：${st.diagResult.category || ''}`);
      } catch (e) { /* 已提示 */ }
      finally { st.diagnosing = false; }
    },
    async applySuggestedTime(row) {
      if (!row?.bugid || !row?.suggested_time) {
        return ElMessage.warning('缺少 bugid 或建议时间');
      }
      try {
        const body = await api('/api/trigger_time/update', {
          method: 'POST', body: JSON.stringify({ bugid: row.bugid, new_time: row.suggested_time })
        });
        ElMessage.success(`${row.bugid} 触发时间已替换为 ${row.suggested_time}（${body.message || '已保存'}）`);
        row.verify_status = 'corrected';
        row.correction_time = row.suggested_time;
      } catch (e) { /* 已提示 */ }
    },
    getApplicableCorrectionCount() {
      return this.troubleshoot.diagResults.filter(
        r => r.verify_status === 'success' && r.suggested_time && r.suggested_time !== r.problem_time
      ).length;
    },
    async batchApplyCorrectionTimes() {
      const targets = this.troubleshoot.diagResults.filter(
        r => r.verify_status === 'success' && r.suggested_time && r.suggested_time !== r.problem_time
      );
      if (!targets.length) return ElMessage.warning('无待应用的修正时间');
      this.troubleshoot.batchApplyingTime = true;
      try {
        const items = targets.map(r => ({ bugid: r.bugid, new_time: r.suggested_time }));
        const body = await api('/api/trigger_time/batch_update', {
          method: 'POST', body: JSON.stringify({ items })
        });
        targets.forEach(r => { r.verify_status = 'corrected'; r.correction_time = r.suggested_time; });
        ElMessage.success(body.message || `已应用 ${targets.length} 条修正时间`);
      } catch (e) { /* 已提示 */ }
      finally { this.troubleshoot.batchApplyingTime = false; }
    },
    openSuggestionEditor(row) {
      const ed = this.troubleshoot.correctionEditor;
      ed.row = row;
      ed.time = row.correction_time || row.suggested_time || '';
      ed.note = row.correction_note || '';
      ed.humanReason = (row.report && row.report.human_reason) || '';
      ed.matchedCategory = (row.report && row.report.final_category) || row.category || '';
      ed.saving = false;
      ed.visible = true;
    },
    matchHumanReasonCategories(queryStr, cb) {
      const allOptions = [
        { value: '无gmlogger文件', category: '无gmlogger文件', keywords: ['无gmlogger', 'gmlogger'] },
        { value: '无gmlogger日志文件', category: '无gmlogger文件', keywords: ['无gmlogger日志'] },
        { value: '日志文件已损坏', category: '日志过滤逻辑', keywords: ['损坏', '已损坏'] },
        { value: '问题重复，无需排查', category: '问题重复', keywords: ['重复', '问题重复'] },
        { value: '问题未复现', category: '问题未复现', keywords: ['未复现', '问题未复现', '不复现'] },
        { value: '触发时间无日志', category: '触发时间问题', keywords: ['触发时间', '时间无日志', '时间问题'] },
        { value: '该Jira无日志附件，属于正常处理机制', category: '无gmlogger文件', keywords: ['无日志', '无附件', '无日志附件', '正常处理'] },
        { value: 'JIRA 分析任务执行超时', category: '分析任务执行超时，跳过排查', keywords: ['超时', '执行超时', '任务超时'] },
        { value: '服务有报错', category: '服务运行问题', keywords: ['服务', '服务报错', '服务有报错'] },
        { value: '接口无响应，待源泉排查', category: '接口响应问题', keywords: ['接口', '无响应', '连接失败'] },
        { value: '疑似接口拥堵导致的接口无响应，待源泉排查', category: '接口并发响应问题', keywords: ['拥堵', '并发', 'adjudication'] },
        { value: '疑似接口拥堵导致的手动中断', category: '接口并发响应问题', keywords: ['拥堵', '手动中断', '手动中断'] },
        { value: '时间添加为', category: '触发时间问题', keywords: ['时间添加', '修改时间', '替换时间'] },
        { value: '无法自动归类，待人工排查', category: '待人工排查', keywords: ['人工', '待人工', '无法归类'] },
        { value: '解压问题，待排查', category: '解压问题', keywords: ['解压', '解压问题', '待排查'] },
      ];
      if (!queryStr) return cb(allOptions.map(o => ({ value: o.value, category: o.category })));
      const lower = queryStr.toLowerCase();
      const matched = allOptions.filter(o =>
        o.keywords.some(k => k.toLowerCase().includes(lower)) || o.value.toLowerCase().includes(lower)
      );
      cb(matched.length ? matched.map(o => ({ value: o.value, category: o.category })) : allOptions.map(o => ({ value: o.value, category: o.category })));
    },
    onCorrectionTimeChange(val) {
      // 时间变更时实时更新人工审核结果
      const ed = this.troubleshoot.correctionEditor;
      if (val) {
        ed.humanReason = `时间添加为${val}`;
      }
    },
    async saveSuggestion() {
      const ed = this.troubleshoot.correctionEditor;
      if (!ed.row || ed.saving) return;
      if (!ed.row.bugid) return ElMessage.warning('缺少 bugid');
      ed.saving = true;
      const row = ed.row;
      try {
        if (ed.time) {
          const timeStr = typeof ed.time === 'object' ? new Date(ed.time).toISOString().replace('T', ' ').slice(0, 19) : String(ed.time);
          await api('/api/trigger_time/update', {
            method: 'POST', body: JSON.stringify({ bugid: row.bugid, new_time: timeStr })
          });
          row.correction_time = timeStr;
          row.verify_status = 'corrected';
          // 输入时间后始终自动填充人工审核结果
          if (!row.report) row.report = {};
          row.report.human_reason = `时间添加为${timeStr}`;
          ed.humanReason = row.report.human_reason;
        }
        row.correction_note = ed.note;
        if (ed.humanReason) {
          if (!row.report) row.report = {};
          let reason = ed.humanReason;
          if (reason === '时间添加为' && ed.time) {
            const timeStr = typeof ed.time === 'object' ? new Date(ed.time).toISOString().replace('T', ' ').slice(0, 19) : String(ed.time);
            reason = `时间添加为${timeStr}`;
          }
          row.report.human_reason = reason;
          if (ed.matchedCategory) { row.report.final_category = ed.matchedCategory; row.category = ed.matchedCategory; }
          if (!ed.time) row.verify_status = 'corrected';
        }
        const cacheUpdate = { bugid: row.bugid };
        if (ed.time) cacheUpdate.correction_time = row.correction_time;
        if (ed.note !== undefined) cacheUpdate.correction_note = ed.note;
        if (row.report && row.report.human_reason) cacheUpdate.human_reason = row.report.human_reason;
        if (ed.matchedCategory) cacheUpdate.category = ed.matchedCategory;
        await api('/api/troubleshoot/update_cache', { method: 'POST', body: JSON.stringify(cacheUpdate) });
        ed.visible = false;
        ElMessage.success(`${row.bugid} 修正建议已保存`);
      } catch (e) { ElMessage.error('保存失败'); }
      finally { ed.saving = false; }
    },
    stopDiagnose() {
      this.troubleshoot.stopFlag = true;
      if (this.troubleshoot.abortController) this.troubleshoot.abortController.abort();
      api('/api/troubleshoot/cancel_diag', {
        method: 'POST', body: JSON.stringify({ bugids: [] })
      }).catch(() => {});
      ElMessage.info('正在停止诊断，已完成的结果保留');
    },
    async diagnoseAllFailed() {
      const targets = this.troubleshoot.records.filter(r => r['分析结果'] === '失败');
      if (!targets.length) { ElMessage.warning('无可诊断的记录（需分析结果为失败）'); return; }
      // jira号去重，同一 bug 仅诊断一次
      const seen = new Set();
      const uniqueTargets = [];
      for (const r of targets) {
        const id = r['jira号'];
        if (id && !seen.has(id)) { seen.add(id); uniqueTargets.push(r); }
      }
      const dupCount = targets.length - uniqueTargets.length;
      if (dupCount) console.log(`批量诊断去重: ${targets.length} 条 → ${uniqueTargets.length} 条`);
      this.troubleshoot.diagRunning = true;
      this.troubleshoot.stopFlag = false;
      this.troubleshoot.abortController = new AbortController();
      this.troubleshoot.diagResults = [];
      this.troubleshoot.rootCauses = {};
      // 阶段一：批量预归类（快速筛出无需分析的记录）
      try {
        const preBody = await api('/api/troubleshoot/batch_pre_classify', {
          method: 'POST', body: JSON.stringify({
            records: uniqueTargets.map(r => ({
              bugid: r['jira号'], err_msg: r['错误信息'] || '',
              human_review: r['人工审核结果'] || '', done_time: r['分析完成时间'] || '',
              problem_time: r['分析问题时间'] || '',
            })),
          }),
        });
        const preData = preBody.data || {};
        const skipRecords = preData.skip || [];
        const needRecords = preData.need_analysis || [];
        // 将预归类结果立即加入 diagResults（跳过表马上展示）
        for (const s of skipRecords) {
          this.troubleshoot.diagResults.push({
            bugid: s.bugid, category: s.category, done_time: s.done_time,
            problem_time: s.problem_time, detail: s.detail || '',
            err_msg: s.err_msg || '', archive_files: [], verify_status: '',
            suggested_time: '', report: s.report || {}, needs_analysis: false,
          });
        }
        if (skipRecords.length) {
          ElMessage.info(`阶段一：已筛出 ${skipRecords.length} 条自动归类记录`);
        }
        // 阶段二：仅对剩余需分析的记录执行完整诊断
        if (this.troubleshoot.stopFlag) { this.troubleshoot.diagRunning = false; return; }
        const needBugids = new Set(needRecords.map(r => r.bugid));
        const queue = uniqueTargets.filter(r => needBugids.has(r['jira号']));
        const worker = async () => {
          while (queue.length && !this.troubleshoot.stopFlag) { await this._diagnoseRow(queue.shift()); }
        };
        await Promise.all([worker(), worker(), worker()]);
      } catch (e) {
        console.error('批量诊断异常:', e);
      }
      this.troubleshoot.diagRunning = false;
      if (this.troubleshoot.stopFlag) {
        ElMessage.warning(`已停止诊断：完成 ${this.troubleshoot.diagResults.length} 条`);
      } else {
        const skipCount = this.troubleshoot.diagResults.filter(r => !r.needs_analysis).length;
        const analysisCount = this.troubleshoot.diagResults.filter(r => r.needs_analysis).length;
        ElMessage.success(`诊断完成: 自动归类 ${skipCount} 条 + 需分析 ${analysisCount} 条`);
      }
      if (this.troubleshoot.diagResults.length) await this.loadRootCauses();
    },
    async loadRootCauses() {
      const bugids = this.troubleshoot.diagResults.map(r => r.bugid).filter(Boolean);
      if (!bugids.length) return;
      try {
        const resp = await api('/api/timestudy/root-causes', { method: 'POST', body: JSON.stringify({ bugids }) });
        if (resp && resp.data) this.troubleshoot.rootCauses = resp.data;
      } catch (e) { console.warn('加载根因失败:', e); }
    },
    getTroubleshootFailedCount() {
      return this.troubleshoot.records.filter(r => r['分析结果'] === '失败').length;
    },
    // 跳过排查的记录（needs_analysis === false）
    getSkipDiagResults() {
      return (this.troubleshoot.diagResults || []).filter(r => r.needs_analysis === false);
    },
    // 按错误类型筛选后的跳过记录
    getSkipCategories() {
      return [...new Set(this.getSkipDiagResults().map(r => r.category).filter(Boolean))];
    },
    getFilteredSkipResults() {
      const rows = this.getSkipDiagResults();
      if (!this.troubleshoot.skipCategoryFilter) return rows;
      return rows.filter(r => r.category === this.troubleshoot.skipCategoryFilter);
    },
    startEditSkipHuman(row) {
      this.troubleshoot.editingSkipBugid = row.bugid;
      this.troubleshoot.editingSkipReason = (row.report && row.report.human_reason) || '';
    },
    saveSkipHumanReason(row) {
      if (!row.report) row.report = {};
      row.report.human_reason = this.troubleshoot.editingSkipReason;
      this.troubleshoot.editingSkipBugid = '';
    },
    // 需深入分析的记录（needs_analysis !== false）
    getAnalysisDiagResults() {
      return (this.troubleshoot.diagResults || []).filter(r => r.needs_analysis !== false);
    },
    // 批量预归类：快速分类，跳过无需深度分析的记录
    async preClassifyRecords() {
      const targets = this.troubleshoot.records.filter(r => r['分析结果'] === '失败');
      if (!targets.length) return ElMessage.warning('无失败记录');
      this.troubleshoot.preClassifying = true;
      try {
        const records = targets.map(r => ({
          bugid: r['jira号'], err_msg: r['错误信息'] || '',
          human_review: r['人工审核结果'] || '', done_time: r['分析完成时间'] || '',
          problem_time: r['分析问题时间'] || '',
        }));
        const body = await api('/api/troubleshoot/batch_pre_classify', {
          method: 'POST', body: JSON.stringify({ records })
        });
        const data = body.data || {};
        const skipList = data.skip || [];
        const needList = data.need_analysis || [];
        // 将跳过和需分析的结果合并到 diagResults
        this.troubleshoot.diagResults = [...skipList, ...needList];
        ElMessage.success(body.message || `预归类完成: 跳过 ${skipList.length} 条, 需分析 ${needList.length} 条`);
      } catch (e) { /* 已提示 */ }
      finally { this.troubleshoot.preClassifying = false; }
    },
    // 发送给开发者（飞书机器人通知）
    async sendToDeveloper() {
      const skipItems = this.getFilteredSkipResults();
      if (!skipItems.length) return ElMessage.warning('无跳过排查的记录');
      try {
        await ElMessageBox.confirm(
          `将发送 ${skipItems.length} 条待后端排查记录给开发者（飞书机器人通知），确认？`,
          '确认发送', { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning' });
      } catch { return; }
      this.troubleshoot.sendingToDeveloper = true;
      try {
        const records = skipItems.map(r => ({
          bugid: r.bugid, done_time: r.done_time || '', err_msg: r.err_msg || '',
          category: r.category || '',
        }));
        const body = await api('/api/troubleshoot/send_to_developer', {
          method: 'POST', body: JSON.stringify({ records })
        });
        ElMessage.success(body.message || '已发送给开发者');
      } catch (e) { ElMessage.error('发送失败: ' + (e.message || e)); }
      finally { this.troubleshoot.sendingToDeveloper = false; }
    },
    // 批量写入跳过排查记录的人工审核结果（仅写入当前筛选后的）
    async batchWriteSkipReview() {
      const items = this.getFilteredSkipResults()
        .filter(r => r.report && r.report.human_reason)
        .map(r => ({ bugid: r.bugid, done_time: r.done_time, human_reason: r.report.human_reason }));
      if (!items.length) return ElMessage.warning('无有人工分析失败原因的跳过记录');
      try {
        await ElMessageBox.confirm(
          `将写入 ${items.length} 条人工审核结果到多维表格，确认？`,
          '确认写入', { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning' });
      } catch { return; }
      this.troubleshoot.writingReview = true;
      try {
        const body = await api('/api/troubleshoot/batch_write_review', {
          method: 'POST', body: JSON.stringify({ items, only_empty_review: this.troubleshoot.onlyEmptyReview })
        });
        ElMessage.success(body.message);
      } catch (e) { ElMessage.error('写入失败: ' + (e.message || e)); }
      finally { this.troubleshoot.writingReview = false; }
    },
    getManualReviewCount() {
      return (this.troubleshoot.diagResults || []).filter(r => r.verify_status === 'manual').length;
    },
    async rerunManualReview() {
      const manuals = this.troubleshoot.diagResults.filter(r => r.verify_status === 'manual');
      if (!manuals.length) { ElMessage.warning('无待人工审核的记录'); return; }
      this.troubleshoot.diagRunning = true;
      this.troubleshoot.stopFlag = false;
      this.troubleshoot.abortController = new AbortController();
      const queue = [...manuals];
      const worker = async () => {
        while (queue.length && !this.troubleshoot.stopFlag) {
          const d = queue.shift();
          const origRow = this.troubleshoot.records.find(r => r['jira号'] === d.bugid);
          const row = origRow || { 'jira号': d.bugid, '错误信息': '', '分析问题时间': d.problem_time || '', '分析完成时间': d.done_time || '' };
          await this._diagnoseRow(row, true, this.troubleshoot.skipVideoCache);
        }
      };
      await Promise.all([worker(), worker(), worker()]);
      this.troubleshoot.diagRunning = false;
      if (this.troubleshoot.stopFlag) { ElMessage.warning(`已停止，剩余 ${queue.length} 条未执行`); }
      else { ElMessage.success(`重新执行完成，共 ${manuals.length} 条`); }
    },
    getTroubleshootCategories() {
      const cats = [...new Set(this.troubleshoot.diagResults.map(r => r.category).filter(Boolean))];
      cats.unshift('待人工审核');
      return cats;
    },
    getFilteredDiagResults() {
      const rows = this.troubleshoot.diagResults || [];
      const sorted = [...rows].sort((a, b) => {
        const ta = a.done_time ? new Date(a.done_time.replace(/-/g, '/')).getTime() : 0;
        const tb = b.done_time ? new Date(b.done_time.replace(/-/g, '/')).getTime() : 0;
        return ta - tb;
      });
      if (!this.troubleshoot.categoryFilter) return sorted;
      if (this.troubleshoot.categoryFilter === '待人工审核') {
        return sorted.filter(r => r.category === '触发时间问题' && r.verify_status === 'manual');
      }
      return sorted.filter(r => r.category === this.troubleshoot.categoryFilter);
    },
    getDiagEntries(row) {
      const out = [];
      for (const arc of (row.archive_files || [])) {
        const matched = new Set(arc.matched_entries || []);
        for (const name of (arc.entries || [])) {
          out.push({ name: name.split(/[\\/]/).pop(), matched: matched.has(name) });
        }
      }
      return out;
    },
    async copyReport(row) {
      if (!row.report) { ElMessage.warning('暂无报告内容'); return; }
      const lines = [];
      if (row.correction_time) lines.push(`- 修正触发时间：${row.correction_time}`);
      lines.push(`- AI分析失败原因：${row.report.ai_reason || '无'}`, `- 人工分析失败原因：${row.report.human_reason || '无'}`);
      if (row.report.retry_result) lines.push(`- 重试结果：${row.report.retry_result}`);
      lines.push(`- 问题归类：${row.report.final_category || row.category}`);
      const text = `### ${row.bugid}\n${lines.join('\n')}`;
      try { await navigator.clipboard.writeText(text); ElMessage.success(`${row.bugid} 报告已复制`); }
      catch (e) { ElMessage.error('复制失败：' + (e.message || e)); }
    },
    async copyAllReports() {
      const rows = this.getFilteredDiagResults() || [];
      if (!rows.length) { ElMessage.warning('无报告内容'); return; }
      const parts = [];
      for (const row of rows) {
        if (!row.report) continue;
        const lines = [];
        if (row.correction_time) lines.push(`- 修正触发时间：${row.correction_time}`);
        lines.push(`- AI分析失败原因：${row.report.ai_reason || '无'}`, `- 人工分析失败原因：${row.report.human_reason || '无'}`);
        if (row.report.retry_result) lines.push(`- 重试结果：${row.report.retry_result}`);
        lines.push(`- 问题归类：${row.report.final_category || row.category}`);
        parts.push(`### ${row.bugid}\n${lines.join('\n')}`);
      }
      if (!parts.length) { ElMessage.warning('无报告内容'); return; }
      try { await navigator.clipboard.writeText(parts.join('\n\n')); ElMessage.success(`已复制 ${parts.length} 条报告`); }
      catch (e) { ElMessage.error('复制失败：' + (e.message || e)); }
    },
    async batchWriteReview() {
      const items = this.getFilteredDiagResults()
        .filter(r => r.report && r.report.human_reason)
        .map(r => ({ bugid: r.bugid, done_time: r.done_time, human_reason: r.report.human_reason }));
      if (!items.length) return ElMessage.warning('无有人工分析失败原因的记录');
      const scope = this.troubleshoot.categoryFilter ? `筛选「${this.troubleshoot.categoryFilter}」中 ` : '';
      const emptyHint = this.troubleshoot.onlyEmptyReview ? '（仅写入人工审核结果为空的记录）' : '';
      try {
        await ElMessageBox.confirm(
          `将写入${scope}${items.length} 条人工审核结果到多维表格${emptyHint}，确认？`,
          '确认写入', { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning' });
      } catch { return; }
      this.troubleshoot.writingReview = true;
      try {
        const body = await api('/api/troubleshoot/batch_write_review', {
          method: 'POST', body: JSON.stringify({ items, only_empty_review: this.troubleshoot.onlyEmptyReview })
        });
        ElMessage.success(body.message);
      } catch (e) { ElMessage.error('写入失败: ' + (e.message || e)); }
      finally { this.troubleshoot.writingReview = false; }
    },
    async exportTriggerTimeIssues() {
      const triggerIssues = this.troubleshoot.diagResults
        .filter(r => r.category === '触发时间问题' || r.category?.includes('触发时间') || r.category?.includes('解压问题'))
        .filter(r => r.verify_status !== 'manual')
        .map(r => ({
          jira号: r.bugid, 问题归类: r.category, 分析完成时间: r.done_time || '',
          错误时间: r.problem_time || '', 诊断详情: r.detail || '',
          修正建议: r.suggested_time || '',
          人工审核结果: (r.report && r.report.human_reason) || r.correction_note || '',
        }));
      if (!triggerIssues.length) return ElMessage.warning('无触发时间问题记录');
      this.troubleshoot.exportingTriggerIssues = true;
      try {
        const body = await api('/api/troubleshoot/export_trigger_time_issues', {
          method: 'POST', body: JSON.stringify({ items: triggerIssues })
        });
        const d = body.data;
        let msg = `已生成触发时间问题表格: ${d.count} 条`;
        if (d.cloud_url) msg += `\n云端: ${d.cloud_url}`;
        ElMessage.success(msg);
      } catch (e) { ElMessage.error('生成失败: ' + (e.message || e)); }
      finally { this.troubleshoot.exportingTriggerIssues = false; }
    },
    // ===== 按批次排查 =====
    async loadHistoryBatches() {
      this.batchHistory.batchListLoading = true;
      try { const body = await api('/api/data/history_batches'); this.batchHistory.batchList = (body.data && body.data.batches) || []; }
      catch (_) {} finally { this.batchHistory.batchListLoading = false; }
    },
    onBatchHistorySelected() {
      this.batchHistory.jiraRows = []; this.batchHistory.resultFilter = ''; this.batchHistory.sourceFilter = ''; this.batchHistory.keyword = ''; this.batchHistory.manualEmpty = false;
      const first = this.batchHistory.selectedBatches.length ? this.batchHistory.batchList.find((b: any) => b.value === this.batchHistory.selectedBatches[0]) : null;
      this.batchHistory.selectedBatchUrl = first ? (first.url || '') : '';
    },
    async previewBatchHistory() {
      if (!this.batchHistory.selectedBatches.length) return;
      const batchToken = this.batchHistory.selectedBatches[0];
      this.batchHistory.previewLoading = true; this.batchHistory.previewVisible = true;
      const selected = this.batchHistory.batchList.find((b: any) => b.value === batchToken);
      this.batchHistory.previewBatchLabel = selected ? selected.name : batchToken;
      try { const body = await api(`/api/data/history_batch_preview?batch_token=${encodeURIComponent(batchToken)}`); this.batchHistory.previewRows = (body.data && body.data.rows) || []; }
      catch (_) { this.batchHistory.previewRows = []; } finally { this.batchHistory.previewLoading = false; }
    },
    async loadHistoryJira() {
      if (!this.batchHistory.selectedBatches.length) return;
      // 拼接多选 token/name/created
      const tokens: string[] = [], names: string[] = [], createds: string[] = [];
      for (const val of this.batchHistory.selectedBatches) {
        const sel = this.batchHistory.batchList.find((b: any) => b.value === val);
        tokens.push(val);
        names.push(sel ? (sel.name || '') : '');
        createds.push(sel ? (sel.created_time || '') : '');
      }
      this.batchHistory.jiraLoading = true;
      try {
        const body = await api(`/api/data/history_jira?batch_token=${encodeURIComponent(tokens.join(','))}&batch_name=${encodeURIComponent(names.join(','))}&batch_created=${encodeURIComponent(createds.join(','))}`);
        this.batchHistory.jiraRows = (body.data && body.data.rows) || [];
        ElMessage.success(body.message || `已加载 ${this.batchHistory.jiraRows.length} 条记录`);
      } catch (_) {} finally { this.batchHistory.jiraLoading = false; }
    },
    getFilteredBatchHistory() {
      let rows = this.batchHistory.jiraRows || [];
      const rf = this.batchHistory.resultFilter, sf = this.batchHistory.sourceFilter;
      const kw = (this.batchHistory.keyword || '').trim().toLowerCase(), me = this.batchHistory.manualEmpty;
      if (rf) rows = rows.filter((r: any) => (r['分析结果'] || '').trim() === rf);
      if (sf) rows = rows.filter((r: any) => (r['触发来源'] || '').trim() === sf);
      if (kw) rows = rows.filter((r: any) => (r['jira号'] || '').toLowerCase().includes(kw));
      if (me) rows = rows.filter((r: any) => !(r['人工审核结果'] || '').trim());
      return rows;
    },
    async runBatchHistoryAssess() {
      if (!this.batchHistory.jiraRows.length) return ElMessage.warning('请先查询多维表格数据');
      this.batchHistory.assessing = true; this.batchHistory.assessResult = null;
      try {
        const bugids = this.batchHistory.jiraRows.map((r: any) => r['jira号']).filter(Boolean);
        const selected = this.batchHistory.batchList.find((b: any) => b.value === this.batchHistory.selectedBatches[0]);
        const docCreatedTime = selected ? (selected.created_time || '') : '';
        const body = await api('/api/test/batch_quality_assess', { method: 'POST', body: JSON.stringify({ bugids, doc_created_time: docCreatedTime }) });
        if (body.data) { const a = (body.data as any).assessment; this.batchHistory.assessResult = a; ElMessage.success(`评估完成: ${a.total}个`); }
      } catch (e: any) { ElMessage.warning('质量评估失败: ' + e.message); } finally { this.batchHistory.assessing = false; }
    },
  },
};
</script>

<style scoped>
.troubleshoot-tabs { border-radius: 8px; }
.troubleshoot-tabs :deep(.el-tabs__content) { padding: 16px; overflow: visible; }
.diag-action-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 8px; padding-top: 8px; border-top: 1px dashed #dcdfe6; }
</style>
