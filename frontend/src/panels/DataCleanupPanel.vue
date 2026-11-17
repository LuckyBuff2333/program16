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
        <el-table-column prop="后续成功时间" label="后续成功时间" width="165" />
        <el-table-column prop="错误分类" label="错误分类" min-width="180" show-overflow-tooltip />
        <el-table-column prop="人工审核结果" label="人工审核结果" min-width="220" show-overflow-tooltip />
      </el-table>
    </el-card>

    <!-- 多次报错去重 -->
    <el-card shadow="never" style="margin-top:16px">
      <el-alert type="warning" :closable="false" show-icon style="margin-bottom:12px"
        title="多次报错仅保留最新：按 Jira 号+来源归类，展示重复报错记录，可复制审核结果或删除旧记录。" />
      <el-form inline>
        <el-form-item label="分析完成时间">
          <el-date-picker v-model="multiRange" type="datetimerange" value-format="YYYY-MM-DD HH:mm:ss"
            start-placeholder="开始时间" end-placeholder="结束时间" style="width:360px" />
        </el-form-item>
        <el-form-item label="来源">
          <el-radio-group v-model="multiSource">
            <el-radio-button label="">全部</el-radio-button>
            <el-radio-button label="parseFullTicket">线上</el-radio-button>
            <el-radio-button label="jira_analyze">PC</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item>
          <el-button type="warning" :loading="multiQuerying" @click="queryMultiErrors">查询多次报错</el-button>
        </el-form-item>
      </el-form>
      <div v-if="multiRows.length" style="margin:4px 0 10px;display:flex;justify-content:space-between;align-items:center">
        <span style="color:#909399;font-size:12px">共 {{ multiRows.length }} 组 {{ multiTotalRecs }} 条多次报错记录</span>
        <span>
          <el-button size="small" type="primary" :loading="batchCopying" @click="batchCopyReview">一键复制审核结果</el-button>
          <el-button size="small" type="danger" :loading="batchDeleting" @click="batchDeleteOld">一键删除旧记录</el-button>
        </span>
      </div>
      <el-table :data="multiRows" size="small" stripe border max-height="520" row-key="jira"
        @expand-change="onMultiExpand">
        <el-table-column type="expand">
          <template #default="slotProps">
            <div style="padding:8px 16px">
              <div style="color:#606266;font-size:12px;margin-bottom:6px">全部记录（按时间降序）</div>
              <el-table :data="slotProps.row.records" size="small" border max-height="260">
                <el-table-column type="index" label="#" width="40" />
                <el-table-column prop="分析完成时间" label="分析完成时间" width="165" />
                <el-table-column prop="错误分类" label="错误信息" min-width="200" show-overflow-tooltip />
                <el-table-column prop="人工审核结果" label="人工审核结果" min-width="200" show-overflow-tooltip>
                  <template #default="{ row }">
                    <span v-if="row.人工审核结果">{{ row.人工审核结果 }}</span>
                    <span v-else style="color:#C0C4CC">-</span>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="jira" label="Jira号" width="140" />
        <el-table-column label="重复数" width="70" align="center">
          <template #default="{ row }">
            <el-tag type="warning" size="small">{{ row.count }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="70" align="center">
          <template #default="{ row }">
            <el-tag :type="row.source === 'jira_analyze' ? 'info' : row.source === 'parseFullTicket' ? 'warning' : 'danger'" size="small">
              {{ row.source === 'jira_analyze' ? 'PC' : row.source === 'parseFullTicket' ? '线上' : (row.source || '-') }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最新完成时间" width="165">
          <template #default="{ row }">{{ row.records[0]?.分析完成时间 }}</template>
        </el-table-column>
        <el-table-column prop="error_cls" label="错误分类" min-width="180" show-overflow-tooltip />
        <el-table-column label="人工审核结果" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="latestReview(row)">{{ latestReview(row) }}</span>
            <span v-else style="color:#C0C4CC">未审核</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="240" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" :loading="row._copying"
              @click="copyReview(row)">复制审核结果</el-button>
            <el-button size="small" type="danger" :loading="row._deleting"
              @click="deleteOld(row)">删除旧记录</el-button>
          </template>
        </el-table-column>
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
      // 多次报错去重
      multiRange: [],
      multiSource: '',
      multiRows: [],
      multiTotalRecs: 0,
      multiQuerying: false,
      batchCopying: false,
      batchDeleting: false,
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
    latestReview(group) {
      const r = (group.records || []).find(r => r.人工审核结果);
      return r ? r.人工审核结果 : '';
    },
    async queryMultiErrors() {
      if (!this.multiRange || this.multiRange.length !== 2) {
        ElMessage.warning('请选择分析完成时间范围');
        return;
      }
      this.multiQuerying = true;
      try {
        const res = await api('/api/test/data_multi_errors_query', {
          method: 'POST',
          body: JSON.stringify({ start: this.multiRange[0], end: this.multiRange[1], source: this.multiSource }),
        });
        if (!res.ok) { ElMessage.error(res.message || '查询失败'); return; }
        const groups = (res.data || {}).groups || [];
        this.multiRows = groups.map(g => ({ ...g, _copying: false, _deleting: false }));
        this.multiTotalRecs = groups.reduce((s, g) => s + g.count, 0);
        ElMessage.success(res.message || `查询到 ${groups.length} 组`);
      } catch (e) {
        ElMessage.error('查询失败: ' + (e.message || e));
      } finally { this.multiQuerying = false; }
    },
    onMultiExpand() {},
    async copyReview(group) {
      if (group.count < 2) return ElMessage.warning('仅一条记录，无需复制');
      const latest = group.records[0];
      if (latest.人工审核结果) return ElMessage.info('最新记录已有审核结果');
      const reviewed = group.records.find(r => r.人工审核结果);
      if (!reviewed) return ElMessage.warning('该组无审核结果可复制');
      group._copying = true;
      try {
        const res = await api('/api/test/data_multi_errors_copy_review', {
          method: 'POST',
          body: JSON.stringify({ record_id: latest.record_id, review: reviewed.人工审核结果 }),
        });
        if (res.ok) {
          latest.人工审核结果 = reviewed.人工审核结果;
          ElMessage.success('已复制审核结果到最新记录');
        } else ElMessage.error(res.message || '复制失败');
      } catch (e) { ElMessage.error('复制失败: ' + (e.message || e)); }
      finally { group._copying = false; }
    },
    async deleteOld(group) {
      if (group.count < 2) return ElMessage.warning('仅一条记录，无需删除');
      const oldRecs = group.records.slice(1);
      await ElMessageBox.confirm(
        `确认删除 ${oldRecs.length} 条旧报错记录，仅保留最新一条？`,
        '删除确认', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' });
      group._deleting = true;
      try {
        const ids = oldRecs.map(r => r.record_id);
        const res = await api('/api/test/data_multi_errors_delete_old', {
          method: 'POST', body: JSON.stringify({ record_ids: ids }),
        });
        if (res.ok) {
          group.records = [group.records[0]];
          group.count = 1;
          ElMessage.success(res.message || '删除完成');
        } else ElMessage.error(res.message || '删除失败');
      } catch (e) { ElMessage.error('删除失败: ' + (e.message || e)); }
      finally { group._deleting = false; }
    },
    async batchCopyReview() {
      const SKIP_ERR = '时间过滤后日志为空';
      const eligible = [];
      for (const g of this.multiRows) {
        if (g.count < 2) continue;
        const latest = g.records[0];
        if (latest.人工审核结果) continue;
        if ((latest.错误分类 || '').includes(SKIP_ERR)) continue;
        const src = g.records.find(r => r.人工审核结果 && r.错误分类 === latest.错误分类);
        if (src) eligible.push({ g, latest, src });
      }
      if (!eligible.length) return ElMessage.info('没有符合条件的记录可复制');
      await ElMessageBox.confirm(`将复制 ${eligible.length} 条审核结果到最新记录，确认？`,
        '批量复制确认', { type: 'info', confirmButtonText: '确认复制', cancelButtonText: '取消' });
      this.batchCopying = true;
      let ok = 0;
      for (const { g, latest, src } of eligible) {
        g._copying = true;
        try {
          const res = await api('/api/test/data_multi_errors_copy_review', {
            method: 'POST',
            body: JSON.stringify({ record_id: latest.record_id, review: src.人工审核结果 }),
          });
          if (res.ok) { latest.人工审核结果 = src.人工审核结果; ok++; }
        } catch (e) { /* 继续处理下一条 */ }
        g._copying = false;
      }
      this.batchCopying = false;
      ElMessage.success(`批量复制完成：成功 ${ok} 条`);
    },
    async batchDeleteOld() {
      const groups = this.multiRows.filter(g => g.count >= 2);
      if (!groups.length) return ElMessage.info('没有可删除的旧记录');
      const totalDel = groups.reduce((s, g) => s + g.count - 1, 0);
      await ElMessageBox.confirm(`将删除 ${groups.length} 个 Jira 号的 ${totalDel} 条旧记录，仅保留最新一条，确认？`,
        '批量删除确认', { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' });
      this.batchDeleting = true;
      const allIds = [];
      const gMap = {};
      for (const g of groups) {
        g._deleting = true;
        g.records.slice(1).forEach(r => allIds.push(r.record_id));
        gMap[g.jira] = g;
      }
      try {
        const res = await api('/api/test/data_multi_errors_delete_old', {
          method: 'POST', body: JSON.stringify({ record_ids: allIds }),
        });
        if (res.ok) {
          for (const g of groups) { g.records = [g.records[0]]; g.count = 1; g._deleting = false; }
          this.multiTotalRecs = this.multiRows.reduce((s, g) => s + g.count, 0);
          ElMessage.success(`批量删除完成：${groups.length} 个 Jira 号，${allIds.length} 条旧记录`);
        } else {
          ElMessage.error(res.message || '批量删除失败');
          groups.forEach(g => g._deleting = false);
        }
      } catch (e) {
        ElMessage.error('批量删除失败: ' + (e.message || e));
        groups.forEach(g => g._deleting = false);
      }
      this.batchDeleting = false;
    },
  },
};
</script>

<style scoped>
.data-cleanup { padding: 4px; }
.el-table__expanded-cell { padding: 10px 20px !important; }
</style>
