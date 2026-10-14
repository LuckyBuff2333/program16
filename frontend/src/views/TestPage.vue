<template>
  <el-container style="background:#fff;border-radius:10px;height:100%;overflow:hidden">
    <el-main class="module-main">
      <transition name="fade" mode="out-in">
      <div>
        <!-- 评论分析侧重点对比 -->
        <div v-if="testPanel === 'comment_compare'" key="comment_compare" class="test-panel">
          <div class="section-title">评论分析侧重点对比</div>
          <el-alert type="info" :closable="false"
            title="对同一 Jira 用多种 prompt 策略各跑一次评论分析，并列展示结果，选定偏好风格后自动注入后续分析"></el-alert>
          <el-card shadow="never" style="margin-top:14px">
            <el-row :gutter="12" align="middle">
              <el-col :span="8"><el-input v-model="commentCompare.bugid" placeholder="输入 Jira 号" clearable></el-input></el-col>
              <el-col :span="6"><el-button type="primary" :loading="running.commentCompare" @click="runCommentCompare">执行对比</el-button></el-col>
              <el-col :span="10" v-if="commentCompare.currentStyle"><el-tag type="success" size="large">当前风格: {{ commentCompare.currentStyle }}</el-tag></el-col>
            </el-row>
          </el-card>
          <el-card v-if="commentCompare.results.length" shadow="never" style="margin-top:14px">
            <div class="section-title" style="margin-bottom:10px">策略对比汇总</div>
            <el-table :data="commentCompare.results" size="small" stripe border>
              <el-table-column prop="label" label="分析策略" width="120">
                <template #default="{ row }"><span style="font-weight:600">{{ row.label }}</span><el-tag v-if="commentCompare.selected === row.key" type="success" size="small" style="margin-left:4px">已选</el-tag></template>
              </el-table-column>
              <el-table-column prop="bugid" label="Jira号" width="130"></el-table-column>
              <el-table-column prop="root_cause" label="问题根因" min-width="200" show-overflow-tooltip></el-table-column>
              <el-table-column prop="table_conclusion" label="AI评论总结" min-width="180" show-overflow-tooltip></el-table-column>
              <el-table-column prop="has_ai_conclusion" label="AI结论" width="80" align="center">
                <template #default="{ row }"><el-tag :type="row.has_ai_conclusion ? 'success' : 'info'" size="small">{{ row.has_ai_conclusion ? '有' : '无' }}</el-tag></template>
              </el-table-column>
              <el-table-column prop="analysis_status" label="状态" width="80" align="center">
                <template #default="{ row }"><el-tag :type="row.analysis && !row.analysis.startsWith('（') ? 'success' : 'danger'" size="small">{{ row.analysis && !row.analysis.startsWith('（') ? '成功' : '失败' }}</el-tag></template>
              </el-table-column>
              <el-table-column prop="confidence_assessment" label="置信度评估" width="100" align="center">
                <template #default="{ row }"><el-tag :type="row.confidence_assessment === '高' ? 'success' : (row.confidence_assessment === '中' ? 'warning' : 'danger')" size="small">{{ row.confidence_assessment || '低' }}</el-tag></template>
              </el-table-column>
            </el-table>
          </el-card>
          <el-row :gutter="14" style="margin-top:14px" v-if="commentCompare.results.length">
            <el-col :span="6" v-for="item in commentCompare.results" :key="item.key">
              <el-card shadow="hover" :style="commentCompare.selected === item.key ? 'border:2px solid #67c23a' : ''">
                <template #header>
                  <div style="display:flex;align-items:center;justify-content:space-between">
                    <span style="font-weight:bold">{{ item.label }}</span>
                    <el-tag v-if="commentCompare.selected === item.key" type="success" size="small">已选定</el-tag>
                  </div>
                </template>
                <div style="font-size:12px;color:#909399;margin-bottom:8px">{{ item.instruction }}</div>
                <div style="white-space:pre-wrap;font-size:13px;max-height:360px;overflow-y:auto">{{ item.analysis }}</div>
                <el-button type="primary" size="small" style="margin-top:10px;width:100%"
                  :disabled="commentCompare.selected === item.key" @click="saveStylePreference(item.key, item.label, item.instruction)">
                  {{ commentCompare.selected === item.key ? '已选定' : '选定此风格' }}
                </el-button>
              </el-card>
            </el-col>
          </el-row>
          <el-empty v-else-if="!running.commentCompare" description="输入 Jira 号并点击执行对比" style="margin-top:30px"></el-empty>
        </div>

        <!-- 大型面板委托给独立组件 -->
        <BatchAiPanel v-else-if="testPanel === 'batch_ai'" />
        <ConfidenceBatchPanel v-else-if="testPanel === 'confidence_batch'" />
        <ProdBatchPanel v-else-if="testPanel === 'prod_batch'" />
        <TroubleshootPanel v-else-if="testPanel === 'troubleshoot'" />
        <OnlineFollowupPanel v-else-if="testPanel === 'online_followup'" />
        <AiLogVisualPanel v-else-if="testPanel === 'ai_log_visual'" />
        <ConfigTuningPanel v-else-if="testPanel === 'config_tuning'" />
        <DailySummaryPanel v-else-if="testPanel === 'daily_summary'" />
      </div>
      </transition>
    </el-main>
  </el-container>
