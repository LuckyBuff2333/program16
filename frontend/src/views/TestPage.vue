<template>
  <el-container style="background:#fff;border-radius:10px;height:100%;overflow:hidden">
    <el-main class="module-main">
        <!-- 大型面板委托给独立组件，keep-alive 保留执行状态 -->
        <keep-alive>
          <component :is="activePanelComponent" />
        </keep-alive>
    </el-main>
  </el-container>
</template>

<script lang="ts">
// @ts-nocheck
import { colWidth, verdictStyle, fieldLabel } from '../composables/utils';
import BatchAiPanel from '../panels/BatchAiPanel.vue';
import ConfidenceBatchPanel from '../panels/ConfidenceBatchPanel.vue';
import ProdBatchPanel from '../panels/ProdBatchPanel.vue';
import TroubleshootPanel from '../panels/TroubleshootPanel.vue';
import OnlineFollowupPanel from '../panels/OnlineFollowupPanel.vue';
import AiLogVisualPanel from '../panels/AiLogVisualPanel.vue';
import ConfigTuningPanel from '../panels/ConfigTuningPanel.vue';
import DailySummaryPanel from '../panels/DailySummaryPanel.vue';
import JiraLookupPanel from '../panels/JiraLookupPanel.vue';
import AppLogDownloadPanel from '../panels/AppLogDownloadPanel.vue';
import TimeExtractPanel from '../panels/TimeExtractPanel.vue';
import AdpTestPanel from '../panels/AdpTestPanel.vue';

export default {
  name: 'TestPage',
  components: {
    BatchAiPanel, ConfidenceBatchPanel,
    ProdBatchPanel, TroubleshootPanel, OnlineFollowupPanel,
    AiLogVisualPanel, ConfigTuningPanel, DailySummaryPanel,
    JiraLookupPanel, AppLogDownloadPanel,
    TimeExtractPanel,
    AdpTestPanel,
  },
  props: { testPanel: { type: String, default: 'batch_ai' } },
  computed: {
    activePanelComponent() {
      const map = {
        batch_ai: 'BatchAiPanel',
        confidence_batch: 'ConfidenceBatchPanel',
        prod_batch: 'ProdBatchPanel',
        troubleshoot: 'TroubleshootPanel',
        online_followup: 'OnlineFollowupPanel',
        ai_log_visual: 'AiLogVisualPanel',
        config_tuning: 'ConfigTuningPanel',
        daily_summary: 'DailySummaryPanel',
        jira_lookup: 'JiraLookupPanel',
        app_log_download: 'AppLogDownloadPanel',
        time_extract: 'TimeExtractPanel',
        adp_test: 'AdpTestPanel',
      };
      return map[this.testPanel] || 'BatchAiPanel';
    },
  },
  methods: {
    colWidth, verdictStyle, fieldLabel,
  },
};
</script>
