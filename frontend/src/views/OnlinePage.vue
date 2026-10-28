<template>
  <div>
  <el-tabs :model-value="tab" @update:model-value="$emit('update:tab', $event)" type="border-card" class="online-tabs" @tab-click="activeFailCat = ''">

    <!-- 页签1：任务总览 -->
    <el-tab-pane label="任务总览" name="flow">
      <div class="to-head">
        <span class="to-title">任务总览</span>
        <el-button :loading="toLoading" @click="refreshTaskOverview" round size="small" style="margin-left:10px">
          <span v-if="!toLoading" style="margin-right:2px">↻</span> 刷新
        </el-button>
      </div>
      <div v-if="toLoaded || toLoading" class="to-grid">
        <div class="to-card to-click" :class="{ 'is-active': activeCat === 'total' }" style="--accent:#409eff;--bg:linear-gradient(135deg,#e8f4fd,#f0f7ff)" @click="selectCategory('total')">
          <div class="to-icon">📦</div>
          <div class="to-body"><div class="to-value">{{ taskOv.total }}</div><div class="to-label">今日执行总数</div></div>
          <div class="to-foot">去重 Jira 号</div>
        </div>
        <div class="to-card to-click" :class="{ 'is-active': activeCat === 'success' }" style="--accent:#16a34a;--bg:linear-gradient(135deg,#f0fdf4,#ecfdf5)" @click="selectCategory('success')">
          <div class="to-icon">✅</div>
          <div class="to-body"><div class="to-value" style="color:#16a34a">{{ taskOv.success.count }}</div><div class="to-label">成功数量</div></div>
          <div class="to-foot">多维表格分析成功</div>
        </div>
        <div class="to-card to-click" :class="{ 'is-active': activeCat === 'analyzing' }" style="--accent:#d97706;--bg:linear-gradient(135deg,#fffbeb,#fef3c7)" @click="selectCategory('analyzing')">
          <div class="to-icon">⏳</div>
          <div class="to-body"><div class="to-value" style="color:#d97706">{{ taskOv.analyzing.count }}</div><div class="to-label">分析中</div></div>
          <div class="to-foot">多维表格暂无数据</div>
        </div>
        <div class="to-card to-click" :class="{ 'is-active': activeCat === 'investigate' }" style="--accent:#dc2626;--bg:linear-gradient(135deg,#fef2f2,#fee2e2)" @click="selectCategory('investigate')">
          <div class="to-icon">🔍</div>
          <div class="to-body"><div class="to-value" style="color:#dc2626">{{ taskOv.investigate.count }}</div><div class="to-label">待排查</div></div>
          <div class="to-foot">执行失败且分析失败</div>
        </div>
        <div class="to-card to-click" :class="{ 'is-active': activeCat === 'retry' }" style="--accent:#7c3aed;--bg:linear-gradient(135deg,#f5f3ff,#ede9fe)" @click="selectCategory('retry')">
          <div class="to-icon">🔄</div>
          <div class="to-body"><div class="to-value" style="color:#7c3aed">{{ taskOv.retry.count }}</div><div class="to-label">待重试</div></div>
          <div class="to-foot">执行成功但分析失败</div>
        </div>
      </div>
      <el-empty v-else-if="!toLoading" description="点击刷新加载任务总览" :image-size="60" />

      <!-- 任务总览详情表格 -->
      <div v-if="activeCat && activeRows.length > 0" class="to-table-section" ref="toTable">
        <div class="to-table-head">
          <span class="to-table-title">{{ activeCatTitle }}</span>
          <span class="to-table-count">{{ activeRows.length }} 条</span>
        </div>
        <el-table :data="activeRows" size="small" stripe border :max-height="tableMaxHeight"
          :header-cell-style="{background:'#f5f7fa',color:'#303133',fontWeight:600}" style="width:100%">
          <el-table-column type="index" label="#" width="50" />
          <el-table-column prop="jira" label="Jira号" width="150" />
          <!-- 执行总数：分析状态 -->
          <template v-if="activeCat === 'total'">
            <el-table-column prop="status" label="分析状态" min-width="120" align="center">
              <template #default="{row}">
                <el-tag :type="row.status === '分析完成' ? 'success' : row.status === '分析中' ? 'warning' : 'danger'" size="small" round>{{ row.status }}</el-tag>
              </template>
            </el-table-column>
          </template>
          <!-- 成功：总耗时 -->
          <template v-else-if="activeCat === 'success'">
            <el-table-column prop="duration" label="总耗时" min-width="140" />
          </template>
          <!-- 分析中：执行时间、触发时间 -->
          <template v-else-if="activeCat === 'analyzing'">
            <el-table-column prop="exec_time" label="执行时间" width="180" />
            <el-table-column prop="trigger_time" label="触发时间" min-width="180" />
          </template>
          <!-- 待排查：分析完成时间、错误信息 -->
          <template v-else-if="activeCat === 'investigate'">
            <el-table-column prop="done_time" label="分析完成时间" width="180" />
            <el-table-column prop="error_info" label="错误信息" min-width="260" show-overflow-tooltip />
          </template>
          <!-- 待重试：分析完成时间、人工审核结果 -->
          <template v-else-if="activeCat === 'retry'">
            <el-table-column prop="done_time" label="分析完成时间" width="180" />
            <el-table-column prop="human_review" label="人工审核结果" min-width="200" show-overflow-tooltip />
          </template>
        </el-table>
      </div>
      <div v-else-if="activeCat && activeRows.length === 0" style="text-align:center;padding:40px 0;color:#909399">
        该分类暂无数据
      </div>
    </el-tab-pane>

    <!-- 页签2：接口设置 -->
    <el-tab-pane label="接口设置" name="config">
      <div class="cfg-toolbar">
        <span class="cfg-toolbar-hint">
          密钥/令牌类字段不回显，留空表示保持原值；删除字段与新增字段均需点「保存配置」后生效
          <b v-if="sensitivePaths.length">（已隐藏 {{ sensitivePaths.length }} 个密钥/令牌字段）</b>
          <b v-if="pendingDeletes.length">（待删除 {{ pendingDeletes.length }} 项）</b>
        </span>
        <div style="display:flex;gap:8px;flex-shrink:0">
          <el-button size="small" :disabled="running.saveConfig" @click="reloadConfig">放弃修改</el-button>
          <el-button size="small" type="primary" :loading="running.saveConfig" @click="saveConfig">保存配置</el-button>
        </div>
      </div>
      <el-row :gutter="14">
        <el-col :span="8" v-for="item in apiSections" :key="item.key">
          <el-card shadow="never" style="margin-bottom:14px">
            <template #header>
              <div style="display:flex;justify-content:space-between;align-items:center">
                <span style="font-weight:600">{{ item.title }}</span>
                <div style="display:flex;align-items:center;gap:8px">
                  <el-button size="small" type="primary" link @click="openAddField(item.key)">+ 添加字段</el-button>
                  <el-switch v-if="config[item.key] && config[item.key].mock !== undefined" v-model="config[item.key].mock" :active-text="'Mock'" inline-prompt></el-switch>
                </div>
              </div>
            </template>
            <div style="overflow-x:auto">
            <el-form label-width="90px" size="small" style="min-width:260px">
              <template v-for="(val, field) in (config[item.key] || {})">
                <template v-if="field !== 'mock'">
                  <!-- 共用凭证：页面只读，后端同样拒绝修改与删除 -->
                  <el-form-item v-if="isLocked(item.key, s(field))">
                    <template #label><el-tooltip :content="s(field)" placement="top" :disabled="s(field).length < 8"><span>{{ fieldLabel(s(field)) }}</span></el-tooltip></template>
                    <div class="cfg-field-row">
                      <el-input :model-value="lockedText(item.key, s(field), val)" disabled></el-input>
                      <el-tag size="small" type="danger" style="flex-shrink:0">锁定</el-tag>
                    </div>
                  </el-form-item>
                  <!-- 留空即复用其它段凭证的字段：只读展示生效值，避免误填覆盖共用配置 -->
                  <el-form-item v-else-if="isFallbackOnly(item.key, s(field), val)">
                    <template #label><el-tooltip :content="s(field)" placement="top" :disabled="s(field).length < 8"><span>{{ fieldLabel(s(field)) }}</span></el-tooltip></template>
                    <div class="cfg-field-row">
                      <el-input :model-value="fallbackText(item.key, s(field))" disabled></el-input>
                      <el-tag size="small" type="info" style="flex-shrink:0">复用</el-tag>
                    </div>
                  </el-form-item>
                  <el-form-item v-else-if="typeof val === 'number'">
                    <template #label><el-tooltip :content="field" placement="top" :disabled="s(field).length < 8"><span>{{ fieldLabel(s(field)) }}</span></el-tooltip></template>
                    <div class="cfg-field-row">
                      <el-input-number v-model="config[item.key][field]" :min="0" :step="val < 1 ? 0.05 : 1"></el-input-number>
                      <span class="field-del-btn" title="删除字段" @click="removeField(item.key, s(field))">&#x2715;</span>
                    </div>
                  </el-form-item>
                  <el-form-item v-else-if="typeof val === 'boolean'">
                    <template #label><el-tooltip :content="field" placement="top" :disabled="s(field).length < 8"><span>{{ fieldLabel(s(field)) }}</span></el-tooltip></template>
                    <div class="cfg-field-row">
                      <el-switch v-model="config[item.key][field]"></el-switch>
                      <span class="field-del-btn" title="删除字段" @click="removeField(item.key, s(field))">&#x2715;</span>
                    </div>
                  </el-form-item>
                  <el-form-item v-else-if="isSensitive(s(field))">
                    <template #label><el-tooltip :content="s(field)" placement="top" :disabled="s(field).length < 8"><span>{{ fieldLabel(s(field)) }}</span></el-tooltip></template>
                    <div class="cfg-field-row">
                      <el-input :model-value="secretDraft[secretKey(item.key, s(field))] || ''"
                        @update:model-value="(v) => setSecret(item.key, s(field), v)"
                        type="password" show-password
                        :placeholder="fieldPlaceholder(item.key, s(field), val)"></el-input>
                      <span class="field-del-btn" title="删除字段" @click="removeField(item.key, s(field))">&#x2715;</span>
                    </div>
                  </el-form-item>
                  <el-form-item v-else-if="Array.isArray(val) && val.length && typeof val[0] === 'object'">
                    <template #label><el-tooltip :content="field" placement="top" :disabled="s(field).length < 8"><span>{{ fieldLabel(s(field)) }}</span></el-tooltip></template>
                    <div style="width:100%">
                      <div v-for="(row, idx) in config[item.key][field]" :key="idx" style="display:flex;gap:4px;margin-bottom:4px;align-items:center">
                        <span style="min-width:20px;font-size:11px;color:#909399">{{ idx + 1 }}</span>
                        <el-input v-for="(subVal, subKey) in row" :key="subKey" v-model="config[item.key][field][idx][subKey]" size="small" :placeholder="s(subKey)" style="flex:1" />
                        <el-button size="small" type="danger" link @click="config[item.key][field].splice(idx, 1)">✕</el-button>
                      </div>
                      <el-button size="small" link type="primary" @click="config[item.key][field].push({})">+ 添加条目</el-button>
                    </div>
                  </el-form-item>
                  <el-form-item v-else-if="Array.isArray(val)">
                    <template #label><el-tooltip :content="field" placement="top" :disabled="s(field).length < 8"><span>{{ fieldLabel(s(field)) }}</span></el-tooltip></template>
                    <div class="cfg-field-row" style="flex-direction:column;align-items:stretch">
                      <el-input type="textarea" :rows="Math.min(val.length + 1, 6)"
                        :model-value="(val || []).join('\n')"
                        @update:model-value="updateArrayField.bind(null, item.key, s(field))"
                        placeholder="每行一个"></el-input>
                      <span class="field-del-btn" title="删除字段" @click="removeField(item.key, s(field))" style="align-self:flex-end">&#x2715;</span>
                    </div>
                  </el-form-item>
                  <el-form-item v-else-if="val !== null && typeof val === 'object' && !Array.isArray(val)">
                    <template #label><el-tooltip :content="field" placement="top" :disabled="s(field).length < 8"><span>{{ fieldLabel(s(field)) }}</span></el-tooltip></template>
                    <div style="width:100%;border:1px solid #e4e7ed;border-radius:4px;padding:6px;background:#fafafa">
                      <div v-for="(subVal, subKey) in val" :key="subKey" v-show="subKey !== '_newKey'" style="display:flex;align-items:center;gap:4px;margin-bottom:4px">
                        <span style="min-width:50px;font-size:11px;color:#606266">{{ subKey }}</span>
                        <el-input v-model="config[item.key][field][subKey]" size="small" :placeholder="subVal || '可选'"></el-input>
                        <span class="field-del-btn" title="删除子项" @click="removeSubField(item.key, s(field), s(subKey))">&#x2715;</span>
                      </div>
                      <div style="display:flex;gap:4px;margin-top:4px">
                        <el-input v-model="config[item.key][field]._newKey" size="small" placeholder="新键名" style="width:100px" @keyup.enter="addSubField(item.key, s(field))"></el-input>
                        <el-button size="small" link type="primary" @click="addSubField(item.key, s(field))">+ 添加</el-button>
                      </div>
                    </div>
                  </el-form-item>
                  <el-form-item v-else>
                    <template #label><el-tooltip :content="s(field)" placement="top" :disabled="s(field).length < 8"><span>{{ fieldLabel(s(field)) }}</span></el-tooltip></template>
                    <div class="cfg-field-row">
                      <el-input v-model="config[item.key][field]" :placeholder="fieldPlaceholder(item.key, s(field), val)"></el-input>
                      <span class="field-del-btn" title="删除字段" @click="removeField(item.key, s(field))">&#x2715;</span>
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
      taskOv: { total: 0, all_rows: [] as any[], success: { count: 0, rows: [] as any[] }, analyzing: { count: 0, rows: [] as any[] }, investigate: { count: 0, rows: [] as any[] }, retry: { count: 0, rows: [] as any[] } } as Record<string, any>,
      toLoading: false,
      toLoaded: false,
      activeCat: '' as string,
      config: {} as Record<string, any>,
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
      // 配置页：敏感字段不回显，用户重新输入才提交；删除项缓存到 pendingDeletes
      sensitivePaths: [] as string[],
      maskToken: '********',
      secretDraft: {} as Record<string, string>,
      pendingDeletes: [] as any[],
      // 留空时会自动复用其它段的字段（如机器人复用多维表格的 App ID/Secret）
      fallbackFields: {} as Record<string, any>,
      // 共用凭证：页面只读（后端也拒绝改/删）
      lockedPaths: [] as string[],
      errorStats: {
        afterTime: '', querying: false, records: [] as any[], queryMsg: '', queryError: false,
        successFilter: '', deletingDirty: false,
      },
      newForm: { section: '', fieldName: '', fieldType: 'string', fieldValue: '', fieldValueNum: 0, fieldValueBool: false },
      showAddFieldDialog: false,

    };
  },
  mounted() {
    this.loadConfig();
    this.loadFlowStats();
    // 任务总览改为手动刷新，不自动加载
  },
  computed: {
    activeRows() {
      if (!this.activeCat) return [];
      if (this.activeCat === 'total') return this.taskOv.all_rows || [];
      return (this.taskOv[this.activeCat] && this.taskOv[this.activeCat].rows) || [];
    },
    activeCatTitle() {
      const map = { total: '今日执行总数', success: '成功数量', analyzing: '分析中', investigate: '待排查', retry: '待重试' } as Record<string, string>;
      return map[this.activeCat] || '';
    },
    tableMaxHeight() {
      const el = this.$refs.toTable;
      if (!el) return 500;
      const rect = (el as unknown as HTMLElement).getBoundingClientRect();
      return Math.max(200, window.innerHeight - rect.top - 60);
    },
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
    // Vue v-for 的 field 类型为 string|number，此辅助方法统一转为 string
    s(v: any): string { return String(v); },
    // 更新数组类型配置字段（从 textarea 换行文本解析）
    updateArrayField(sectionKey: string, fieldName: string, text: string) {
      this.config[sectionKey][fieldName] = text.split('\n').map((s: string) => s.trim()).filter(Boolean);
    },
    async loadConfig() {
      const body = await api('/api/config');
      const data: Record<string, any> = body.data || {};
      this.sensitivePaths = Array.isArray(data._sensitive) ? data._sensitive : [];
      this.maskToken = data._mask || '********';
      this.fallbackFields = data._fallbacks || {};
      this.lockedPaths = Array.isArray(data._locked) ? data._locked : [];
      const rest: Record<string, any> = { ...data };
      delete rest._sensitive;
      delete rest._mask;
      delete rest._fallbacks;
      delete rest._locked;
      this.config = { ...this.config, ...rest };
      this.secretDraft = {};
    },
    async reloadConfig() {
      this.pendingDeletes = [];
      this.secretDraft = {};
      await this.loadConfig();
      ElMessage.success('已重新加载配置，未保存的修改已丢弃');
    },
    // 是否为密钥/令牌类字段（与后端 _is_sensitive_key 判定保持一致）
    isSensitive(field: string): boolean {
      const low = String(field).toLowerCase();
      if (/(_url|_uri|_field|_column|_timeout|_path|_dir)$/.test(low)) return false;
      return /(token|secret|password|passwd|api_key|apikey|app_key|appkey|cookie|credential|private_key)/.test(low);
    },
    secretKey(section: string, field: string): string { return `${section}.${field}`; },
    sectionTitle(key: string): string {
      const item = this.apiSections.find((x: any) => x.key === key);
      return item ? item.title : key;
    },
    // 共用凭证：只读展示，不允许在页面修改或删除
    isLocked(section: string, field: string): boolean {
      return this.lockedPaths.includes(this.secretKey(section, field));
    },
    lockedText(section: string, field: string, val: any): string {
      if (this.isSensitive(field)) return val === this.maskToken ? '已配置（共用，不可修改）' : '未配置';
      return val === undefined || val === null ? '' : String(val);
    },
    // 该字段留空且存在回退来源 → 页面按只读展示生效值（如机器人复用多维表格的 App ID）
    isFallbackOnly(section: string, field: string, val: any): boolean {
      const fb = this.fallbackFields[this.secretKey(section, field)];
      if (!fb) return false;
      return val === undefined || val === null || val === '';
    },
    fallbackText(section: string, field: string): string {
      const fb = this.fallbackFields[this.secretKey(section, field)] || {};
      const fromSection = String(fb.from || '').split('.')[0];
      return `${fb.preview || '已配置'}（复用「${this.sectionTitle(fromSection)}」）`;
    },
    // 占位符要说明“留空会发生什么”，尤其是留空会回退复用其它段凭证的字段
    fieldPlaceholder(section: string, field: string, val: any): string {
      const fb = this.fallbackFields[this.secretKey(section, field)];
      const isEmpty = val === undefined || val === null || val === '';
      if (isEmpty && fb) {
        const fromSection = String(fb.from || '').split('.')[0];
        return `未单独配置，留空则复用「${this.sectionTitle(fromSection)}」（当前：${fb.preview || '未配置'}）`;
      }
      if (this.isSensitive(field)) {
        return val === this.maskToken ? '已配置，留空则不修改' : '未配置，留空则不修改';
      }
      return val || '可选';
    },
    setSecret(section: string, field: string, value: string) {
      this.secretDraft[this.secretKey(section, field)] = value;
    },
    markDeleted(path: any[]) {
      const key = path.join('.');
      if (!this.pendingDeletes.some((p: any[]) => p.join('.') === key)) this.pendingDeletes.push(path);
    },
    dropDeleted(path: any[]) {
      const key = path.join('.');
      this.pendingDeletes = this.pendingDeletes.filter((p: any[]) => p.join('.') !== key);
    },
    // 保存配置：字段级合并 + 显式删除，敏感字段只提交用户重新输入的值
    async saveConfig() {
      this.running.saveConfig = true;
      try {
        const config: Record<string, any> = {};
        this.apiSections.forEach((sec: any) => {
          const section = JSON.parse(JSON.stringify(this.config[sec.key] || {}));
          delete section._newKey;
          Object.values(section).forEach((v: any) => {
            if (v && typeof v === 'object' && !Array.isArray(v)) delete v._newKey;
          });
          // 敏感字段：只有重新输入才下发；占位符/空值一律不提交，由后端保留原值
          // 说明：这里按字段名判定（而不是只看 _sensitive 列表），否则"原本为空"的密钥字段新填值不会被提交
          Object.keys(section).forEach((field: string) => {
            if (!this.isSensitive(field)) return;
            const draft = (this.secretDraft[this.secretKey(sec.key, field)] || '').trim();
            if (draft) section[field] = draft;
            else delete section[field];
          });
          // 只有同时存在 mock 与 enabled 时，才用 mock 派生 enabled（否则会把 enabled 强制改回 true）
          if (section.enabled !== undefined && section.mock !== undefined) section.enabled = !section.mock;
          config[sec.key] = section;
        });
        ['similarity', 'database', 'audit', 'output'].forEach((k: string) => {
          if (this.config[k] !== undefined) config[k] = this.config[k];
        });
        const body = await api('/api/config', {
          method: 'POST',
          body: JSON.stringify({ config, delete: this.pendingDeletes }),
        });
        ElMessage.success(body.message);
        this.pendingDeletes = [];
        await this.loadConfig();
        await this.loadFlowStats();
      } catch (e) { /* 错误已由 api() 统一提示 */ } finally { this.running.saveConfig = false; }
    },
    openAddField(sectionKey: string) {
      if (!this.config[sectionKey]) this.config[sectionKey] = {};
      this.newForm = { section: sectionKey, fieldName: '', fieldType: 'string', fieldValue: '', fieldValueNum: 0, fieldValueBool: false };
      this.showAddFieldDialog = true;
    },
    confirmAddField() {
      const name = this.newForm.fieldName.trim();
      if (!name) return ElMessage.warning('请输入字段名称');
      if (!/^[A-Za-z0-9_.\-]+$/.test(name)) return ElMessage.warning('字段名只能包含字母、数字、下划线、点和短横线');
      if (name.startsWith('_')) return ElMessage.warning('字段名不能以下划线开头');
      if (!this.config[this.newForm.section]) this.config[this.newForm.section] = {};
      const section = this.config[this.newForm.section];
      if (section[name] !== undefined) return ElMessage.warning(`字段 "${name}" 已存在，请更换名称`);
      let value: any;
      if (this.newForm.fieldType === 'number') value = this.newForm.fieldValueNum;
      else if (this.newForm.fieldType === 'boolean') value = this.newForm.fieldValueBool;
      else value = this.newForm.fieldValue;
      this.config[this.newForm.section] = { ...section, [name]: value };
      this.dropDeleted([this.newForm.section, name]);
      this.showAddFieldDialog = false;
      ElMessage.success(`已添加字段 "${name}"，点「保存配置」后生效`);
    },
    removeField(sectionKey: string, fieldName: string) {
      ElMessageBox.confirm(`确认删除字段 "${fieldName}"？点「保存配置」后才会从配置文件移除`, '删除确认', {
        confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning',
      }).then(() => {
        delete this.config[sectionKey][fieldName];
        this.config[sectionKey] = { ...this.config[sectionKey] };
        delete this.secretDraft[this.secretKey(sectionKey, fieldName)];
        this.markDeleted([sectionKey, fieldName]);
        ElMessage.success(`已删除字段 "${fieldName}"，点「保存配置」后生效`);
      }).catch(() => {});
    },
    removeSubField(sectionKey: string, fieldName: string, subKey: string) {
      const obj = this.config[sectionKey] && this.config[sectionKey][fieldName];
      if (!obj || obj[subKey] === undefined) return;
      delete obj[subKey];
      this.config[sectionKey][fieldName] = { ...obj };
      this.markDeleted([sectionKey, fieldName, subKey]);
      ElMessage.success(`已删除子项 "${subKey}"，点「保存配置」后生效`);
    },
    addSubField(sectionKey: string, fieldName: string) {
      const obj = this.config[sectionKey][fieldName] as any;
      const newKey = (obj._newKey || '').trim();
      if (!newKey) return;
      if (obj[newKey] !== undefined) return ElMessage.warning(`子键 "${newKey}" 已存在`);
      obj[newKey] = '';
      delete obj._newKey;
      this.config[sectionKey][fieldName] = { ...obj };
      this.dropDeleted([sectionKey, fieldName, newKey]);
    },
    async loadFlowStats() {
      try { const body = await api('/api/overview'); this.overview = body.data as any; } catch (_) {}
    },
    async loadTaskOverview(force = false) {
      this.toLoading = true;
      try {
        const url = force
          ? '/api/dashboard/task_overview?force=true'
          : '/api/dashboard/task_overview';
        const r = await api(url);
        this.taskOv = r.data as any;
        this.toLoaded = true;
      } catch (e: any) { ElMessage.error('任务总览加载失败: ' + (e?.message || e)); } finally { this.toLoading = false; }
    },
    refreshTaskOverview() { this.loadTaskOverview(true); },
    selectCategory(cat: string) {
      this.activeCat = this.activeCat === cat ? '' : cat;
      if (this.activeCat) {
        this.$nextTick(() => {
          const el = this.$refs.toTable as any;
          if (el) el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        });
      }
    },
    async queryErrorStats(useTime: any) {
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
        this.errorStats.records = (resp.data as any).rows || [];
        this.errorStats.queryMsg = `统计到 ${resp.data.count || 0} 个 Jira 号存在失败记录`;
      } catch (e: any) {
        this.errorStats.queryMsg = '查询失败: ' + (e?.message || e);
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
        if (this.errorStats.afterTime) { await this.queryErrorStats(true); }
      } catch (e: any) {
        ElMessage.error('删除失败: ' + (e?.message || '未知错误'));
      } finally { this.errorStats.deletingDirty = false; }
    },

  },
};
</script>

