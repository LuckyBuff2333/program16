/** 可观测模块 mock 数据 */

// ---- 审计记录 ----
export interface AuditRecord {
  key: string
  time: string
  file: string
  doc_id: string
  cos_hash: string
  result: string
}

export const auditData: AuditRecord[] = [
  { key: '1', time: '2026-10-22 09:14:33', file: 'case_pack_20261022.zip', doc_id: 'DOC-A8F3E1', cos_hash: 'a3f8e1c9d2...', result: '成功' },
  { key: '2', time: '2026-10-21 17:42:10', file: 'dms_log_bundle.zip', doc_id: 'DOC-7B2D4E', cos_hash: '7b2d4ea1f5...', result: '成功' },
  { key: '3', time: '2026-10-21 14:08:55', file: 'audio_focus_trace.zip', doc_id: 'DOC-C5E9A0', cos_hash: 'c5e9a0b3d7...', result: '成功' },
]

// ---- Case 台账 ----
export interface CaseRecord {
  key: string
  vcu_number: string
  case_id: string
  finish_time: string
  duration: string
  conf: number
  converged: boolean
  case_type: string
  reflow_status: string
}

export const caseData: CaseRecord[] = [
  { key: '1', vcu_number: 'VCU-20261022-01', case_id: 'CASE-20261022-001', finish_time: '2026-10-22 10:32:00', duration: '24m4s', conf: 0.80, converged: true, case_type: '新案', reflow_status: '待回流' },
  { key: '2', vcu_number: 'VCU-20261022-02', case_id: 'CASE-20261022-002', finish_time: '2026-10-22 10:15:44', duration: '18m22s', conf: 0.92, converged: true, case_type: '新案', reflow_status: '编辑回流' },
  { key: '3', vcu_number: 'VCU-20261021-03', case_id: 'CASE-20261021-003', finish_time: '2026-10-21 22:50:11', duration: '31m10s', conf: 0.45, converged: false, case_type: '回归', reflow_status: '待回流' },
  { key: '4', vcu_number: 'VCU-20261021-04', case_id: 'CASE-20261021-004', finish_time: '2026-10-21 20:18:33', duration: '15m55s', conf: 0.88, converged: true, case_type: '新案', reflow_status: '编辑回流' },
  { key: '5', vcu_number: 'VCU-20261021-05', case_id: 'CASE-20261021-005', finish_time: '2026-10-21 18:44:02', duration: '27m33s', conf: 0.63, converged: false, case_type: '新案', reflow_status: '待回流' },
  { key: '6', vcu_number: 'VCU-20261020-06', case_id: 'CASE-20261020-006', finish_time: '2026-10-20 16:30:50', duration: '12m43s', conf: 0.95, converged: true, case_type: '回归', reflow_status: '编辑回流' },
  { key: '7', vcu_number: 'VCU-20261020-07', case_id: 'CASE-20261020-007', finish_time: '2026-10-20 14:22:17', duration: '21m7s', conf: 0.71, converged: true, case_type: '新案', reflow_status: '待回流' },
  { key: '8', vcu_number: 'VCU-20261020-08', case_id: 'CASE-20261020-008', finish_time: '2026-10-20 11:05:40', duration: '19m48s', conf: 0.38, converged: false, case_type: '新案', reflow_status: '待回流' },
  { key: '9', vcu_number: 'VCU-20261019-09', case_id: 'CASE-20261019-009', finish_time: '2026-10-19 23:12:28', duration: '22m15s', conf: 0.85, converged: true, case_type: '回归', reflow_status: '编辑回流' },
  { key: '10', vcu_number: 'VCU-20261019-10', case_id: 'CASE-20261019-010', finish_time: '2026-10-19 19:45:00', duration: '16m30s', conf: 0.77, converged: true, case_type: '新案', reflow_status: '待回流' },
  { key: '11', vcu_number: 'VCU-20261019-11', case_id: 'CASE-20261019-011', finish_time: '2026-10-19 15:20:33', duration: '28m41s', conf: 0.52, converged: false, case_type: '新案', reflow_status: '待回流' },
  { key: '12', vcu_number: 'VCU-20261018-12', case_id: 'CASE-20261018-012', finish_time: '2026-10-18 12:10:55', duration: '14m22s', conf: 0.91, converged: true, case_type: '回归', reflow_status: '编辑回流' },
]


// ---- Case 详情 ----
export interface PhaseItem {
  name: string
  duration: string
  seconds: number
  color: string
}

export interface TimelineEvent {
  time: string
  text: string
}

