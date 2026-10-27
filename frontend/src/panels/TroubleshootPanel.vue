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
      <div v-if="getFilteredDiagResults().length" style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:6px 0 8px">
        <el-tag size="small" type="info">本次诊断 {{ getFilteredDiagResults().length }} 条</el-tag>
        <el-tag size="small" type="success">正常 {{ diagTimeStats()['正常'] || 0 }}</el-tag>
        <el-tag size="small" type="warning">待确认 {{ diagTimeStats()['待确认'] || 0 }}</el-tag>
        <el-tag size="small" type="danger">不可用 {{ diagTimeStats()['不可用'] || 0 }}</el-tag>
        <el-tag size="small">无参考 {{ diagTimeStats()['无参考'] || 0 }}</el-tag>
      </div>
      <el-table :data="getFilteredDiagResults()" size="small" stripe border max-height="320" row-key="bugid">
        <el-table-column type="index" label="#" width="45"></el-table-column>
        <el-table-column prop="bugid" label="Jira号" width="120"></el-table-column>
        <el-table-column prop="category" label="问题归类" width="170">
          <template #default="{row}"><el-tag :type="diagCategoryTagType(row.category)" size="small">{{ row.category }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="done_time" label="分析完成时间" width="160"></el-table-column>
        <el-table-column label="当前触发时间" width="200">
          <template #default="{row}">
            <span>{{ row.problem_time || '-' }}</span>
            <el-tag v-if="row.time_check && row.time_check.current && row.time_check.current.status"
              size="mini" style="margin-left:6px" :type="timeStatusTagType(row.time_check.current.status)">
              {{ row.time_check.current.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="建议时间" width="190">
          <template #default="{row}">
            <span v-if="row.suggested_time">{{ row.suggested_time }}</span>
            <span v-else style="color:#c0c4cc">-</span>
            <span v-if="row.time_check && row.time_check.change_sec !== null && row.time_check.change_sec !== undefined"
              style="margin-left:6px;font-size:12px;color:#909399">{{ formatChange(row.time_check) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="抓包时间" width="150">
          <template #default="{row}">{{ (row.time_check && row.time_check.ref_time) || '-' }}</template>
        </el-table-column>
        <el-table-column label="差秒" width="90">
          <template #default="{row}">
            <span v-if="row.time_check && row.time_check.delta_sec !== null && row.time_check.delta_sec !== undefined"
              :style="{color: (row.time_check.status==='不可用') ? '#f56c6c' : ((row.time_check.status==='待确认') ? '#e6a23c' : '#67c23a')}">
              {{ formatDelta(row.time_check) }}
            </span>
            <span v-else style="color:#c0c4cc">-</span>
          </template>
        </el-table-column>
        <el-table-column label="时间判定" width="100">
          <template #default="{row}">
            <el-tag v-if="row.time_check && row.time_check.status" size="small" :type="timeStatusTagType(row.time_check.status)">
              {{ row.time_check.status }}
            </el-tag>
            <span v-else style="color:#c0c4cc">-</span>
          </template>
        </el-table-column>
        <el-table-column label="依据" width="150">
          <template #default="{row}">
            <el-popover v-if="row.time_check && row.time_check.evidence && row.time_check.evidence.length"
              placement="left" :width="380" trigger="click">
              <template #reference>
                <el-button size="small" link type="primary" style="font-size:12px">
                  {{ row.time_check.evidence.map(e => e['来源']).join(' / ') }}
                </el-button>
              </template>
              <el-table :data="row.time_check.evidence" size="mini" border>
                <el-table-column prop="来源" label="来源" width="110"></el-table-column>
                <el-table-column prop="时间" label="时间" width="150"></el-table-column>
                <el-table-column label="与抓包差" width="100">
                  <template #default="{row: ev}">{{ formatDelta({ delta_sec: ev['与抓包差秒'] }) }}</template>
                </el-table-column>
              </el-table>
            </el-popover>
            <span v-else style="color:#c0c4cc">-</span>
          </template>
        </el-table-column>
        <el-table-column label="诊断详情" min-width="260">
          <template #default="{row}">
            <div v-if="isNewDetailFormat(row.detail)" style="white-space:pre-wrap;line-height:1.4;font-size:13px">
              <div v-for="(line, idx) in row.detail.split('\n')" :key="idx" :style="getDetailLineStyle(line)">{{ line }}</div>
            </div>
            <span v-else>{{ row.detail }}</span>
          </template>
        </el-table-column>
        <el-table-column label="人工审核结果" min-width="200" show-overflow-tooltip>
          <template #default="{row}">
            <div v-if="troubleshoot.editingSkipBugid === row.bugid" style="display:flex;align-items:center;gap:4px">
              <el-input v-model="troubleshoot.editingSkipReason" size="small" placeholder="输入人工审核结果" autofocus
                @keyup.enter="saveSkipHumanReason(row)"></el-input>
              <el-button size="small" type="success" link @click="saveSkipHumanReason(row)">保存</el-button>
              <el-button size="small" type="info" link @click="troubleshoot.editingSkipBugid=''">取消</el-button>
            </div>
            <div v-else style="display:flex;align-items:center;gap:6px">
              <span v-if="row.report && row.report.human_reason"
                :style="isTimeDifferent(row) ? 'color:#67c23a;font-weight:600' : 'color:#e6a23c;font-weight:600'">{{ row.report.human_reason }}</span>
              <span v-else style="color:#c0c4cc">-</span>
              <el-button link size="small" type="primary" style="color:#909399;font-size:12px" @click="startEditSkipHuman(row)">编辑</el-button>
            </div>
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
        <p v-if="singleTroubleshoot.diagResult.verify_status && ['success', 'manual', 'corrected'].includes(singleTroubleshoot.diagResult.verify_status)">
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
        stopFlag: false, abortController: null, skipVideoCache: false, execOnlyEmptyReview: false, preClassifying: false, bootId: '',
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
    diagTimeStats() {
      const stat = { '正常': 0, '待确认': 0, '不可用': 0, '无参考': 0 };
      const rows = (this.troubleshoot && this.troubleshoot.diagResults) || [];
      const list = this.troubleshoot.categoryFilter
        ? rows.filter((r) => r.category === this.troubleshoot.categoryFilter) : rows;
      for (const r of list) {
        const s = r.time_check && r.time_check.status;
        if (s && stat[s] !== undefined) stat[s] += 1;
      }
      return stat;
    },
    formatChange(tc) {
      if (!tc) return '';
      const d = tc.change_sec;
      if (d === null || d === undefined) return '';
      if (d === 0) return '无变化';
      const sign = d > 0 ? '晚' : '早';
      const abs = Math.abs(d);
      const txt = abs >= 3600 ? `${(abs / 3600).toFixed(1)}h` : (abs >= 60 ? `${Math.round(abs / 60)}min` : `${abs}s`);
      return `${sign} ${txt}`;
    },
    formatDelta(tc) {
      if (!tc) return '-';
      const d = tc.delta_sec;
      if (d === null || d === undefined) return '-';
      const sign = d > 0 ? '晚' : (d < 0 ? '早' : '');
      const abs = Math.abs(d);
      const txt = abs >= 3600 ? `${(abs / 3600).toFixed(1)}h` : (abs >= 60 ? `${Math.round(abs / 60)}min` : `${abs}s`);
      return `${sign} ${txt}`.trim();
    },
    timeStatusTagType(s) {
      return s === '正常' ? 'success' : (s === '待确认' ? 'warning' : (s === '不可用' ? 'danger' : 'info'));
    },
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
      } catch (e) {
        // api() 默认 120s 超时，超时会抛 TimeoutError；此前这里静默忽略，
        // 用户只看到按钮转圈结束、没有结果也没有提示。
        if (e && (e.name === 'TimeoutError' || e.name === 'AbortError')) {
          ElMessage.warning('查询超时（超过 120 秒），多维表格数据量较大，请稍后重试');
        }
      }
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
    async ensureBootId() {
      // 批量诊断会带上服务启动标识；服务重启后旧页面/旧批量会被后端拒绝，
      // 避免“重启后浏览器里的上一轮排查继续下载附件、继续提取”。
      try {
        const b = await api('/api/troubleshoot/boot_id');
        this.troubleshoot.bootId = (b.data && b.data.boot_id) || '';
      } catch (e) { /* 取不到时留空，后端会拒绝并提示刷新 */ }
      return this.troubleshoot.bootId;
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
          body: JSON.stringify({ bugid, err_msg: row['错误信息'] || '', problem_time: row['分析问题时间'] || '', done_time: row['分析完成时间'] || '', force, skip_video_cache: skipVideoCache, boot_id: this.troubleshoot.bootId || '' }),
          signal,
        });
        const d = body.data || {};
        const idx = this.troubleshoot.diagResults.findIndex(r => r.bugid === bugid);
        if (idx >= 0) { this.troubleshoot.diagResults.splice(idx, 1, d); }
        else { this.troubleshoot.diagResults.push(d); }
      } catch (e) {
        const msg = String(e?.message || '');
        if (msg.includes('服务已重启')) {
          this.troubleshoot.stopFlag = true;
          ElMessage.warning('批量诊断已停止：服务已重启，请刷新页面后重新执行');
          return;
        }
        if (e?.name === 'TypeError' || /Failed to fetch|NetworkError|Load failed/i.test(msg)) {
          this.troubleshoot.stopFlag = true;
          ElMessage.error('诊断连接中断（服务可能已重启），批量诊断已停止');
          return;
        }
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
    async diagnoseOne(row) {
      await this.ensureBootId();
      await this._diagnoseRow(row);
    },
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
        await this.ensureBootId();
        const body = await api('/api/troubleshoot/diagnose', {
          method: 'POST',
          body: JSON.stringify({ bugid: row['jira号'], err_msg: row['错误信息'] || '', problem_time: row['分析问题时间'] || '', done_time: row['分析完成时间'] || '', boot_id: this.troubleshoot.bootId || '' })
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
    getApplicableCorrections() {
      return this.troubleshoot.diagResults.filter((r) => {
        if (r.verify_status !== 'success' || !r.suggested_time) return false;
        if (r.suggested_time === r.problem_time) return false;
        // 时间方向判定为“不可用”的不自动应用（避免把逻辑上不可能的时间写回去）
        if (r.time_check && r.time_check.status === '不可用') return false;
        return true;
      });
    },
    getApplicableCorrectionCount() {
      return this.getApplicableCorrections().length;
    },
    async batchApplyCorrectionTimes() {
      const targets = this.getApplicableCorrections();
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
      await this.ensureBootId();
      if (!this.troubleshoot.bootId) {
        this.troubleshoot.diagRunning = false;
        ElMessage.error('无法获取服务启动标识，请刷新页面后重试');
        return;
      }
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
        console.log('[预归类] 服务器返回:', JSON.stringify(preBody).substring(0, 500));
        const preData = preBody.data || {};
        const skipRecords = preData.skip || [];
        const needRecords = preData.need_analysis || [];
        console.log(`[预归类] skip=${skipRecords.length}, need=${needRecords.length}`, needRecords.map(r => r.bugid));
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
        // 已有缓存结果的直接展示，不重新诊断
        const cachedNeed = needRecords.filter(r => r.detail || (r.report && r.report.ai_reason));
        for (const c of cachedNeed) {
          this.troubleshoot.diagResults.push({
            bugid: c.bugid, category: c.category, done_time: c.done_time,
            problem_time: c.problem_time, detail: c.detail || '',
            err_msg: c.err_msg || '', archive_files: [], verify_status: c.verify_status || '',
            suggested_time: c.suggested_time || '', report: c.report || {}, needs_analysis: true,
          });
        }
        const cachedBugids = new Set(cachedNeed.map(r => r.bugid));
        const queue = uniqueTargets.filter(r => needBugids.has(r['jira号']) && !cachedBugids.has(r['jira号']));
        console.log(`[预归类] 诊断队列: cached=${cachedNeed.length}, pending=${queue.length}条`);
        const worker = async () => {
          while (queue.length && !this.troubleshoot.stopFlag) {
            await this._diagnoseRow(queue.shift());
            if (queue.length) await new Promise(r => setTimeout(r, 3000));
          }
        };
        await worker();
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
    // 判断诊断详情是否为新格式（4行简洁格式）
    isNewDetailFormat(detail) {
      if (!detail) return false;
      return detail.includes('评论提取到') || detail.includes('视频提取到') || detail.includes('图片提取到') || detail.includes('最终结果');
    },
    // 获取诊断详情行的样式
    getDetailLineStyle(line) {
      if (!line) return '';
      if (line.startsWith('评论提取到')) return 'color:#409eff';
      if (line.startsWith('视频提取到')) return 'color:#67c23a';
      if (line.startsWith('图片提取到')) return 'color:#e6a23c';
      if (line.startsWith('最终结果')) return 'font-weight:700;color:#303133';
      return '';
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
    // 需分析表格行样式：分析完成时间与错误时间不同，或已保存人工审核时标绿
    diagRowClassName({ row }) {
      const hasReview = row.report && row.report.human_reason;
      const timeDiff = row.done_time && row.problem_time && row.done_time !== row.problem_time;
      if (hasReview || timeDiff) return 'row-green';
      return '';
    },
    // 跳过排查表格行样式：已保存人工审核时标绿
    skipRowClassName({ row }) {
      if (row.report && row.report.human_reason) return 'row-green';
      return '';
    },
    // 判断人工审核结果中的时间与错误时间是否不同（比较完整日期+时间）
    isTimeDifferent(row) {
      if (!row.problem_time || !row.report || !row.report.human_reason) return false;
      const extractDateTime = (s) => {
        const m = s.match(/(\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2}(?::\d{2})?)/);
        return m ? m[1].replace(/\s+/g, ' ').trim() : '';
      };
      // 从人工审核结果文本中提取完整日期时间
      const humanDT = extractDateTime(row.report.human_reason);
      // 从错误时间中提取完整日期时间
      const problemDT = extractDateTime(row.problem_time);
      if (!humanDT || !problemDT) return false;
      return humanDT !== problemDT;
    },
    // 根据人工审核文本自动匹配分类
    classifyHumanReason(text) {
      if (!text) return '';
      const t = text.toLowerCase();
      // 触发时间问题
      if (/时间添加|时间异常|触发时间|未找到问题时间/.test(text)) return '触发时间问题';
      // 并发过多
      if (/并发过多|接口拥堵|手动中断|jira\s*server|过载|网络抖动/.test(t)) return '并发过多';
      // 分析任务执行超时
      if (/执行超时|jira.*分析任务.*超时/.test(t)) return '分析任务执行超时，跳过排查';
      // IT侧服务停止
      if (/模型调用失败|it侧服务停止|服务停止/.test(t)) return 'IT侧服务停止';
      // 服务关闭
      if (/服务关闭|服务有报错|server\s*disconnected/.test(t)) return '服务关闭';
      // 问题重复
      if (/问题重复|重复/.test(text)) return '问题重复';
      // 问题未复现
      if (/未复现|不复现/.test(text)) return '问题未复现';
      // 无gmlogger
      if (/无gmlogger|gmlogger文件已上传|无可下载.*日志/.test(t)) return '无gmlogger';
      // 解压问题
      if (/解压|unrar|rar5/.test(t)) return '解压问题';
      // 磁盘空间不足
      if (/磁盘空间不足|no space left/.test(t)) return '磁盘空间不足';
      // 分析can信号
      if (/分析can信号|can信号/.test(t)) return '分析can信号导致超时';
      // 待后端开发排查
      if (/待后端开发排查|httpstatuserror/.test(t)) return '待后端开发排查';
      // 日志待补充（仅人工标记：确认了触发时间但日志里没有对应时间段）
      if (/日志待补充|待补充日志|日志不全|日志里没有|没有.*日志|日志缺失/.test(text)) return '日志待补充';
      // 日志过滤逻辑
      if (/损坏|日志文件已损坏|日志过滤/.test(text)) return '日志过滤逻辑';
      return '';
    },
    async saveSkipHumanReason(row) {
      const newReason = this.troubleshoot.editingSkipReason;
      if (!newReason || !newReason.trim()) {
        ElMessage.warning('请输入审核内容');
        return;
      }
      // 替换整个 report 对象以强制触发 Vue 响应式更新
      const oldReport = row.report || {};
      row.report = { ...oldReport, human_reason: newReason };
      // 根据输入文本自动归类匹配
      const newCategory = this.classifyHumanReason(newReason);
      if (newCategory) {
        row.category = newCategory;
        // 更新 needs_analysis 标记：跳过类别设为 false
        const skipCats = new Set(['待后端开发排查', '磁盘空间不足', '服务关闭', '并发过多', 'IT侧服务停止',
          '接口连接问题', '接口响应问题', '分析任务执行超时，跳过排查', '问题重复', '问题未复现', '无gmlogger', '日志待补充']);
        row.needs_analysis = !skipCats.has(newCategory);
      }
      // 同步到本地诊断缓存，确保下次批量诊断能读到最新值
      try {
        await api('/api/troubleshoot/update_cache', {
          method: 'POST',
          body: JSON.stringify({
            bugid: row.bugid,
            human_reason: newReason,
            category: newCategory || undefined,
          }),
        });
        const catHint = newCategory ? `（归类：${newCategory}）` : '';
        ElMessage({ type: 'success', message: `${row.bugid} 保存成功${catHint}`, duration: 2500, showClose: true });
        // 触发时间问题：提取时间并写入云端触发时间表
        if (newCategory === '触发时间问题') {
          const timeMatch = newReason.match(/(\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2}(?::\d{2})?)/);
          if (timeMatch) {
            try {
              await api('/api/trigger_time/batch_update', {
                method: 'POST',
                body: JSON.stringify({ items: [{ bugid: row.bugid, new_time: timeMatch[1] }] }),
              });
              ElMessage({ type: 'success', message: `云端触发时间已更新为 ${timeMatch[1]}`, duration: 2000, showClose: true });
            } catch (e2) {
              ElMessage({ type: 'warning', message: `云端写入失败: ${e2.message || e2}`, duration: 3000, showClose: true });
            }
          }
        }
      } catch (e) {
        ElMessage({ type: 'warning', message: `${row.bugid} 本地已保存，但缓存同步失败: ${e.message || e}`, duration: 4000, showClose: true });
      } finally {
        // 保存完成后退出编辑状态
        this.troubleshoot.editingSkipBugid = '';
      }
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
      await this.ensureBootId();
      if (!this.troubleshoot.bootId) {
        this.troubleshoot.diagRunning = false;
        ElMessage.error('无法获取服务启动标识，请刷新页面后重试');
        return;
      }
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
      // 只返回“需要深入分析”的记录，根据类别筛选
      let rows = (this.troubleshoot.diagResults || []).filter(r => r.needs_analysis !== false);
      // 仅人工审核结果为空：过滤掉已有人工审核结果的记录
      if (this.troubleshoot.onlyEmptyReview) {
        rows = rows.filter(r => !r.existing_review);
      }
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
:deep(.row-green td) { background-color: transparent !important; }
</style>
