<template>
  <div class="test-panel">
    <div class="section-title">App.log 下载</div>
    <el-alert type="info" :closable="false"
      title="从内网服务器拉取 app.log 并保存到本地 logs/ 目录，完成后可直接打开目录查看。" />

    <el-card shadow="never" style="margin-top:14px">
      <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap">
        <el-button type="primary" :loading="downloading" @click="downloadLog" :disabled="downloading">
          <span v-if="!downloading" style="margin-right:4px">⬇</span>
          {{ downloading ? '拉取中...' : '拉取 app.log' }}
        </el-button>
        <el-button type="success" plain @click="openFolder">
          📂 打开目录
        </el-button>
        <span v-if="statusMsg" :style="{ color: statusOk ? '#67c23a' : '#f56c6c', fontSize: '13px' }">{{ statusMsg }}</span>
      </div>
      <div v-if="savedPath" style="margin-top:12px;padding:10px 14px;background:#f5f7fa;border-radius:6px;font-size:12px;color:#606266;display:flex;align-items:center;gap:8px">
        <span style="color:#909399">保存位置：</span>
        <code style="color:#303133;word-break:break-all">{{ savedPath }}</code>
      </div>
    </el-card>

    <el-card shadow="never" style="margin-top:14px" v-if="downloadHistory.length">
      <div style="font-weight:600;margin-bottom:10px;font-size:13px">拉取历史</div>
      <el-table :data="downloadHistory" size="small" stripe border max-height="260">
        <el-table-column type="index" label="#" width="50" />
        <el-table-column prop="time" label="时间" width="180" />
        <el-table-column prop="status" label="状态" width="100" align="center">
          <template #default="{row}">
            <el-tag :type="row.status === '成功' ? 'success' : 'danger'" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="message" label="备注" min-width="200" show-overflow-tooltip />
      </el-table>
    </el-card>
  </div>
</template>

<script lang="ts">
// @ts-nocheck
import { ElMessage } from 'element-plus';

export default {
  name: 'AppLogDownloadPanel',
  data() {
    return {
      downloading: false,
      statusMsg: '',
      statusOk: false,
      savedPath: '',
      downloadHistory: [] as Array<{ time: string; status: string; message: string }>,
    };
  },
  methods: {
    async downloadLog() {
      this.downloading = true;
      this.statusMsg = '';
      this.savedPath = '';
      const now = new Date().toLocaleString('zh-CN');
      try {
        const resp = await fetch('/api/applog/download', {
          signal: AbortSignal.timeout(130000),
        });
        const body = await resp.json();
        if (!body.ok) throw new Error(body.message || '拉取失败');
        const data = body.data;
        this.savedPath = data.path;
        this.statusMsg = `拉取成功（${data.size_mb} MB）`;
        this.statusOk = true;
        this.downloadHistory.unshift({ time: now, status: '成功', message: `${data.size_mb} MB → ${data.path}` });
        ElMessage.success('app.log 已保存到 logs/ 目录');
      } catch (e: any) {
        const msg = e?.message || '拉取失败';
        this.statusMsg = msg;
        this.statusOk = false;
        this.downloadHistory.unshift({ time: now, status: '失败', message: msg });
        ElMessage.error('拉取失败: ' + msg);
      } finally {
        this.downloading = false;
      }
    },
    async openFolder() {
      try {
        const resp = await fetch('/api/applog/open_folder', { method: 'POST' });
        const body = await resp.json();
        if (!body.ok) throw new Error(body.message);
        ElMessage.success('已打开 logs 目录');
      } catch (e: any) {
        ElMessage.error('打开目录失败: ' + (e?.message || e));
      }
    },
  },
};
</script>
