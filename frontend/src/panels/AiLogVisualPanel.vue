<template>
  <div class="test-panel">
    <div class="section-title">AI日志分析自学习内容可视化</div>
    <el-alert type="info" :closable="false" style="margin-bottom:12px">
      读取AI日志分析服务的日志或上传本地日志文件/压缩包，按 Jira 号过滤并按分析轮次分组展示每轮的调用细节
    </el-alert>
    <el-card shadow="never" style="margin-bottom:12px">
      <template #header>① 查询条件</template>
      <el-radio-group v-model="aiLogVisual.source" style="margin-bottom:12px">
        <el-radio-button value="remote">远程服务日志</el-radio-button>
        <el-radio-button value="local">本地文件上传</el-radio-button>
      </el-radio-group>
      <el-form inline>
        <el-form-item label="Jira号">
          <el-input v-model="aiLogVisual.jiraId" placeholder="输入 Jira 号（如 VCU-123456）" clearable @keyup.enter="readAiLogVisual" style="width:260px"></el-input>
        </el-form-item>
        <template v-if="aiLogVisual.source === 'remote'">
          <el-form-item label="日志类型">
            <el-select v-model="aiLogVisual.logName" style="width:100px">
              <el-option label="全部" value="all"></el-option>
              <el-option label="应用" value="app"></el-option>
              <el-option label="性能" value="perf"></el-option>
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="aiLogVisual.loading" @click="readAiLogVisual">读取日志</el-button>
          </el-form-item>
        </template>
        <template v-else>
          <el-form-item>
            <el-upload :auto-upload="false" :show-file-list="false" :on-change="(f) => handleAiLogFileSelect(f)"
              accept=".log,.txt,.md,.csv,.zip,.tar.gz,.tgz,.gz">
              <el-button type="primary" :loading="aiLogVisual.loading">选择文件</el-button>
            </el-upload>
          </el-form-item>
          <el-form-item v-if="aiLogVisual.uploadFileName">
            <el-tag type="info" closable @close="aiLogVisual.uploadFileName='';aiLogVisual.uploadFile=null">{{ aiLogVisual.uploadFileName }}</el-tag>
            <el-button type="success" :loading="aiLogVisual.loading" :disabled="!aiLogVisual.uploadFile || !aiLogVisual.jiraId" @click="uploadAiLogVisual" style="margin-left:8px">解析</el-button>
          </el-form-item>
        </template>
      </el-form>
      <el-alert v-if="aiLogVisual.msg" :type="aiLogVisual.error?'error':'success'" :closable="false" style="margin-top:8px">{{ aiLogVisual.msg }}</el-alert>
      <div v-if="aiLogVisual.fileInfo.length" style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap">
        <el-tag v-for="fi in aiLogVisual.fileInfo" :key="fi.name" size="small" type="success">{{ fi.name }} ({{ fi.lines }}行)</el-tag>
      </div>
    </el-card>
    <el-card v-if="aiLogVisual.rounds.length" shadow="never">
      <template #header>
        ② 分析结果：{{ aiLogVisual.totalLines }} 行日志，匹配 {{ aiLogVisual.matchedLines }} 行，共 {{ aiLogVisual.rounds.length }} 轮
      </template>
      <div v-for="(round, ri) in aiLogVisual.rounds" :key="ri" style="margin-bottom:16px">
        <div style="font-weight:bold;color:#409eff;margin-bottom:6px;font-size:14px">第 {{ round.round }} 轮分析（{{ round.entries.length }} 条记录）</div>
        <el-table :data="round.entries" size="small" stripe border>
          <el-table-column prop="line_no" label="行号" width="70"></el-table-column>
          <el-table-column prop="time" label="时间" width="160"></el-table-column>
          <el-table-column prop="type" label="类型" width="100">
            <template #default="{row}">
              <el-tag size="small" :type="row.type==='知识库调用'?'primary':row.type==='分析结果'?'success':row.type==='评论分析'?'warning':'info'">{{ row.type }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="content" label="内容" min-width="500" show-overflow-tooltip></el-table-column>
        </el-table>
      </div>
    </el-card>
    <el-empty v-else-if="!aiLogVisual.loading && aiLogVisual.msg && !aiLogVisual.error" description="无匹配记录"></el-empty>

    <!-- 本地文档分析 -->
    <el-card shadow="never" style="margin-top:16px;border:2px solid #67c23a">
      <template #header><span style="font-weight:700;color:#67c23a">本地文档分析（study目录推理轮次解析）</span></template>
      <div style="display:flex;align-items:center;gap:10px">
        <el-button type="primary" :loading="studyAnalysis.loading" @click="studyAnalysisRefresh">刷新文件夹</el-button>
        <el-select v-if="studyAnalysis.folders.length" v-model="studyAnalysis.selectedFolder" placeholder="选择分析文件夹" style="width:400px" filterable>
          <el-option v-for="f in studyAnalysis.folders" :key="f.path" :label="f.name" :value="f.path"></el-option>
        </el-select>
        <el-button v-if="studyAnalysis.selectedFolder" type="success" :loading="studyAnalysis.loading" @click="studyAnalysisParse">解析</el-button>
      </div>
      <el-alert v-if="studyAnalysis.msg" :type="studyAnalysis.error?'error':'success'" :closable="false" style="margin-top:8px">{{ studyAnalysis.msg }}</el-alert>
    </el-card>
    <!-- 分析结果 -->
    <el-card v-if="studyAnalysis.rounds.length" shadow="never" style="margin-top:12px">
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span style="font-weight:600">推理轮次详情：{{ studyAnalysis.folderName }}</span>
          <div style="display:flex;gap:8px">
            <el-tag type="info">共 {{ studyAnalysis.totalRounds }} 轮</el-tag>
            <el-tag type="warning">总耗时 {{ studyAnalysis.elapsedSeconds }}s</el-tag>
          </div>
        </div>
      </template>
      <el-table :data="studyAnalysis.rounds" size="small" stripe border>
        <el-table-column prop="round" label="轮次" width="60" align="center"></el-table-column>
        <el-table-column label="推理内容" min-width="300">
          <template #default="{row}">
            <div style="white-space:pre-wrap;font-size:12px;line-height:1.5">{{ row.llm_summary || '-' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="工具调用" width="200">
          <template #default="{row}">
            <el-tag v-if="row.tool_count" type="primary" size="small">{{ row.tool_count }} 次</el-tag>
            <span v-else style="color:#999">无</span>
            <span v-if="row.tools.length" style="display:inline-block;width:36px;vertical-align:middle">
              <el-popover trigger="hover" width="400" teleported>
                <template #reference><el-button link type="primary" size="small">详情</el-button></template>
                <div v-for="(t,i) in row.tools" :key="i" style="font-size:12px;margin-bottom:4px">{{ t }}</div>
              </el-popover>
            </span>
          </template>
        </el-table-column>
        <el-table-column label="知识库" width="160">
          <template #default="{row}">
            <el-tag v-if="row.knowledge_count" type="success" size="small">{{ row.knowledge_count }} 篇</el-tag>
            <span v-else style="color:#999">-</span>
            <span v-if="row.knowledge.length" style="display:inline-block;width:36px;vertical-align:middle">
              <el-popover trigger="hover" width="350" teleported>
                <template #reference><el-button link type="success" size="small">列表</el-button></template>
                <div v-for="(k,i) in row.knowledge" :key="i" style="font-size:12px;margin-bottom:2px">{{ k }}</div>
              </el-popover>
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="avg_time" label="平均耗时" width="100" align="center">
          <template #default="{row}"><span>{{ row.avg_time }}s</span></template>
        </el-table-column>
      </el-table>
    </el-card>
    <!-- 结论汇总 -->
    <el-card v-if="studyAnalysis.conclusions.length" shadow="never" style="margin-top:12px">
      <template #header><span style="font-weight:600">结论汇总（{{ studyAnalysis.conclusions.length }} 条）</span></template>
      <el-table :data="studyAnalysis.conclusions" size="small" stripe border>
        <el-table-column type="index" label="#" width="40"></el-table-column>
        <el-table-column prop="statement" label="结论" min-width="400" show-overflow-tooltip></el-table-column>
        <el-table-column prop="confidence" label="置信度" width="110" align="center">
          <template #default="{row}">
            <el-tag :type="row.confidence==='high'?'success':row.confidence==='medium'?'warning':'info'" size="small">{{ ({high:'高',medium:'中',low:'低'})[row.confidence] || row.confidence }}（{{ row.confidence }}）</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="severity" label="严重度" width="130" align="center">
          <template #default="{row}">
            <el-tag :type="row.severity==='critical'?'danger':row.severity==='major'||row.severity==='important'?'warning':'info'" size="small">{{ ({critical:'严重',major:'重要',important:'重要',info:'信息'})[row.severity] || row.severity }}（{{ row.severity }}）</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="category" label="类型" width="140">
          <template #default="{row}">
            <el-tag size="small">{{ ({confirmed:'已确认',possible:'可能',root_cause:'根因',symptom:'表象'})[row.category] || row.category }}（{{ row.category }}）</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script lang="ts">
// @ts-nocheck
import { ElMessage } from 'element-plus';
import { api } from '../composables/utils';
export default {
  name: 'AiLogVisualPanel',
  data() {
    return {
      aiLogVisual: {
        jiraId: '', logName: 'all', loading: false, source: 'remote',
        totalLines: 0, matchedLines: 0, rounds: [], msg: '', error: false,
        uploadFile: null, uploadFileName: '', fileInfo: [],
      },
      studyAnalysis: {
        loading: false, msg: '', error: false,
        folders: [], selectedFolder: '',
        rounds: [], conclusions: [], totalRounds: 0, elapsedSeconds: 0, folderName: '',
      },
    };
  },
  methods: {
    async readAiLogVisual() {
      if (!this.aiLogVisual.jiraId) return ElMessage.warning('请输入 Jira 号');
      this.aiLogVisual.loading = true;
      this.aiLogVisual.msg = ''; this.aiLogVisual.error = false;
      this.aiLogVisual.rounds = []; this.aiLogVisual.totalLines = 0; this.aiLogVisual.matchedLines = 0;
      try {
        const body = await api('/api/test/ai_log_visual', {
          method: 'POST',
          body: JSON.stringify({ jira_id: this.aiLogVisual.jiraId, log_name: this.aiLogVisual.logName }),
        });
        const d = body.data;
        this.aiLogVisual.totalLines = d.total_lines;
        this.aiLogVisual.matchedLines = d.matched_lines;
        this.aiLogVisual.rounds = d.rounds || [];
        this.aiLogVisual.msg = body.message;
      } catch (e) {
        this.aiLogVisual.msg = '读取失败: ' + e.message;
        this.aiLogVisual.error = true;
      } finally { this.aiLogVisual.loading = false; }
    },
    handleAiLogFileSelect(fileObj) {
      this.aiLogVisual.uploadFile = fileObj.raw;
      this.aiLogVisual.uploadFileName = fileObj.name;
      this.aiLogVisual.msg = '';
      this.aiLogVisual.fileInfo = [];
    },
    async uploadAiLogVisual() {
      if (!this.aiLogVisual.jiraId) return ElMessage.warning('请输入 Jira 号');
      if (!this.aiLogVisual.uploadFile) return ElMessage.warning('请选择文件');
      this.aiLogVisual.loading = true;
      this.aiLogVisual.msg = ''; this.aiLogVisual.error = false;
      this.aiLogVisual.rounds = []; this.aiLogVisual.totalLines = 0; this.aiLogVisual.matchedLines = 0;
      this.aiLogVisual.fileInfo = [];
      try {
        const formData = new FormData();
        formData.append('file', this.aiLogVisual.uploadFile);
        const resp = await fetch('/api/test/ai_log_visual_upload?jira_id=' + encodeURIComponent(this.aiLogVisual.jiraId), {
          method: 'POST', body: formData,
        });
        const body = await resp.json();
        if (!body.success) throw new Error(body.message || '解析失败');
        const d = body.data;
        this.aiLogVisual.totalLines = d.total_lines;
        this.aiLogVisual.matchedLines = d.matched_lines;
        this.aiLogVisual.rounds = d.rounds || [];
        this.aiLogVisual.fileInfo = d.file_info || [];
        this.aiLogVisual.msg = body.message;
      } catch (e) {
        this.aiLogVisual.msg = '上传解析失败: ' + e.message;
        this.aiLogVisual.error = true;
      } finally { this.aiLogVisual.loading = false; }
    },
    async studyAnalysisRefresh() {
      this.studyAnalysis.loading = true;
      this.studyAnalysis.msg = ''; this.studyAnalysis.error = false;
      this.studyAnalysis.selectedFolder = '';
      this.studyAnalysis.rounds = []; this.studyAnalysis.conclusions = [];
      try {
        const body = await api('/api/test/study_analysis', { method: 'POST', body: '{}' });
        this.studyAnalysis.folders = body.data?.folders || [];
        this.studyAnalysis.msg = body.message;
        if (this.studyAnalysis.folders.length === 1) {
          this.studyAnalysis.selectedFolder = this.studyAnalysis.folders[0].path;
        }
      } catch (e) {
        this.studyAnalysis.msg = '扫描失败: ' + e.message;
        this.studyAnalysis.error = true;
      } finally { this.studyAnalysis.loading = false; }
    },
    async studyAnalysisParse() {
      if (!this.studyAnalysis.selectedFolder) return ElMessage.warning('请选择一个文件夹');
      this.studyAnalysis.loading = true;
      this.studyAnalysis.rounds = []; this.studyAnalysis.conclusions = [];
      try {
        const body = await api('/api/test/study_analysis', {
          method: 'POST',
          body: JSON.stringify({ folder_path: this.studyAnalysis.selectedFolder }),
        });
        const d = body.data;
        this.studyAnalysis.rounds = d.rounds || [];
        this.studyAnalysis.conclusions = d.conclusions || [];
        this.studyAnalysis.totalRounds = d.total_rounds || 0;
        this.studyAnalysis.elapsedSeconds = d.elapsed_seconds || 0;
        this.studyAnalysis.folderName = d.folder_name || '';
        this.studyAnalysis.msg = body.message;
      } catch (e) {
        this.studyAnalysis.msg = '解析失败: ' + e.message;
        this.studyAnalysis.error = true;
      } finally { this.studyAnalysis.loading = false; }
    },
  },
};
</script>