<style scoped>
/* ── 接口设置工具条 ── */
.cfg-toolbar {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  margin-bottom: 12px; padding: 10px 14px; border-radius: 8px;
  background: #f5f8ff; border: 1px solid #dbe6fb;
}
.cfg-toolbar-hint { font-size: 12px; color: #5a6b8a; line-height: 1.6; }
.cfg-toolbar-hint b { color: #d97706; }
/* ── 任务总览 ── */
.to-head { display: flex; align-items: center; margin-bottom: 16px; }
.to-title { font-size: 16px; font-weight: 700; color: #1f3b73; }
.to-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 14px; margin-bottom: 20px; }
.to-card {
  background: var(--bg, #f5f7fa); border-radius: 12px; padding: 18px 20px;
  display: flex; flex-wrap: wrap; align-items: center; gap: 12px;
  border: 1px solid rgba(0,0,0,.04);
  transition: transform .2s ease, box-shadow .2s ease;
}
.to-card:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(0,0,0,.06); }
.to-click { cursor: pointer; }
.to-click:active { transform: translateY(0); }
.to-click.is-active { border: 2px solid var(--accent); box-shadow: 0 0 0 3px rgba(64,158,255,.12); }
.to-icon { font-size: 28px; line-height: 1; }
.to-body { flex: 1; min-width: 0; }
.to-value { font-size: 26px; font-weight: 800; color: #1a202c; line-height: 1.2; }
.to-label { font-size: 12px; color: #718096; margin-top: 2px; }
.to-foot { width: 100%; font-size: 11px; color: #909399; padding-top: 6px; border-top: 1px solid rgba(0,0,0,.05); }
.to-jira-list { max-height: 420px; overflow-y: auto; display: flex; flex-direction: column; gap: 2px; }
.to-jira-item { padding: 6px 12px; font-size: 13px; font-family: 'Consolas','Monaco',monospace; color: #303133; border-radius: 4px; transition: background .15s ease; }
.to-jira-item:hover { background: #f0f2f5; }
/* ── 详情表格 ── */
.to-table-section { margin-top: 18px; display: flex; flex-direction: column; overflow: hidden; }
.to-table-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.to-table-title { font-size: 14px; font-weight: 700; color: #1f3b73; }
.to-table-count { font-size: 12px; color: #909399; }
@media (max-width: 1100px) { .to-grid { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 700px) { .to-grid { grid-template-columns: repeat(2, 1fr); } }
</style>

<!-- 非 scoped 样式：强制表格铺满宽度 -->
<style>
.to-table-section .el-table { width: 100% !important; }
.to-table-section .el-table__body-wrapper { width: 100% !important; }
.to-table-section table { width: 100% !important; table-layout: fixed !important; }
</style>
