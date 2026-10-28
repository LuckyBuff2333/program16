/**
 * 共享工具函数 — 从 App.vue 抽取的纯函数与请求封装
 * 各视图组件直接 import 使用，不再通过 this 调用
 */
import { ElMessage } from 'element-plus';

// ─── API 请求封装 ───
export async function api<T = Record<string, unknown>>(url: string, options: RequestInit = {}): Promise<{ ok: boolean; message: string; data: T; [k: string]: unknown }> {
  if (!options.signal) {
    try { options.signal = AbortSignal.timeout(180000); } catch { /* 兼容旧浏览器 */ }
  }
  const resp = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...options });
  const body = await resp.json() as Record<string, unknown>;
  if (!body.ok) {
    ElMessage.error((body.message as string) || '请求失败');
    throw new Error(String(body.message));
  }
  return body as any;
}

// ─── 表格列宽 ───
export function colWidth(col: string): number {
  const wide = ['AI评论总结', 'AI分析结果(飞书链接)', 'rootcause', '文档路径', '已入库分析流程', '新根因结论', '已入库根因分析', '错误信息'];
  if (col === '判定结果' || col === '结果置信度' || col === '补充状态') return 100;
  if (col === 'jira号') return 120;
  if (col === '失败分类') return 130;
  if (col.includes('时间')) return 160;
  return wide.includes(col) ? 220 : 110;
}

export function resultColWidth(col: string): number {
  const wide = ['AI评论总结', 'AI分析结果(飞书链接)', 'rootcause', '文档路径', '已入库分析流程', '新根因结论', '已入库根因分析', '错误信息'];
  if (col === '判定结果' || col === '最终结论' || col === '结果置信度' || col === '补充状态' || col === '分析状态') return 100;
  if (col === 'jira号' || col === 'bugid' || col === '分析问题时间' || col === '执行时间' || col === '触发时间' || col === '分析时间') return 140;
  return wide.includes(col) ? 180 : 90;
}

// ─── 判定结果样式 ───
export function verdictStyle(val: string): string {
  if (val === '达标' || val === '通过') return 'color:#67c23a;font-weight:700';
  if (val === '不达标' || val === '分析失败' || val === '不通过' || val === '失败') return 'color:#f56c6c;font-weight:700';
  return '';
}

// ─── 字段名中文标签映射 ───
const FIELD_LABELS: Record<string, string> = {
  url: '接口地址', timeout: '超时(秒)', model: '模型名称',
  api_key: 'API Key', enabled: '是否启用', mock: 'Mock模式',
  bugid_field: 'API参数名', trigger_time_field: '触发时间字段',
  content_field: '内容字段', username: '用户名', token: 'Token',
  threshold: '相似度阈值', root_cause_hit_ratio: '根因命中比例',
  sample_count: '默认抽查数',
  table_name: '表名', kb_table: '知识库表',
  audited_file: '已抽查文件', report_file: '报告文件',
  bugid_column: 'bugid列', trigger_time_column: '触发时间列',
  root_cause_column: '根因列', process_column: '流程列',
  analysis_process_column: '分析流程列', custom_header: '自定义头',
  app_id: 'App ID', app_secret: 'App Secret', cookie: '浏览器 Cookie', domain: '飞书域名',
  wiki_token: 'Wiki Token', app_token: '多维表格 Token',
  table_id: '数据表 ID', view_id: '视图 ID', report_field: '报告字段名',
  poll_interval: '轮询间隔(秒)',
  batch_folder_token: '批次文件夹 Token',
  trigger_time_app_token: '触发表 Token',
  trigger_time_table_ids: '触发表 ID列表',
  user_access_token: '用户 Access Token',
  user_refresh_token: '用户 Refresh Token',
  client_id: 'Client ID', client_secret: 'Client Secret',
  token_url: 'Token地址', prod_url: '生产接口地址',
  prod_token_url: '生产Token地址',
  prod_client_id: '生产Client ID', prod_client_secret: '生产Client Secret',
  prod_model: '生产模型', env: '环境',
  jqls: 'JQL查询列表',
  doc_dir: '文档目录', log_dir: '日志目录', report_dir: '报告目录',
  auth_type: '认证方式', root_cause_field: '根因字段',
  host: '服务器地址', port: '端口', endpoint: '接口路径',
};

export function fieldLabel(field: string): string {
  return FIELD_LABELS[field] || field;
}

// ─── 诊断归类标签颜色 ───
export function diagCategoryTagType(category: string): string {
  if (!category) return 'info';
  if (category.includes('触发时间')) return 'warning';
  if (category.includes('日志待补充')) return 'warning';
  if (category.includes('无gmlogger') || category.includes('附件')) return 'danger';
  if (category.includes('成功') || category === '分析成功') return 'success';
  if (category.includes('超时') || category.includes('网络')) return '';
  return 'info';
}
