<template>
  <div>
  <el-tabs :model-value="tab" @update:model-value="$emit('update:tab', $event)" type="border-card" class="online-tabs" @tab-click="activeFailCat = ''">

    <!-- 页签1：流程可视化 -->
    <el-tab-pane label="流程可视化" name="flow">
      <div class="stat-row">
        <div class="stat-card"><div class="num">{{ overview.daily_total || 0 }}</div><div class="label">今日补充总数</div></div>
        <div class="stat-card"><div class="num" style="color:#389e0d">{{ overview.daily_complete || 0 }}</div><div class="label">已完整（5字段全填充）</div></div>
        <div class="stat-card"><div class="num" style="color:#d48806">{{ overview.daily_incomplete || 0 }}</div><div class="label">待补充（字段缺失）</div></div>
        <div class="stat-card"><div class="num" style="color:#b25e09">{{ overview.audited_total || 0 }}</div><div class="label">累计已抽查</div></div>
      </div>
    </el-tab-pane>

    <!-- 页签2：接口设置 -->
    <el-tab-pane label="接口设置" name="config">
      <el-row :gutter="14">
        <el-col :span="8" v-for="item in apiSections" :key="item.key">
          <el-card shadow="never" style="margin-bottom:14px">
            <template #header>
              <div style="display:flex;justify-content:space-between;align-items:center">
                <span style="font-weight:600">{{ item.title }}</span>
                <div style="display:flex;align-items:center;gap:8px">
                  <el-button size="small" type="primary" link @click="openAddField(item.key)">+ 添加字段</el-button>
                  <el-switch v-if="config[item.key].mock !== undefined" v-model="config[item.key].mock" :active-text="'Mock'" inline-prompt></el-switch>
                </div>
              </div>
            </template>
            <div style="overflow-x:auto">
            <el-form label-width="90px" size="small" style="min-width:260px">
              <template v-for="(val, field) in config[item.key]">
                <template v-if="field !== 'mock'">
                  <el-form-item v-if="typeof val === 'number'">
                    <template #label><el-tooltip :content="field" placement="top" :disabled="field.length < 8"><span>{{ fieldLabel(field) }}</span></el-tooltip></template>
                    <div class="cfg-field-row">
                      <el-input-number v-model="config[item.key][field]" :min="0" :step="val < 1 ? 0.05 : 1"></el-input-number>
                      <span class="field-del-btn" title="删除字段" @click="removeField(item.key, field)">&#x2715;</span>
                    </div>
                  </el-form-item>
                  <el-form-item v-else-if="typeof val === 'boolean'">
                    <template #label><el-tooltip :content="field" placement="top" :disabled="field.length < 8"><span>{{ fieldLabel(field) }}</span></el-tooltip></template>
                    <div class="cfg-field-row">
                      <el-switch v-model="config[item.key][field]"></el-switch>
                      <span class="field-del-btn" title="删除字段" @click="removeField(item.key, field)">&#x2715;</span>
                    </div>
                  </el-form-item>
                  <el-form-item v-else-if="field.includes('token') || field.includes('password') || field.includes('api_key') || field.includes('secret')">
                    <template #label><el-tooltip :content="field" placement="top" :disabled="field.length < 8"><span>{{ fieldLabel(field) }}</span></el-tooltip></template>
                    <div class="cfg-field-row">
                      <el-input v-model="config[item.key][field]" type="password" show-password :placeholder="val || '可选'"></el-input>
                      <span class="field-del-btn" title="删除字段" @click="removeField(item.key, field)">&#x2715;</span>
                    </div>
                  </el-form-item>
                  <el-form-item v-else-if="Array.isArray(val)">
                    <template #label><el-tooltip :content="field" placement="top" :disabled="field.length < 8"><span>{{ fieldLabel(field) }}</span></el-tooltip></template>
                    <div class="cfg-field-row" style="flex-direction:column;align-items:stretch">
                      <el-input type="textarea" :rows="Math.min(val.length + 1, 6)"
                        :model-value="(val || []).join('\n')"
                        @update:model-value="v => config[item.key][field] = v.split('\n').map(s => s.trim()).filter(Boolean)"
                        placeholder="每行一个"></el-input>
                      <span class="field-del-btn" title="删除字段" @click="removeField(item.key, field)" style="align-self:flex-end">&#x2715;</span>
                    </div>
                  </el-form-item>
                  <el-form-item v-else-if="val !== null && typeof val === 'object' && !Array.isArray(val)">
                    <template #label><el-tooltip :content="field" placement="top" :disabled="field.length < 8"><span>{{ fieldLabel(field) }}</span></el-tooltip></template>
                    <div style="width:100%;border:1px solid #e4e7ed;border-radius:4px;padding:6px;background:#fafafa">
                      <div v-for="(subVal, subKey) in val" :key="subKey" v-show="subKey !== '_newKey'" style="display:flex;align-items:center;gap:4px;margin-bottom:4px">
                        <span style="min-width:50px;font-size:11px;color:#606266">{{ subKey }}</span>
                        <el-input v-model="config[item.key][field][subKey]" size="small" :placeholder="subVal || '可选'"></el-input>
                        <span class="field-del-btn" title="删除子项" @click="delete config[item.key][field][subKey]">&#x2715;</span>
                      </div>
                      <div style="display:flex;gap:4px;margin-top:4px">
                        <el-input v-model="config[item.key][field]._newKey" size="small" placeholder="新键名" style="width:100px" @keyup.enter="addSubField(item.key, field)"></el-input>
                        <el-button size="small" link type="primary" @click="addSubField(item.key, field)">+ 添加</el-button>
                      </div>
                    </div>
                  </el-form-item>
                  <el-form-item v-else>
                    <template #label><el-tooltip :content="field" placement="top" :disabled="field.length < 8"><span>{{ fieldLabel(field) }}</span></el-tooltip></template>
                    <div class="cfg-field-row">
                      <el-input v-model="config[item.key][field]" :placeholder="val || '可选'"></el-input>
                      <span class="field-del-btn" title="删除字段" @click="removeField(item.key, field)">&#x2715;</span>
                    </div>
                  </el-form-item>
                </template>
              </template>
            </el-form>
            </div>
          </el-card>
        </el-col>
      </el-row>
    </el-tab-pane>

    <!-- 页签：数据统计 -->
    <el-tab-pane label="数据统计" name="stats">
      <el-tabs v-model="statsTab" type="card" style="margin-top:-4px">
        <el-tab-pane label="错误统计" name="error_stats">
          <div style="padding:12px 0">
            <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px;flex-wrap:wrap">
              <el-date-picker v-model="errorStats.afterTime" type="datetime" placeholder="分析完成时间起点（留空则全量）"
                format="YYYY-MM-DD HH:mm" value-format="YYYY-MM-DD HH:mm:ss" size="default" style="width:280px" clearable></el-date-picker>
              <el-button type="primary" :loading="errorStats.querying" @click="queryErrorStats(true)">按时间查询</el-button>
              <el-button :loading="errorStats.querying" @click="queryErrorStats(false)">全量查询</el-button>
            </div>
            <div v-if="errorStats.queryMsg" style="display:flex;align-items:center;gap:10px;margin-bottom:10px;padding:8px 14px;background:#f5f7fa;border-radius:8px;flex-wrap:wrap">
              <el-tag :type="errorStats.queryError ? 'danger' : 'success'" size="small">{{ errorStats.queryMsg }}</el-tag>
              <el-select v-model="errorStats.successFilter" placeholder="筛选分析状态" style="width:160px" size="small" clearable>
                <el-option label="全部" value=""></el-option>
                <el-option label="有分析成功" value="yes"></el-option>
                <el-option label="无分析成功" value="no"></el-option>
              </el-select>
              <el-button size="small" @click="copyFilteredJiras" :disabled="!filteredErrorStatsRecords.length">
                复制 Jira 号（{{ filteredErrorStatsRecords.length }}）
              </el-button>
              <el-button type="danger" size="small" plain :loading="errorStats.deletingDirty" @click="deleteDirtyData">
                批量删除脏数据
              </el-button>
            </div>
            <el-table v-if="filteredErrorStatsRecords.length" :data="filteredErrorStatsRecords" size="small" stripe border max-height="480"
              :header-cell-style="{background:'#f5f7fa',color:'#303133',fontWeight:600}">
              <el-table-column type="index" label="#" width="50"></el-table-column>
              <el-table-column prop="jira号" label="Jira号" width="140"></el-table-column>
              <el-table-column prop="失败次数" label="失败次数" width="80" align="center">
                <template #default="{row}">
                  <el-tag :type="row['失败次数']>=3?'danger':row['失败次数']>=2?'warning':'info'" size="small" round>{{ row['失败次数'] }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="是否有分析成功" width="120" align="center">
                <template #default="{row}">
                  <el-tag :type="row['有成功记录']?'success':'danger'" size="small">{{ row['有成功记录'] ? '是' : '否' }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="最新人工审核原因" label="最新人工审核原因" min-width="260" show-overflow-tooltip>
                <template #default="{row}"><span v-if="row['最新人工审核原因']">{{ row['最新人工审核原因'] }}</span><span v-else style="color:#c0c4cc">-</span></template>
              </el-table-column>
              <el-table-column prop="gmlogger文件" label="gmlogger文件" min-width="220" show-overflow-tooltip>
                <template #default="{row}"><span v-if="row['gmlogger文件']" style="font-size:12px">{{ row['gmlogger文件'] }}</span><span v-else style="color:#c0c4cc">-</span></template>
              </el-table-column>
              <el-table-column prop="最新失败时间" label="最新失败时间" width="160"></el-table-column>
            </el-table>
            <el-empty v-else-if="!errorStats.querying && errorStats.queryMsg && !errorStats.queryError" description="无匹配记录" :image-size="60" style="padding:40px 0"></el-empty>
          </div>
        </el-tab-pane>
        <el-tab-pane label="性能数据统计" name="config_tuning">
          <ConfigTuningPanel embedded style="padding-top:4px" />
        </el-tab-pane>
      </el-tabs>
    </el-tab-pane>

    <!-- 页签：数据看板 -->
    <el-tab-pane label="数据看板" name="data">
      <DataDashboardPanel />
    </el-tab-pane>

  </el-tabs>

  <!-- 添加配置字段弹窗 -->
  <el-dialog v-model="showAddFieldDialog" title="添加配置字段" width="420px">
    <el-form label-width="80px">
      <el-form-item label="所属配置">
        <el-tag>{{ apiSections.find(s => s.key === newForm.section)?.title || newForm.section }}</el-tag>
      </el-form-item>
      <el-form-item label="字段名称" required>
        <el-input v-model="newForm.fieldName" placeholder="英文 key，如 headers、retry_count"></el-input>
      </el-form-item>
      <el-form-item label="字段类型">
        <el-select v-model="newForm.fieldType">
          <el-option label="文本 (String)" value="string"></el-option>
          <el-option label="数字 (Number)" value="number"></el-option>
          <el-option label="布尔 (Boolean)" value="boolean"></el-option>
        </el-select>
      </el-form-item>
      <el-form-item label="字段值">
        <el-switch v-if="newForm.fieldType === 'boolean'" v-model="newForm.fieldValueBool"></el-switch>
        <el-input-number v-else-if="newForm.fieldType === 'number'" v-model="newForm.fieldValueNum" style="width:100%"></el-input-number>
        <el-input v-else v-model="newForm.fieldValue" placeholder="字段值（可留空）"></el-input>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="showAddFieldDialog = false">取消</el-button>
      <el-button type="primary" @click="confirmAddField">确认添加</el-button>
    </template>
  </el-dialog>
  </div>
</template>

<script lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus';
import { api, colWidth, verdictStyle, fieldLabel } from '../composables/utils';
import ConfigTuningPanel from '../panels/ConfigTuningPanel.vue';
import DataDashboardPanel from '../panels/DataDashboardPanel.vue';

export default {
  name: 'OnlinePage',
  components: { ConfigTuningPanel, DataDashboardPanel },
  props: {
    tab: { type: String, default: 'flow' },
  },
  emits: ['update:tab'],
  data() {
    return {
      activeFailCat: '',
      statsTab: 'error_stats',
      overview: { mock: {} as any, daily_total: 0, daily_complete: 0, daily_incomplete: 0, audited_total: 0, today: '' },
      config: { prod_ai: {} as any, ai_log_api: {} as any, jira_api: {} as any, diana: {} as any, feishu_bitable: {} as any, feishu_bot: {} as any, knowledge_base_api: {} as any, similarity: {} as any, audit: {} as any, database: {} as any },
      apiSections: [
        { key: 'prod_ai', title: '线上AI日志分析接口' },
        { key: 'ai_log_api', title: 'AI日志分析工具接口(PC)' },
        { key: 'jira_api', title: 'Jira RESTAPI' },
        { key: 'diana', title: 'Diana大模型接口' },
        { key: 'feishu_bitable', title: '飞书多维表格' },
        { key: 'feishu_bot', title: '飞书机器人' },
        { key: 'knowledge_base_api', title: '知识库入库接口' },
      ],
      running: { saveConfig: false },
      errorStats: {
        afterTime: '', querying: false, records: [], queryMsg: '', queryError: false,
        successFilter: '', deletingDirty: false,
      },
      newForm: { section: '', fieldName: '', fieldType: 'string', fieldValue: '', fieldValueNum: 0, fieldValueBool: false },
      showAddFieldDialog: false,

    };
  },
  mounted() {
    this.loadConfig();
    this.loadOverview();
  },
  computed: {
    filteredErrorStatsRecords() {
      const records = this.errorStats.records;
      const filter = this.errorStats.successFilter;
      if (!filter) return records;
      if (filter === 'yes') return records.filter(r => r['有成功记录']);
      if (filter === 'no') return records.filter(r => !r['有成功记录']);
      return records;
    },
  },
  methods: {
    colWidth, verdictStyle, fieldLabel,
    async loadConfig() {
      const body = await api('/api/config');
      this.config = { ...this.config, ...(body.data || {}) };
    },
    async saveConfig() {
      this.running.saveConfig = true;
      try {
        const payload: Record<string, any> = {};
        this.apiSections.forEach(s => {
          payload[s.key] = JSON.parse(JSON.stringify(this.config[s.key] || {}));
          if (payload[s.key].enabled !== undefined) payload[s.key].enabled = !payload[s.key].mock;
          Object.values(payload[s.key]).forEach((v: any) => { if (v && typeof v === 'object' && !Array.isArray(v)) delete v._newKey; });
        });
        payload.similarity = this.config.similarity;
        payload.database = this.config.database;
        payload.audit = this.config.audit;
        payload.output = (this.config as any).output;
        const body = await api('/api/config', { method: 'POST', body: JSON.stringify(payload) });
        ElMessage.success(body.message);
        await this.loadOverview();
      } catch (e) { /* 错误已提示 */ } finally { this.running.saveConfig = false; }
    },
    openAddField(sectionKey: string) {
      this.newForm = { section: sectionKey, fieldName: '', fieldType: 'string', fieldValue: '', fieldValueNum: 0, fieldValueBool: false };
      this.showAddFieldDialog = true;
    },
    confirmAddField() {
      const name = this.newForm.fieldName.trim();
      if (!name) return ElMessage.warning('请输入字段名称');
      if (this.config[this.newForm.section][name] !== undefined) return ElMessage.warning(`字段 "${name}" 已存在，请更换名称`);
      let value: any;
      if (this.newForm.fieldType === 'number') value = this.newForm.fieldValueNum;
      else if (this.newForm.fieldType === 'boolean') value = this.newForm.fieldValueBool;
      else value = this.newForm.fieldValue;
      this.config[this.newForm.section][name] = value;
      this.showAddFieldDialog = false;
      ElMessage.success(`已添加字段 "${name}"`);
    },
    removeField(sectionKey: string, fieldName: string) {
      ElMessageBox.confirm(`确认删除字段 "${fieldName}"？`, '删除确认', {
        confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning',
      }).then(() => {
        delete this.config[sectionKey][fieldName];
        this.config[sectionKey] = { ...this.config[sectionKey] };
        ElMessage.success(`已删除字段 "${fieldName}"`);
      }).catch(() => {});
    },
    addSubField(sectionKey: string, fieldName: string) {
      const obj = this.config[sectionKey][fieldName] as any;
      const newKey = (obj._newKey || '').trim();
      if (!newKey) return;
      if (obj[newKey] !== undefined) return ElMessage.warning(`子键 "${newKey}" 已存在`);
      obj[newKey] = '';
      delete obj._newKey;
      this.config[sectionKey][fieldName] = { ...obj };
    },
    async loadOverview() {
      try { const body = await api('/api/overview'); this.overview = body.data; } catch (_) {}
    },
    async queryErrorStats(useTime) {
      const afterTime = useTime ? (this.errorStats.afterTime || '') : '';
      if (useTime && !afterTime) return ElMessage.warning('请选择分析完成时间起点');
      this.errorStats.querying = true;
      this.errorStats.records = [];
      this.errorStats.queryMsg = '';
      this.errorStats.queryError = false;
      try {
        const resp = await api('/api/test/error_stats', {
          method: 'POST', body: JSON.stringify({ after_time: afterTime }),
        });
        this.errorStats.records = resp.data.rows || [];
        this.errorStats.queryMsg = `统计到 ${resp.data.count || 0} 个 Jira 号存在失败记录`;
      } catch (e) {
        this.errorStats.queryMsg = '查询失败: ' + e.message;
        this.errorStats.queryError = true;
      } finally { this.errorStats.querying = false; }
    },
    async copyFilteredJiras() {
      const records = this.filteredErrorStatsRecords;
      if (!records.length) return ElMessage.warning('无数据可复制');
      const text = records.map(r => r['jira号']).filter(Boolean).join('\n');
      try {
        await navigator.clipboard.writeText(text);
        ElMessage.success(`已复制 ${records.length} 个 Jira 号`);
      } catch (e) {
        const ta = document.createElement('textarea');
        ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
        document.body.appendChild(ta); ta.select(); document.execCommand('copy');
        document.body.removeChild(ta);
        ElMessage.success(`已复制 ${records.length} 个 Jira 号`);
      }
    },
    async deleteDirtyData() {
      const records = this.filteredErrorStatsRecords;
      const targetRecords = records.filter(r =>
        r['有成功记录'] && r['最新人工审核原因'] && r['最新人工审核原因'].includes('时间添加为')
      );
      if (!targetRecords.length) {
        return ElMessage.warning('无符合条件的数据（需要有分析成功且审核原因包含"时间添加为"）');
      }
      const jiraIds = targetRecords.map(r => r['jira号']);
      try {
        await ElMessageBox.confirm(
          `将从飞书多维表格中删除 ${jiraIds.length} 个 Jira 号的所有失败记录（此操作不可撤销），是否继续？`,
          '确认删除多维表格数据', { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' }
        );
      } catch { return; }
      this.errorStats.deletingDirty = true;
      try {
        const body = await api('/api/test/delete_dirty_data', {
          method: 'POST', body: JSON.stringify({ jira_ids: jiraIds })
        });
        ElMessage.success(body.message || `已删除 ${body.data?.deleted_count || 0} 条记录`);
        if (this.errorStats.afterTime) { await this.queryErrorStats(); }
      } catch (e) {
        ElMessage.error('删除失败: ' + (e.message || '未知错误'));
      } finally { this.errorStats.deletingDirty = false; }
    },

  },
};
</script>