</template>

<script lang="ts">
// @ts-nocheck
import { ElMessage } from 'element-plus';
import { api, colWidth, verdictStyle, fieldLabel } from '../composables/utils';
import BatchAiPanel from '../panels/BatchAiPanel.vue';
import ConfidenceBatchPanel from '../panels/ConfidenceBatchPanel.vue';
import ProdBatchPanel from '../panels/ProdBatchPanel.vue';
import TroubleshootPanel from '../panels/TroubleshootPanel.vue';
import OnlineFollowupPanel from '../panels/OnlineFollowupPanel.vue';
import AiLogVisualPanel from '../panels/AiLogVisualPanel.vue';
import ConfigTuningPanel from '../panels/ConfigTuningPanel.vue';
import DailySummaryPanel from '../panels/DailySummaryPanel.vue';

export default {
  name: 'TestPage',
  components: {
    BatchAiPanel, ConfidenceBatchPanel,
    ProdBatchPanel, TroubleshootPanel, OnlineFollowupPanel,
    AiLogVisualPanel, ConfigTuningPanel, DailySummaryPanel,
  },
  props: { testPanel: { type: String, default: 'batch_ai' } },
  data() {
    return {
      commentCompare: { bugid: '', results: [] as any[], selected: null as string | null, currentStyle: '' },
      running: { commentCompare: false },
    };
  },
  methods: {
    colWidth, verdictStyle, fieldLabel,
    async runCommentCompare() {
      if (!this.commentCompare.bugid) return ElMessage.warning('请输入 Jira 号');
      this.running.commentCompare = true; this.commentCompare.results = []; this.commentCompare.selected = null;
      try {
        const result = await api('/api/test/comment_compare_strategies', { method: 'POST', body: JSON.stringify({ bugid: this.commentCompare.bugid }) });
        const data = result.data || {};
        this.commentCompare.results = data.strategies || []; this.commentCompare.currentStyle = data.current_style || '';
        if (data.current_style) { const match = (data.strategies || []).find((s: any) => s.instruction === data.current_style); if (match) this.commentCompare.selected = match.key; }
        ElMessage.success(result.msg || '对比完成');
      } catch (e: any) { ElMessage.error('对比失败: ' + e.message); } finally { this.running.commentCompare = false; }
    },
    async saveStylePreference(key: string, label: string, instruction: string) {
      try {
        await api('/api/test/save_style_preference', { method: 'POST', body: JSON.stringify({ strategy_key: key, instruction }) });
        this.commentCompare.selected = key; this.commentCompare.currentStyle = instruction;
        ElMessage.success(`已选定「${label}」风格，后续分析将按此侧重点执行`);
      } catch (e: any) { ElMessage.error('保存失败: ' + e.message); }
    },

  },
};
</script>
