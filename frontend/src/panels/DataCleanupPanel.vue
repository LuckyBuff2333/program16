<template>
  <div class="data-cleanup">
    <el-alert type="info" :closable="false" show-icon style="margin-bottom:12px"
      title="按分析开始时间筛选数据沉淀：只保留失败后又有同 Jira 同来源成功记录的失败行，可勾选删除。" />

    <el-card shadow="never">
      <el-form inline>
        <el-form-item label="分析开始时间">
          <el-date-picker v-model="range" type="datetimerange" value-format="YYYY-MM-DD HH:mm:ss"
            start-placeholder="开始时间" end-placeholder="结束时间" style="width:360px" />
        </el-form-item>
        <el-form-item label="来源">
          <el-radio-group v-model="source">
            <el-radio-button label="">全部</el-radio-button>
            <el-radio-button label="parseFullTicket">线上</el-radio-button>
            <el-radio-button label="jira_analyze">PC</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="querying" @click="query">查询</el-button>
          <el-button type="danger" :disabled="!selected.length" :loading="deleting" @click="removeSelected">
            删除选中（{{ selected.length }}）
          </el-button>
          <el-button type="danger" plain :disabled="!rows.length" :loading="deleting" @click="removeAll">
            全选删除（{{ rows.length }}）
          </el-button>
        </el-form-item>
      </el-form>
      <div style="margin:4px 0 10px;color:#909399;font-size:12px">
        共 {{ total }} 条；勾选后只删除失败行，成功行不会动。
      </div>

      <el-table :data="rows" size="small" stripe border max-height="520"
        row-key="record_id" @selection-change="onSelection">
        <el-table-column type="selection" width="45" reserve-selection />
        <el-table-column prop="jira号" label="Jira号" width="120" />
        <el-table-column prop="触发来源" label="来源" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.触发来源 === 'parseFullTicket'" type="warning" size="small">线上</el-tag>
            <el-tag v-else-if="row.触发来源 === 'jira_analyze'" type="info" size="small">PC</el-tag>
            <span v-else>{{ row.触发来源 || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="分析开始时间" label="失败开始时间" width="165" />
        <el-table-column prop="分析完成时间" label="失败完成时间" width="165" />
        <el-table-column prop="后续成功时间" label="后续成功时间" width="165" />
        <el-table-column prop="错误分类" label="错误分类" min-width="180" show-overflow-tooltip />
        <el-table-column prop="人工审核结果" label="人工审核结果" min-width="220" show-overflow-tooltip />
      </el-table>
    </el-card>
  </div>
</template>

<script lang="ts">
// @ts-nocheck
import { ElMessage, ElMessageBox } from 'element-plus';
import { api } from '../composables/utils';

export default {
  name: 'DataCleanupPanel',
  data() {
    return {
      range: [],
      source: '',
      rows: [],
      total: 0,
      selected: [],
      querying: false,
      deleting: false,
    };
  },
  methods: {
    async query() {
      if (!this.range || this.range.length !== 2) {
        ElMessage.warning('请选择分析开始时间范围');
        return;
      }
      this.querying = true;
      try {
        const res = await api('/api/test/data_cleanup_preview', {
          method: 'POST',
          body: JSON.stringify({ start: this.range[0], end: this.range[1], source: this.source }),
        });
        if (!res.ok) {
          ElMessage.error(res.message || '查询失败');
          return;
        }
        this.rows = (res.data || {}).rows || [];
        this.total = (res.data || {}).total || 0;
        this.selected = [];
      } catch (e) {
        ElMessage.error('查询失败: ' + (e.message || e));
      } finally {
        this.querying = false;
      }
    },
    onSelection(rows) {
      this.selected = rows || [];
    },
    async remove(ids) {
      if (!ids.length) return;
      await ElMessageBox.confirm(
        `确认删除 ${ids.length} 条失败记录？成功记录不会删除。`,
        '删除确认',
        { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
      );
      this.deleting = true;
      try {
        const res = await api('/api/test/data_cleanup_delete', {
          method: 'POST',
          body: JSON.stringify({ record_ids: ids }),
        });
        if (res.ok) {
          ElMessage.success(res.message || '删除完成');
          await this.query();
        } else {
          ElMessage.error(res.message || '删除失败');
        }
      } catch (e) {
        ElMessage.error('删除失败: ' + (e.message || e));
      } finally {
        this.deleting = false;
      }
    },
    removeSelected() {
      return this.remove(this.selected.map(r => r.record_id));
    },
    removeAll() {
      return this.remove(this.rows.map(r => r.record_id));
    },
  },
};
</script>

<style scoped>
.data-cleanup { padding: 4px; }
</style>
