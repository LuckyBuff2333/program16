<template>
  <div class="obs-home">
    <!-- 观测看板 -->
    <el-card class="obs-home-board" shadow="hover">
      <template #header>
        <span class="obs-section-title">观测看板</span>
      </template>
      <div class="obs-board-content">
        <div class="obs-board-actions">
          <el-space>
            <el-button @click="$emit('navigate', { page: 'obs_dashboard' })">
              📂 打开看板
            </el-button>
            <el-button type="primary" :loading="compileLoading" @click="handleCompile">
              🚀 拉取最新 Case
            </el-button>
          </el-space>
        </div>
        <div class="obs-board-credentials">
          <div class="obs-cred-header">
            <span>⚙️</span>
            <span class="obs-cred-label">COS 凭据设置</span>
          </div>
          <div class="obs-cred-inputs">
            <el-input v-model="secretId" placeholder="SecretId" />
            <el-input v-model="secretKey" placeholder="SecretKey" show-password />
          </div>
          <el-button size="small" style="margin-top: 10px" @click="handleSaveCredentials">保存到 config.json</el-button>
          <p class="obs-cred-hint">凭据保存后落盘本机 config.json (600 权限)，不会上传至任何远程服务。</p>
        </div>
      </div>
    </el-card>

    <!-- Case 档案上传 -->
    <el-card shadow="hover">
      <template #header>
        <span class="obs-section-title">Case 档案上传</span>
      </template>
      <div class="obs-upload-content">
        <div class="obs-upload-actions">
          <el-upload :auto-upload="true" :http-request="handleFileUpload" :limit="1">
            <el-button>📤 选择文件上传</el-button>
          </el-upload>
          <el-input v-model="targetKb" placeholder="目标 KB（知识库名称）" style="width: 260px; margin-top: 10px" />
        </div>
        <div class="obs-upload-rules">
          <div class="obs-rules-header">
            <span>📄</span>
            <span class="obs-rules-label">切片规则说明</span>
          </div>
          <ul class="obs-rules-list">
            <li>标识符切分：以 RTC ID、时间戳、进程名为锚点进行切片</li>
            <li>每个切片最大 512 tokens，重叠 64 tokens</li>
            <li>自动识别日志级别（INFO / WARN / ERROR）并加权</li>
            <li>二进制附件（.bin / .so）跳过，仅索引文本文件</li>
          </ul>
        </div>
      </div>
    </el-card>

    <!-- 最近上传审计 -->
    <el-card shadow="hover">
      <template #header>
        <span class="obs-section-title">最近上传审计</span>
      </template>
      <el-table :data="auditData" size="small" border stripe v-loading="auditLoading"
        :header-cell-style="{ background: '#f5f7fa', color: '#303133', fontWeight: 600 }">
        <el-table-column prop="time" label="时间" width="180" />
        <el-table-column prop="file" label="文件" />
        <el-table-column prop="doc_id" label="doc_id" width="140" />
        <el-table-column prop="cos_hash" label="cos_hash" width="160" />
        <el-table-column prop="result" label="结果" width="100">
          <template #default="{ row }">
            <el-tag type="success" size="small">{{ row.result }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script lang="ts">
import { ElMessage } from 'element-plus'

const API_BASE = ''

export default {
  emits: ['navigate'],
  data() {
    return {
      secretId: '',
      secretKey: '',
      targetKb: '',
      auditData: [] as any[],
      auditLoading: false,
      compileLoading: false,
    }
  },
  mounted() {
    this.loadCredentials()
    this.loadAudits()
  },
  methods: {
    async handleSaveCredentials() {
      if (!this.secretId || !this.secretKey) {
        ElMessage.warning('请填写 SecretId 和 SecretKey')
        return
      }
      try {
        const res = await fetch(`${API_BASE}/api/v1/observability/config`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ secret_id: this.secretId, secret_key: this.secretKey }),
        })
        const json = await res.json()
        if (json.ok) {
          ElMessage.success(json.message)
          this.secretId = ''
          this.secretKey = ''
        } else {
          ElMessage.error(json.message)
        }
      } catch (e: any) {
        ElMessage.error('保存失败: ' + e.message)
      }
    },
    async loadCredentials() {
      try {
        const res = await fetch(`${API_BASE}/api/v1/observability/config`)
        const json = await res.json()
        if (json.ok && json.data?.configured) {
          this.secretId = json.data.secret_id_masked
        }
      } catch { /* 未配置时静默 */ }
    },
    async loadAudits() {
      this.auditLoading = true
      try {
        const res = await fetch(`${API_BASE}/api/v1/observability/upload-audits?page=1&page_size=10`)
        const json = await res.json()
        if (json.ok) {
          this.auditData = json.data.items
        }
      } catch (e: any) {
        console.error('加载审计记录失败:', e)
      } finally {
        this.auditLoading = false
      }
    },
    async handleCompile() {
      this.compileLoading = true
      try {
        const res = await fetch(`${API_BASE}/api/v1/observability/sync`, { method: 'POST' })
        const json = await res.json()
        if (json.ok) {
          const d = json.data
          ElMessage.success(`同步完成: 扫描 ${d.total} 条, 新增 ${d.inserted} 条, 跳过 ${d.skipped} 条`)
        } else {
          ElMessage.error(json.message || '同步失败')
        }
      } catch (e: any) {
        ElMessage.error('拉取失败: ' + e.message)
      } finally {
        this.compileLoading = false
      }
    },
    async handleFileUpload(options: any) {
      const formData = new FormData()
      formData.append('file', options.file)
      formData.append('target_kb', this.targetKb)
      try {
        const res = await fetch(`${API_BASE}/api/v1/observability/upload`, {
          method: 'POST',
          body: formData,
        })
        const json = await res.json()
        if (json.ok) {
          ElMessage.success(`上传成功: doc_id=${json.data.doc_id}`)
          this.loadAudits()
          options.onSuccess?.(json)
        } else {
          ElMessage.error(json.message)
          options.onError?.(new Error(json.message))
        }
      } catch (e: any) {
        ElMessage.error('上传失败: ' + e.message)
        options.onError?.(e)
      }
    },
  },
}
</script>

<style scoped>
.obs-home { display: flex; flex-direction: column; gap: 16px; }
.obs-home-board { border: 2px solid #409eff; }
.obs-section-title { font-weight: 600; color: #303133; font-size: 15px; }
.obs-board-content { display: flex; flex-wrap: wrap; gap: 32px; align-items: flex-start; }
.obs-board-actions { flex-shrink: 0; }
.obs-board-credentials { flex: 1; min-width: 320px; }
.obs-cred-header { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.obs-cred-label { font-size: 13px; font-weight: 500; color: #606266; }
.obs-cred-inputs { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.obs-cred-hint { font-size: 12px; color: #c0c4cc; margin-top: 8px; }
.obs-upload-content { display: flex; flex-wrap: wrap; gap: 24px; align-items: flex-start; }
.obs-upload-actions { flex-shrink: 0; }
.obs-upload-rules {
  flex: 1; min-width: 280px; padding: 16px; border-radius: 8px;
  background: #f5f7fa; border: 1px solid #ebeef5;
}
.obs-rules-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.obs-rules-label { font-size: 13px; font-weight: 500; color: #606266; }
.obs-rules-list { font-size: 12px; color: #909399; line-height: 2; padding-left: 18px; margin: 0; }
</style>
