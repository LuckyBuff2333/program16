<template>
  <div class="obs-ht">
    <el-table
      v-if="tableData.length"
      :data="tableData"
      size="small"
      border
      :header-cell-style="headerStyle"
      row-class-name="obs-ht-row"
    >
      <el-table-column prop="hypothesis" label="假设" min-width="220">
        <template #default="{ row }">
          <span class="obs-ht-hypo">{{ row.hypothesis }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="verdict" label="判定" width="110" align="center">
        <template #default="{ row }">
          <el-tag
            :type="row.verdict === 'confirmed' ? 'success' : 'danger'"
            effect="dark"
            size="small"
            round
          >
            {{ row.verdict === 'confirmed' ? '已确认' : '已排除' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="evidence" label="关键证据" min-width="260">
        <template #default="{ row }">
          <span class="obs-ht-evidence">{{ row.evidence }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="remark" label="备注" width="110">
        <template #default="{ row }">
          <span style="color: #909399; font-size: 12px">{{ row.remark }}</span>
        </template>
      </el-table-column>
    </el-table>

    <div v-else class="obs-ht-empty">
      暂无假设判定数据，请点击一键复测
    </div>
  </div>
</template>

<script lang="ts">
/**
 * HypothesisTable — 假设判定表
 *
 * 数据格式: [{key?, hypothesis, verdict, evidence, remark}]
 */
export default {
  props: {
    hypotheses: { type: Array as () => any[], default: () => [] },
  },
  computed: {
    tableData(): any[] {
      return (this.hypotheses || []).filter(h => h && h.hypothesis)
    },
    headerStyle() {
      return {
        background: '#f5f7fa',
        color: '#303133',
        fontWeight: 600,
        fontSize: '13px',
      }
    },
  },
}
</script>

<style scoped>
.obs-ht { }
.obs-ht-hypo {
  font-size: 13px;
  color: #303133;
  line-height: 1.6;
}
.obs-ht-evidence {
  font-size: 12px;
  color: #606266;
  line-height: 1.6;
}
.obs-ht-empty {
  color: #909399;
  font-size: 13px;
  padding: 24px 0;
  text-align: center;
}
</style>
