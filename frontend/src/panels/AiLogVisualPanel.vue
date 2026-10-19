<template>
  <div class="test-panel">
    <div class="section-title">AI日志分析自学习内容可视化</div>
    <el-alert type="info" :closable="false" style="margin-bottom:12px">
      输入 Jira 号获取 AI 日志分析报告，自动解析推理轮次
    </el-alert>
    <!-- ① AI 日志分析报告 -->
    <el-card shadow="never" style="margin-bottom:12px;border:2px solid #409eff">
      <template #header>① AI 日志分析报告</template>
      <el-form inline>
        <el-form-item label="Jira号">
          <el-input v-model="studyAnalysis.aiReportBugid" placeholder="输入 Jira 号（如 VCU-105015）" clearable @keyup.enter="fetchAiReport" style="width:260px"></el-input>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="studyAnalysis.aiReportLoading" @click="fetchAiReport">获取报告</el-button>
        </el-form-item>
      </el-form>
      <el-alert v-if="studyAnalysis.aiReportMsg" :type="studyAnalysis.aiReportContent?'success':'error'" :closable="false" style="margin-top:8px">{{ studyAnalysis.aiReportMsg }}</el-alert>
      <div v-if="studyAnalysis.aiReportDirPath" style="margin-top:8px;display:flex;align-items:center;gap:8px;flex-wrap:wrap">
        <el-tag type="info" size="small">本地路径: {{ studyAnalysis.aiReportDirPath }}</el-tag>
        <el-button size="small" @click="openReportDir">打开目录</el-button>
        <el-button size="small" type="success" @click="readLogFromReport">解析轮次</el-button>
      </div>
    </el-card>
    <!-- ② 推理轮次解析结果 -->
    <el-card v-if="studyAnalysis.rounds.length" shadow="never" style="margin-top:12px;border:2px solid #67c23a">
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
          <template #default="{row}"><span>{{ row.avg_time ? row.avg_time + 's' : '-' }}</span></template>
        </el-table-column>
        <el-table-column label="本轮结论" min-width="250">
          <template #default="{row}">
            <div style="white-space:pre-wrap;font-size:12px;line-height:1.5">{{ row.conclusion || '-' }}</div>
          </template>
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
      studyAnalysis: {
        loading: false, msg: '', error: false,
        folders: [], selectedFolder: '',
        rounds: [], conclusions: [], totalRounds: 0, elapsedSeconds: 0, folderName: '',
        aiReportBugid: '', aiReportContent: '', aiReportLoading: false, aiReportMsg: '',
        aiReportFilePath: '', aiReportDirPath: '',
      },
    };
  },
  methods: {
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
    async fetchAiReport() {
      const bugid = (this.studyAnalysis.aiReportBugid || '').trim();
      if (!bugid) return ElMessage.warning('请输入 Jira 号');
      this.studyAnalysis.aiReportLoading = true;
      this.studyAnalysis.aiReportContent = '';
      this.studyAnalysis.aiReportMsg = '';
      this.studyAnalysis.aiReportFilePath = '';
      this.studyAnalysis.aiReportDirPath = '';
      try {
        const body = await api(`/api/test/ai_report/${encodeURIComponent(bugid)}`);
        if (body.ok && body.data?.content) {
          this.studyAnalysis.aiReportContent = body.data.content;
          this.studyAnalysis.aiReportFilePath = body.data.file_path || '';
          this.studyAnalysis.aiReportDirPath = body.data.dir_path || '';
          this.studyAnalysis.aiReportMsg = body.message || '获取成功';
        } else {
          this.studyAnalysis.aiReportMsg = body.message || '获取失败';
        }
      } catch (e) {
        this.studyAnalysis.aiReportMsg = '请求失败: ' + e.message;
      } finally { this.studyAnalysis.aiReportLoading = false; }
    },
    async openReportDir() {
      if (!this.studyAnalysis.aiReportDirPath) return;
      try { await api(`/api/test/open_dir?path=${encodeURIComponent(this.studyAnalysis.aiReportDirPath)}`); } catch (_) {}
    },
    async readLogFromReport() {
      const content = (this.studyAnalysis.aiReportContent || '').trim();
      if (!content) return ElMessage.warning('请先获取报告');
      const bugid = (this.studyAnalysis.aiReportBugid || '').trim();
      this.studyAnalysis.loading = true;
      this.studyAnalysis.rounds = [];
      this.studyAnalysis.msg = '';
      this.studyAnalysis.error = false;
      try {
        const body = await api('/api/test/ai_report_analyze', {
          method: 'POST', body: JSON.stringify({ content }),
        });
        if (body.ok && body.data) {
          this.studyAnalysis.rounds = body.data.rounds || [];
          this.studyAnalysis.totalRounds = body.data.total_rounds || 0;
          this.studyAnalysis.elapsedSeconds = body.data.elapsed_seconds || 0;
          this.studyAnalysis.folderName = bugid || 'AI报告分析';
          this.studyAnalysis.msg = `解析完成: ${body.data.total_rounds} 轮`;
        } else {
          this.studyAnalysis.error = true;
          this.studyAnalysis.msg = body.msg || '解析失败';
        }
      } catch (e: any) {
        this.studyAnalysis.error = true;
        this.studyAnalysis.msg = '解析失败: ' + e.message;
      } finally {
        this.studyAnalysis.loading = false;
      }
    },
  },
};
</script>
