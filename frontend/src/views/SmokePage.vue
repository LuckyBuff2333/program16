<template>
  <div style="padding:20px;max-width:1200px;margin:0 auto">
    <div class="section-title" style="font-size:18px;margin-bottom:16px">冒烟测试</div>
    <el-alert type="info" :closable="false" style="margin-bottom:16px"
      title="覆盖功能验证/置信度/异常处理/批量性能/集成流程 5 大维度，共 20 条标准用例。配置 Jira 号后一键触发线上 AI 日志分析接口，并查询多维表格中的分析结果进行验证。"></el-alert>

    <!-- 维度统计 -->
    <div class="stat-row" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin-bottom:16px">
      <div v-for="ds in smokeDimStats" :key="ds.dim" class="stat-card" style="padding:12px;background:#fafafa;border-radius:6px;border:1px solid #ebeef5">
        <div class="num" style="font-size:24px;font-weight:700">{{ ds.count }}</div>
        <div class="label" style="font-size:12px;margin-top:2px">
          <el-tag size="small" :type="ds.type" style="margin-right:4px">{{ ds.dim }}</el-tag>
        </div>
      </div>
    </div>

    <!-- ① 用例库 -->
    <el-card shadow="never" style="margin-bottom:16px">
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span style="font-weight:700">① 用例库</span>
          <div style="display:flex;align-items:center;gap:8px">
            <span style="font-size:12px;color:#909399">最近更新：{{ smokeTestLastUpdate }}</span>
            <el-tag type="success">共 {{ smokeTest.cases.length }} 条</el-tag>
          </div>
        </div>
      </template>
      <el-table :data="smokeTest.cases" stripe size="small" border :row-class-name="({row}: any)=>row.checked?'':'el-table__row--unselected'">
        <el-table-column label="" width="42" align="center">
          <template #default="{row}"><el-checkbox v-model="row.checked"></el-checkbox></template>
        </el-table-column>
        <el-table-column prop="tc" label="TC编号" width="80"></el-table-column>
        <el-table-column label="维度" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="dimType(row.dim)">{{ row.dim }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="用例名称" min-width="220"></el-table-column>
        <el-table-column label="Jira号" width="220">
          <template #default="{row}">
            <el-input v-model="row.jiraId" size="small" clearable
              :placeholder="row.multi ? '多个Jira号，逗号分隔' : '输入Jira号'"
              @keyup.enter="runSmokeTest"></el-input>
          </template>
        </el-table-column>
      </el-table>
      <div style="display:flex;align-items:center;gap:12px;margin-top:10px">
        <el-button size="small" @click="smokeTest.cases.forEach(c=>c.checked=true)">全选</el-button>
        <el-button size="small" @click="smokeTest.cases.forEach(c=>c.checked=false)">反选</el-button>
        <el-button size="small" type="primary" @click="saveSmokeTestConfig">保存配置</el-button>
      </div>
    </el-card>

    <!-- ② 一键执行AI分析 -->
    <el-card shadow="never" style="margin-bottom:16px">
      <template #header><span style="font-weight:700">② 一键执行 AI 分析</span></template>
      <div style="display:flex;align-items:center;gap:12px">
        <el-radio-group v-model="smokeTest.execMode" size="small">
          <el-radio-button label="online">线上执行</el-radio-button>
          <el-radio-button label="pc">PC执行</el-radio-button>
        </el-radio-group>
        <el-button type="primary" :loading="smokeTest.running" @click="runSmokeTest"
          :disabled="smokeTest.cases.filter(c=>c.checked&&c.jiraId).length===0">一键执行</el-button>
        <el-tag v-if="smokeTest.execMsg" :type="smokeTest.execError?'danger':'success'">{{ smokeTest.execMsg }}</el-tag>
      </div>
      <el-table v-if="smokeTest.execResults.length" :data="smokeTest.execResults" size="small" stripe border style="margin-top:12px">
        <el-table-column type="index" label="#" width="45"></el-table-column>
        <el-table-column prop="jira号" label="Jira号" width="140"></el-table-column>
        <el-table-column label="执行结果" width="90" align="center">
          <template #default="{row}">
            <el-tag :type="row['执行结果']==='成功'?'success':'danger'" size="small">{{ row['执行结果'] }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="触发时间" label="触发时间" width="160"></el-table-column>
        <el-table-column prop="执行时间" label="执行时间" width="160"></el-table-column>
        <el-table-column prop="备注" label="备注" min-width="200" show-overflow-tooltip></el-table-column>
      </el-table>
    </el-card>

    <!-- ③ 多维表格查询 -->
    <el-card shadow="never" style="margin-bottom:16px">
      <template #header><span style="font-weight:700">③ 多维表格查询</span></template>
      <div style="display:flex;align-items:center;gap:12px">
        <el-button type="success" :loading="smokeTest.querying" @click="querySmokeTestBitable"
          :disabled="smokeTest.cases.filter(c=>c.jiraId).length===0">一键查询多维表格</el-button>
        <el-button type="warning" :loading="smokeTest.saving" @click="saveSmokeTestRecord"
          :disabled="!smokeTest.bitableRecords.length">生成记录</el-button>
        <el-tag v-if="smokeTest.queryMsg" :type="smokeTest.queryError?'danger':'success'">{{ smokeTest.queryMsg }}</el-tag>
      </div>
      <el-table v-if="smokeTest.bitableRecords.length" :data="smokeTest.bitableRecords" size="small" stripe border style="margin-top:12px">
        <el-table-column type="index" label="#" width="45"></el-table-column>
        <el-table-column prop="jira号" label="Jira号" width="140"></el-table-column>
        <el-table-column label="分析结果" width="90" align="center">
          <template #default="{row}">
            <el-tag :type="row['分析结果']==='成功'?'success':row['分析结果']==='失败'?'danger':'info'" size="small">{{ row['分析结果'] || '-' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="分析耗时" width="100" align="center">
          <template #default="{row}">{{ computeSmokeDuration(row) }}</template>
        </el-table-column>
        <el-table-column prop="分析问题时间" label="分析问题时间" width="160"></el-table-column>
        <el-table-column prop="分析完成时间" label="分析完成时间" width="160"></el-table-column>
        <el-table-column label="置信度" width="90" align="center">
          <template #default="{row}">
            <el-tag v-if="row['结果置信度']" :type="parseFloat(row['结果置信度'])>=0.8?'success':parseFloat(row['结果置信度'])>=0.5?'warning':'info'" size="small">{{ row['结果置信度'] }}</el-tag>
            <span v-else style="color:#999">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="rootcause" label="问题根因" min-width="200" show-overflow-tooltip>
          <template #default="{row}"><span v-if="row.rootcause">{{ row.rootcause }}</span><span v-else style="color:#c0c4cc">-</span></template>
        </el-table-column>
        <el-table-column prop="错误信息" label="错误信息" min-width="180" show-overflow-tooltip>
          <template #default="{row}"><span v-if="row['错误信息']" style="color:#f56c6c">{{ row['错误信息'] }}</span><span v-else style="color:#c0c4cc">-</span></template>
        </el-table-column>
        <el-table-column prop="人工审核结果" label="人工审核" width="120" show-overflow-tooltip>
          <template #default="{row}"><span v-if="row['人工审核结果']">{{ row['人工审核结果'] }}</span><span v-else style="color:#c0c4cc">-</span></template>
        </el-table-column>
        <el-table-column label="报告" width="60" align="center">
          <template #default="{row}">
            <a v-if="row['飞书报告链接']" :href="row['飞书报告链接']" target="_blank" style="color:#409eff;font-size:12px">查看</a>
            <span v-else style="color:#c0c4cc">-</span>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="smokeTest.saveMsg" style="margin-top:8px">
        <el-alert :type="smokeTest.saveError?'danger':'success'" :closable="false">
          {{ smokeTest.saveMsg }}
          <a v-if="smokeTest.saveCloudUrl" :href="smokeTest.saveCloudUrl" target="_blank" style="margin-left:8px;color:#409eff">查看云端文档</a>
        </el-alert>
      </div>
      <el-table v-if="smokeTest.savedResults.length" :data="smokeTest.savedResults" size="small" stripe border style="margin-top:8px">
        <el-table-column type="index" label="#" width="45"></el-table-column>
        <el-table-column prop="case_name" label="用例" width="220"></el-table-column>
        <el-table-column prop="jira_id" label="Jira号" width="140"></el-table-column>
        <el-table-column label="是否成功" width="90" align="center">
          <template #default="{row}">
            <el-tag :type="row.is_success==='是'?'success':'danger'" size="small">{{ row.is_success }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="analysis_duration" label="分析耗时" width="120" align="center"></el-table-column>
        <el-table-column prop="total_duration" label="总耗时" width="120" align="center"></el-table-column>
        <el-table-column prop="error_reason" label="错误原因" min-width="200" show-overflow-tooltip>
          <template #default="{row}"><span v-if="row.error_reason && row.error_reason!=='-'" style="color:#f56c6c">{{ row.error_reason }}</span><span v-else style="color:#c0c4cc">-</span></template>
        </el-table-column>
      </el-table>
      <el-empty v-else-if="!smokeTest.querying && smokeTest.queryMsg && !smokeTest.queryError" description="无匹配记录" :image-size="40"></el-empty>
    </el-card>
  </div>
</template>

<script lang="ts">
import { ElMessage } from 'element-plus';
import { api } from '../composables/utils';

// 远程标准用例库（19条20个Jira，覆盖 5 大维度）
const SMOKE_CASES = [
  // A. 功能覆盖（5条）—— 各格式分包解压
  { tc: 'SM-01', name: 'zip分包+完整解压+分析', jira: 'VCU-202844', dim: '功能覆盖' },
  { tc: 'SM-02', name: '7z分包+完整解压+分析', jira: 'VCU-216064', dim: '功能覆盖' },
  { tc: 'SM-03', name: 'rar分包+完整解压+分析', jira: 'VCU-415665', dim: '功能覆盖' },
  { tc: 'SM-04', name: 'rar分卷(.part1.rar)+完整解压', jira: 'VCU-188538', dim: '功能覆盖' },
  { tc: 'SM-05', name: 'tar.gz分包+完整解压', jira: 'VCU-243318', dim: '功能覆盖' },
  // B. 置信度（5条）—— 验证分析结果的置信度得分
  { tc: 'SM-06', name: '完整解压场景置信度验证', jira: 'VCU-541387', dim: '置信度' },
  { tc: 'SM-07', name: '多步骤触发置信度', jira: 'VCU-415748', dim: '置信度' },
  { tc: 'SM-08', name: '磁盘rrno28空间不足触发', jira: 'VCU-218982', dim: '置信度' },
  { tc: 'SM-09', name: '504超时后重试置信度', jira: 'VCU-221439', dim: '置信度' },
  { tc: 'SM-10', name: '间歇性通信故障置信度', jira: 'VCU-544557', dim: '置信度' },
  // C. 异常处理（5条）—— 验证异常场景的容错能力
  { tc: 'SM-11', name: '无日志附件', jira: 'VCU-553431', dim: '异常处理' },
  { tc: 'SM-12', name: '无连接', jira: 'VCU-537403', dim: '异常处理' },
  { tc: 'SM-13', name: 'HTTPStatusError错误处理', jira: 'VCU-553442', dim: '异常处理' },
  { tc: 'SM-14', name: '分析超时(adjudication)', jira: 'VCU-523000', dim: '异常处理' },
  { tc: 'SM-15', name: 'Diana请求超时(TimeoutError)', jira: 'VCU-549408', dim: '异常处理' },
  // D. 批量性能（1条）—— 验证批量执行的性能和稳定性
  { tc: 'SM-16', name: '多个不同维度Jira合并', jira: 'VCU-415748,VCU-544557', dim: '批量性能' },
  // E. 集成流程（3条）—— 端到端流程完整性验证
  { tc: 'SM-17', name: '高置信度(>0.9)完整流程', jira: 'VCU-415748', dim: '集成流程' },
  { tc: 'SM-18', name: '低置信度(<0.2)完整流程', jira: 'VCU-241162', dim: '集成流程' },
  { tc: 'SM-19', name: '根因链路完整性验证', jira: 'VCU-540049', dim: '集成流程' },
];

const DIM_TYPE: Record<string, string> = {
  '功能覆盖': '',
  '置信度': 'success',
  '异常处理': 'danger',
  '批量性能': 'warning',
  '集成流程': 'info',
};

export default {
  name: 'SmokePage',
  data() {
    return {
      smokeTestLastUpdate: '2026-10-13',
      smokeTest: {
        cases: SMOKE_CASES.map(c => ({
          ...c,
          jiraId: c.jira || '',
          checked: !c.multi, // 批量性能用例默认不勾选（需手动填写）
        })),
        version: '',
        execMode: 'online',
        running: false, execResults: [] as any[], execMsg: '', execError: false, execTime: '',
        querying: false, bitableRecords: [] as any[], queryMsg: '', queryError: false,
        saving: false, saveMsg: '', saveError: false, saveCloudUrl: '', savedResults: [] as any[],
      },
    };
  },
  computed: {
    smokeDimStats(): { dim: string; count: number; type: string }[] {
      const dimMap: Record<string, { dim: string; count: number; type: string }> = {};
      this.smokeTest.cases.forEach((c: any) => {
        if (!dimMap[c.dim]) dimMap[c.dim] = { dim: c.dim, count: 0, type: DIM_TYPE[c.dim] || 'info' };
        dimMap[c.dim].count++;
      });
      return Object.values(dimMap);
    },
  },
  mounted() {
    this.loadSmokeTestConfig();
  },
  methods: {
    dimType(dim: string): string {
      return DIM_TYPE[dim] || 'info';
    },
    async runSmokeTest() {
      const selected = this.smokeTest.cases.filter((c: any) => c.checked && c.jiraId.trim());
      if (!selected.length) return ElMessage.warning('请勾选并填写 Jira 号');
      // 支持多Jira：逗号/中文逗号分隔
      const bugids = selected.flatMap((c: any) =>
        c.jiraId.trim().split(/[,，]/).map((s: string) => s.trim()).filter(Boolean)
      );
      const now = new Date();
      const pad = (n: number) => String(n).padStart(2, '0');
      this.smokeTest.execTime = `${now.getFullYear()}-${pad(now.getMonth()+1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
      this.smokeTest.running = true;
      this.smokeTest.execResults = []; this.smokeTest.execMsg = ''; this.smokeTest.execError = false;
      this.smokeTest.savedResults = []; this.smokeTest.saveMsg = ''; this.smokeTest.saveCloudUrl = '';
      try {
        const resp = await fetch('/api/test/prod_batch_run', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ bugids, skip_existing: false, exec_mode: this.smokeTest.execMode }),
        });
        const reader = resp.body!.getReader();
        const decoder = new TextDecoder();
        let buf = '';
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          const lines = buf.split('\n');
          buf = lines.pop()!;
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            try {
              const d = JSON.parse(line.slice(6));
              if (d.type === 'progress') {
                this.smokeTest.execResults.push({
                  'jira号': d.bugid || '', '执行结果': d.status || '',
                  '触发时间': d.exec_time || '', '执行时间': d.analysis_time || '', '备注': d.msg || '',
                });
              }
              else if (d.type === 'done') this.smokeTest.execMsg = d.message || d.msg || `执行完成，成功 ${d.success || 0} 条`;
            } catch (_) {}
          }
        }
        if (!this.smokeTest.execMsg) this.smokeTest.execMsg = `执行完成，共 ${this.smokeTest.execResults.length} 条`;
      } catch (e: any) {
        this.smokeTest.execMsg = '执行失败: ' + e.message;
        this.smokeTest.execError = true;
      } finally { this.smokeTest.running = false; }
    },
    async querySmokeTestBitable() {
      const jiraIds = this.smokeTest.cases
        .filter((c: any) => c.jiraId.trim())
        .flatMap((c: any) => c.jiraId.trim().split(/[,，]/).map((s: string) => s.trim()).filter(Boolean));
      if (!jiraIds.length) return ElMessage.warning('请填写 Jira 号');
      this.smokeTest.querying = true;
      this.smokeTest.bitableRecords = []; this.smokeTest.queryMsg = ''; this.smokeTest.queryError = false;
      this.smokeTest.savedResults = []; this.smokeTest.saveMsg = ''; this.smokeTest.saveCloudUrl = '';
      try {
        const resp = await api<{ rows: any[]; count: number }>('/api/test/smoke_test_query', {
          method: 'POST', body: JSON.stringify({ jira_ids: jiraIds, exec_time: this.smokeTest.execTime }),
        });
        this.smokeTest.bitableRecords = resp.data.rows || [];
        this.smokeTest.queryMsg = `查询到 ${resp.data.count || 0} 条记录`;
      } catch (e: any) {
        this.smokeTest.queryMsg = '查询失败: ' + e.message;
        this.smokeTest.queryError = true;
      } finally { this.smokeTest.querying = false; }
    },
    computeSmokeDuration(row: any): string {
      const dur = row['分析耗时'];
      if (dur && dur !== '-' && dur.trim()) return dur;
      const start = row['分析问题时间'], end = row['分析完成时间'];
      if (!start || !end) return '-';
      try {
        const s = new Date(start.replace(' ', 'T')), e = new Date(end.replace(' ', 'T'));
        if (isNaN(s.getTime()) || isNaN(e.getTime())) return '-';
        const sec = Math.round((e.getTime() - s.getTime()) / 1000);
        if (sec < 0) return '-';
        if (sec < 60) return sec + '秒';
        return Math.floor(sec / 60) + '分' + (sec % 60) + '秒';
      } catch (_) { return '-'; }
    },
    saveSmokeTestConfig() {
      const cfg = this.smokeTest.cases.map((c: any) => ({ tc: c.tc, name: c.name, jiraId: c.jiraId }));
      localStorage.setItem('smoke_test_config', JSON.stringify(cfg));
      ElMessage.success('用例配置已保存');
    },
    loadSmokeTestConfig() {
      try {
        const raw = localStorage.getItem('smoke_test_config');
        if (raw) {
          const cfg = JSON.parse(raw);
          if (Array.isArray(cfg)) {
            cfg.forEach((saved: any) => {
              const c = this.smokeTest.cases.find((x: any) => x.tc === saved.tc || x.name === saved.name);
              if (c && saved.jiraId) c.jiraId = saved.jiraId;
            });
          }
        }
      } catch (_) {}
    },
    async saveSmokeTestRecord() {
      if (!this.smokeTest.bitableRecords.length) return ElMessage.warning('请先查询多维表格');
      if (!this.smokeTest.execTime) return ElMessage.warning('请先执行一键执行');
      this.smokeTest.saving = true;
      this.smokeTest.saveMsg = ''; this.smokeTest.saveError = false; this.smokeTest.saveCloudUrl = '';
      const bitableMap: Record<string, any> = {};
      for (const r of this.smokeTest.bitableRecords) bitableMap[r['jira号']] = r;
      // 遍历所有用例（含多Jira展开）
      const results: any[] = [];
      for (const c of this.smokeTest.cases.filter((c: any) => c.jiraId.trim())) {
        const ids = c.jiraId.trim().split(/[,，]/).map((s: string) => s.trim()).filter(Boolean);
        for (const jiraId of ids) {
          const rec = bitableMap[jiraId.toUpperCase()] || {};
          const dur = this.computeSmokeDuration(rec);
          const totalDur = (rec['总耗时'] && rec['总耗时'] !== '-' && rec['总耗时'].trim()) ? rec['总耗时'] : dur;
          const isSuccess = rec['分析结果'] === '成功' ? '是' : '否';
          const errorReason = isSuccess === '是' ? '-' : (rec['错误信息'] || rec['rootcause'] || '-');
          const caseLabel = ids.length > 1 ? `${c.name} (${jiraId})` : c.name;
          results.push({
            case_name: caseLabel, jira_id: jiraId, is_success: isSuccess,
            analysis_duration: dur, total_duration: totalDur, error_reason: errorReason,
            bitable_record: rec,
          });
        }
      }
      this.smokeTest.savedResults = results.map(r => ({
        case_name: r.case_name, jira_id: r.jira_id, is_success: r.is_success,
        analysis_duration: r.analysis_duration, total_duration: r.total_duration, error_reason: r.error_reason,
      }));
      try {
        const resp = await api<{ cloud_url: string; local_path: string }>('/api/test/smoke_test_save_record', {
          method: 'POST', body: JSON.stringify({
            version: this.smokeTest.version || '-', exec_time: this.smokeTest.execTime, results: results,
            exec_mode: this.smokeTest.execMode,
          }),
        });
        const data = resp.data;
        this.smokeTest.saveCloudUrl = data.cloud_url || '';
        this.smokeTest.saveMsg = `记录已保存${data.local_path ? `（本地: ${data.local_path}）` : ''}`;
        ElMessage.success('冒烟测试记录已生成');
      } catch (e: any) {
        this.smokeTest.saveMsg = '保存失败: ' + e.message;
        this.smokeTest.saveError = true;
      } finally { this.smokeTest.saving = false; }
    },
  },
};
</script>

<style scoped>
.el-table__row--unselected { opacity: 0.5; }
</style>