export interface DecisionStage {
  stage: string
  duration: string
  events: TimelineEvent[]
}

export interface DecisionRound {
  round: number
  stages: DecisionStage[]
}

export interface HypothesisRow {
  key: string
  hypothesis: string
  verdict: string
  evidence: string
  remark: string
}

export interface CaseDetailData {
  case_id: string
  description: string
  total_duration: string
  confidence: number
  converged: boolean
  reflow_status: string
  case_type: string
  root_cause: string
  phases: PhaseItem[]
  decision_chain: DecisionRound[]
  hypotheses: HypothesisRow[]
}

const defaultDescription = [
  '[RTC ID: RTC-2026-44821]',
  '时间: 2026-10-22 09:08:12 ~ 09:32:16',
  '日志包: cos://sgm-logs/20261022/case-001-logs.zip',
  '模块: 电源管理 / PowerManager',
  '现象: STR 唤醒后 Wi-Fi 热点开关异常回弹至关闭状态，用户需要手动重新开启。',
].join('\n')

const caseDetailMock: Record<string, CaseDetailData> = {
  'CASE-20261022-001': {
    case_id: 'CASE-20261022-001',
    description: defaultDescription,
    total_duration: '24m4s',
    confidence: 0.80,
    converged: true,
    reflow_status: '待回流',
    case_type: '新案',
    root_cause: '电源管理状态机异常：VCU 启动时 GMWlanServiceImpl 初始化将 AutoShutdownEnabled 参数错误地设为 true，导致系统超时机制在 STR 唤醒后自动关闭热点。',
    phases: [
      { name: '前置准备', duration: '8s', seconds: 8, color: '#409eff' },
      { name: 'Lead 阶段', duration: '3m40s', seconds: 220, color: '#67c23a' },
      { name: '装配', duration: '1m55s', seconds: 115, color: '#e6a23c' },
      { name: '未归属问题', duration: '18m20s', seconds: 1100, color: '#dcdfe6' },
    ],
    decision_chain: [
      {
        round: 1,
        stages: [
          {
            stage: 'Lead 阶段',
            duration: '3m40s',
            events: [
              { time: '00:08', text: '日志解析完成，识别到 142 条关键日志' },
              { time: '00:45', text: '匹配到 PowerManager 模块异常模式' },
              { time: '01:30', text: '发现 AutoShutdownEnabled=true 异常赋值' },
              { time: '02:50', text: '追踪到 GMWlanServiceImpl 初始化链路' },
              { time: '03:40', text: 'Lead 判定：电源管理初始化缺陷，转入装配' },
            ],
          },
          {
            stage: '装配',
            duration: '1m55s',
            events: [
              { time: '03:40', text: '开始装配证据链' },
              { time: '04:15', text: '关联 VCU 启动序列日志' },
              { time: '05:00', text: '确认 STR 唤醒 → 热点关闭的时序关系' },
              { time: '05:35', text: '装配完成，输出根因判定' },
            ],
          },
          {
            stage: 'Reasoner 阶段',
            duration: '0s',
            events: [
              { time: '05:35', text: 'Reasoner 确认根因置信度 0.80，标记为已收敛' },
            ],
          },
        ],
      },
    ],
    hypotheses: [
      { key: '1', hypothesis: 'AutoShutdownEnabled 在 VCU 启动初始化时被错误设为 true', verdict: 'confirmed', evidence: 'GMWlanServiceImpl.java:L142 赋值语句', remark: 'conf 0.80' },
      { key: '2', hypothesis: 'Wi-Fi 驱动层通信异常导致状态丢失', verdict: 'rejected', evidence: '驱动层日志未见异常', remark: 'conf 0.12' },
      { key: '3', hypothesis: 'STR 唤醒流程中电源策略未正确恢复', verdict: 'rejected', evidence: '电源策略恢复序列正常', remark: 'conf 0.08' },
    ],
  },
}

/** 获取 Case 详情，未匹配的 caseId 返回通用模板 */
export function getCaseDetail(caseId: string): CaseDetailData {
  if (caseDetailMock[caseId]) return caseDetailMock[caseId]
  const base = caseDetailMock['CASE-20261022-001']
  return {
    ...base,
    case_id: caseId,
    description: [
      '[RTC ID: RTC-2026-00000]',
      '时间: 2026-10-22 09:00:00 ~ 09:25:00',
      `日志包: cos://sgm-logs/20261022/${caseId}-logs.zip`,
      '模块: 通用模块',
      '现象: 通用问题描述...',
    ].join('\n'),
  }
}
