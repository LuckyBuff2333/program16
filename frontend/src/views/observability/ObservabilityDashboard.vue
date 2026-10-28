<template>
  <div class="obs-dash">
    <!-- 统计概览卡片 -->
    <el-card shadow="hover" class="obs-stats-card">
      <template #header>
        <span class="obs-section-title">今日概览</span>
        <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
          <el-button type="primary" size="small" :loading="fetchPcLoading" @click="handleFetchReports('pc')">
            {{ fetchPcLoading ? '拉取中...' : '📦 拉取PC' }}
          </el-button>
          <span v-if="fetchPcProgress" class="fetch-progress">
            ✅ {{ fetchPcProgress.fetched }} | ⏳ {{ fetchPcProgress.remaining }}
          </span>
          <el-button type="warning" size="small" :loading="fetchOnlineLoading" @click="handleFetchReports('online')">
            {{ fetchOnlineLoading ? '拉取中...' : '📦 拉取线上' }}
          </el-button>
          <span v-if="fetchOnlineProgress" class="fetch-progress">
            ✅ {{ fetchOnlineProgress.fetched }} | ⏳ {{ fetchOnlineProgress.remaining }}
          </span>
          <el-button type="success" size="small" :loading="syncLoading" @click="handleSync">
            🔄 同步最新数据
          </el-button>
        </div>
      </template>

    </el-card>

    <!-- 汇总表格 -->
    <el-card shadow="hover">
      <template #header>
        <div class="obs-dash-header">
          <span class="obs-section-title">Case 汇总列表</span>
          <div class="obs-search-bar">
            <el-input
              v-model="searchVcu"
              placeholder="请输入 VCU 号码搜索"
              clearable
              style="width: 240px"
              @keyup.enter="handleSearch"
            />
            <el-button type="primary" @click="handleSearch">搜索</el-button>
            <el-button @click="handleReset">重置</el-button>
          </div>
        </div>
      </template>
      <!-- Tab 切换 -->
      <el-tabs v-model="activeTab" @tab-change="onTabChange">
        <el-tab-pane label="jira_analyze（PC端）" name="jira_analyze" />
        <el-tab-pane label="parseFullTicket（线上）" name="parseFullTicket" />
      </el-tabs>
      <el-table :data="caseList" size="small" border stripe v-loading="loading"
        :header-cell-style="{ background: '#f5f7fa', color: '#303133', fontWeight: 600 }">
        <el-table-column prop="vcu_number" label="VCU号码" width="170" />
        <el-table-column prop="case_id" label="case_id" width="200">
          <template #default="{ row }">
            <a class="obs-case-link" @click="$emit('navigate', { page: 'obs_case', caseId: row.case_id })">
              {{ row.case_id }}
            </a>
          </template>
        </el-table-column>
        <el-table-column prop="finish_time" label="完成时间" width="170" />
        <el-table-column prop="duration" label="耗时" width="100" />
        <el-table-column prop="conf" label="conf" width="180">
          <template #default="{ row }">
            <ConfidenceBar :conf="row.conf" :converged="row.converged" />
          </template>
        </el-table-column>
        <el-table-column prop="case_type" label="案例判定" width="100">
          <template #default="{ row }">
            <el-tag type="primary" size="small">{{ row.case_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="reflow_status" label="回流状态" width="110">
          <template #default="{ row }">
            <el-tag :type="row.reflow_status === '编辑回流' ? 'warning' : 'info'" size="small">
              {{ row.reflow_status }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
      <!-- 分页 -->
      <div class="obs-dash-pagination">
        <el-pagination
          v-model:current-page="page"
          :page-size="pageSize"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="loadCases"
        />
      </div>
    </el-card>
  </div>
</template>

<script lang="ts">
import { ElMessage } from 'element-plus'
import ConfidenceBar from './components/ConfidenceBar.vue'

const API_BASE = ''

export default {
  components: { ConfidenceBar },
  emits: ['navigate'],
  data() {
    return {
      caseList: [] as any[],
      loading: false,
      searchVcu: '',
      page: 1,
      pageSize: 50,
      total: 0,
      syncLoading: false,
      fetchPcLoading: false,
      fetchPcProgress: null as { fetched: number; remaining: number } | null,
      fetchOnlineLoading: false,
      fetchOnlineProgress: null as { fetched: number; remaining: number } | null,
      activeTab: 'parseFullTicket',
      _pollTimer: null as ReturnType<typeof setInterval> | null,
      stats: {
        total: 0,
        analyzed: 0,
        failed: 0,
        pending: 0,
        avg_confidence: 0,
        avg_duration: '',
      },
    }
  },
  mounted() {
    this.loadCases()
    this.loadStats()
  },
  activated() {
    // keep-alive 激活时刷新数据（从详情页返回时）
    this.loadCases()
    this.loadStats()
  },
  beforeUnmount() {
    // (轮询已关闭，仅保留手动同步)
  },
  methods: {
    async handleFetchReports(source: 'pc' | 'online') {
      const isPc = source === 'pc'
      if (isPc) this.fetchPcLoading = true
      else this.fetchOnlineLoading = true
      try {
        const res = await fetch(`${API_BASE}/api/v1/observability/batch_fetch_reports?limit=20&source=${source}`, { method: 'POST' })
        const json = await res.json()
        if (json.ok) {
          const d = json.data
          const prog = { fetched: d.fetched || 0, remaining: d.remaining || 0 }
          if (isPc) this.fetchPcProgress = prog
          else this.fetchOnlineProgress = prog
          const label = isPc ? 'PC' : '线上'
          if (d.total === 0 && d.remaining === 0) {
            ElMessage.success(`${label} 全部拉取完成！共 ${d.fetched} 条`)
          } else {
            ElMessage.success(`${label} 成功 ${d.success}, 跳过 ${d.skip}, 失败 ${d.fail} | 已拉取 ${d.fetched}, 待拉取 ${d.remaining}`)
          }
          this.loadCases()
          this.loadStats()
        } else {
          ElMessage.error(json.message || '拉取失败')
        }
      } catch (e: any) {
        ElMessage.error('拉取失败: ' + (e.message || e))
      } finally {
        if (isPc) this.fetchPcLoading = false
        else this.fetchOnlineLoading = false
      }
    },
    async handleSync() {
      this.syncLoading = true
      try {
        const res = await fetch(`${API_BASE}/api/v1/observability/sync_feishu`, { method: 'POST' })
        const json = await res.json()
        if (json.ok) {
          const d = json.data
          ElMessage.success(`同步完成: 总计 ${d.total}, 新增 ${d.inserted}, 更新 ${d.updated}`)
          this.loadCases()
          this.loadStats()
        } else {
          ElMessage.error(json.message || '同步失败')
        }
      } catch (e: any) {
        ElMessage.error('同步失败: ' + (e.message || e))
      } finally {
        this.syncLoading = false
      }
    },
    async loadStats() {
      try {
        const res = await fetch(`${API_BASE}/api/v1/observability/case_stats`)
        const json = await res.json()
        if (json.ok) {
          this.stats = json.data
        }
      } catch (e) {
        console.error('加载统计数据失败:', e)
      }
    },
    onTabChange() {
      this.searchVcu = ''
      this.page = 1
      this.loadCases()
    },
    async loadCases() {
      this.loading = true
      try {
        const params = new URLSearchParams({
          page: String(this.page),
          page_size: String(this.pageSize),
          task_type: this.activeTab,
        })
        if (this.searchVcu.trim()) {
          params.set('vcu_number', this.searchVcu.trim())
        }
        const res = await fetch(`${API_BASE}/api/v1/observability/cases?${params}`)
        const json = await res.json()
        if (json.ok) {
          this.caseList = json.data.list
          this.total = json.data.total || 0
        }
      } catch (e) {
        console.error('加载 Case 列表失败:', e)
      } finally {
        this.loading = false
      }
    },
    handleSearch() {
      this.page = 1
      this.loadCases()
    },
    handleReset() {
      this.searchVcu = ''
      this.page = 1
      this.loadCases()
    },
  },
}
</script>

<style scoped>
.obs-dash { display: flex; flex-direction: column; gap: 16px; }
.obs-dash-header {
  display: flex; align-items: center; justify-content: space-between;
}
.obs-section-title { font-weight: 600; color: #303133; font-size: 15px; }
.fetch-progress { font-size: 13px; color: #67c23a; font-weight: 500; white-space: nowrap; }
.obs-search-bar { display: flex; align-items: center; gap: 8px; }
.obs-dash-pagination {
  display: flex; justify-content: flex-end; margin-top: 16px;
}
.obs-case-link {
  color: #409eff; font-family: monospace; font-size: 13px; cursor: pointer;
  text-decoration: none;
}
.obs-case-link:hover { color: #66b1ff; text-decoration: underline; }
</style>
