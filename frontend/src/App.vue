<template>
  <div class="app-shell" :class="{ 'sidebar-collapsed': sidebarCollapsed }">
    <aside class="app-sidebar">
      <div class="brand">
        <div class="brand-mark">AI</div>
        <div class="brand-copy">
          <strong>AI应用测评平台</strong>
          <span>智能分析工作台</span>
        </div>
      </div>

      <nav class="primary-nav" aria-label="主导航">
        <template v-for="entry in navigationEntries">
          <button
            v-if="!entry.items"
            :key="entry.key || entry.label"
            type="button"
            class="nav-item nav-root-item"
            :class="{ active: activeNavigation === entry.key }"
            :title="sidebarCollapsed ? entry.label : undefined"
            @click="navigateTo(entry)"
          >
            <span class="nav-glyph">{{ entry.glyph }}</span>
            <span class="nav-label">{{ entry.label }}</span>
            <span v-if="activeNavigation === entry.key" class="nav-active-mark"></span>
          </button>
          <div v-else :key="'g-' + (entry.label)" class="nav-group">
            <div class="nav-group-title">{{ entry.label }}</div>
            <template v-for="item in entry.items">
              <div v-if="item.sectionTitle" :key="'s-' + item.sectionTitle" class="nav-subsection-title">{{ item.sectionTitle }}</div>
              <button
                v-else
                :key="item.key"
                type="button"
                class="nav-item"
                :class="{ active: activeNavigation === item.key }"
                :title="sidebarCollapsed ? item.label : undefined"
                @click="navigateTo(item)"
              >
                <span class="nav-glyph">{{ item.glyph }}</span>
                <span class="nav-label">{{ item.label }}</span>
                <span v-if="activeNavigation === item.key" class="nav-active-mark"></span>
              </button>
            </template>
          </div>
        </template>
      </nav>

      <button
        type="button"
        class="sidebar-toggle"
        :aria-label="sidebarCollapsed ? '展开侧栏' : '收起侧栏'"
        @click="toggleSidebar"
      >
        <span>{{ sidebarCollapsed ? '›' : '‹' }}</span>
        <span class="nav-label">{{ sidebarCollapsed ? '展开导航' : '收起导航' }}</span>
      </button>
    </aside>

    <div class="shell-main">
      <header class="topbar">
        <div class="topbar-context">
          <button type="button" class="mobile-nav-toggle" aria-label="切换导航" @click="toggleSidebar">☰</button>
          <span>AI应用测评平台</span>
          <i></i>
          <strong>{{ currentPageMeta.title }}</strong>
        </div>

      </header>

      <main class="workspace">
        <div class="workspace-heading">
          <div>
            <h1>{{ currentPageMeta.title }}</h1>
            <p>{{ currentPageMeta.description }}</p>
          </div>
          <div class="workspace-date">{{ currentDateLabel }}</div>
        </div>

        <div class="workspace-content">
          <OnlinePage v-if="page === 'online'" :tab="tab" @update:tab="tab = $event" />
          <TestPage v-else-if="page === 'testpage'" :test-panel="testPanel" />
          <SmokePage v-else-if="page === 'smoke'" />
          <RegressionPage v-else-if="page === 'regression'" />
        </div>
      </main>
    </div>
  </div>
</template>

<script lang="ts">
// @ts-nocheck
import { ElMessage } from 'element-plus';
import OnlinePage from './views/OnlinePage.vue';
import TestPage from './views/TestPage.vue';
import SmokePage from './views/SmokePage.vue';
import RegressionPage from './views/RegressionPage.vue';
import PlaceholderPage from './components/PlaceholderPage.vue';

export default {
  components: { OnlinePage, TestPage, SmokePage, RegressionPage, PlaceholderPage },
  data() {
    return {
      page: 'online',
      tab: 'flow',
      testPanel: 'batch_ai',
      sidebarCollapsed: false,
      navigationEntries: [
        {
          key: 'overview', label: '任务总览', glyph: '总',
          page: 'online', tab: 'flow',
          title: '任务总览', description: '集中查看当前测试任务状态、今日执行数量与待处理情况。',
        },
        {
          label: '测试执行',
          items: [
            { key: 'pc_function', label: '功能测试', glyph: '功', page: 'testpage', panel: 'batch_ai', title: '功能测试', description: '开展 Bug 验证、问题复现与批量分析。' },
            { key: 'regression', label: '回归测试', glyph: '回', page: 'regression', title: '回归测试', description: '维护回归用例并验证版本变更影响。' },
            { key: 'smoke', label: '冒烟测试', glyph: '冒', page: 'smoke', title: '冒烟测试', description: '使用典型用例快速验证核心链路是否可用。' },
          ],
        },
        {
          label: '问题排查',
          items: [
            { key: 'troubleshoot', label: '问题排查', glyph: '查', page: 'testpage', panel: 'troubleshoot', title: '问题排查', description: '筛选失败任务、查看诊断结果并批量处理问题记录。' },
            { key: 'ai_log_visual', label: '数据可观测分析', glyph: '图', page: 'testpage', panel: 'ai_log_visual', title: '数据可观测分析', description: '以可视化方式查看分析数据与结果。' },
          ],
        },
        {
          label: '数据统计',
          items: [
            { key: 'data_stats', label: '数据统计', glyph: '统', page: 'online', tab: 'stats', title: '数据统计', description: '查看执行统计数据与趋势分析。' },
            { key: 'data_dashboard', label: '数据看板', glyph: '数', page: 'online', tab: 'data', title: '数据看板', description: '集中查看执行数据与质量指标。' },
          ],
        },
        {
          label: '系统配置',
          items: [
            { key: 'config', label: '接口设置', glyph: '设', page: 'online', tab: 'config', title: '接口设置', description: '管理外部服务、模型与知识库连接参数。' },
            { sectionTitle: '更多工具' },
            { key: 'online_followup', label: 'PC VS 线上跟进执行', glyph: '跟', page: 'testpage', panel: 'online_followup', title: 'PC VS 线上跟进执行', description: '对比 PC 与线上执行结果，处理差集与批量执行。' },
            { key: 'confidence_batch', label: '置信度批量写入', glyph: '信', page: 'testpage', panel: 'confidence_batch', title: '置信度批量写入', description: '批量维护任务置信度数据。' },
            { key: 'daily_summary', label: '每日汇总', glyph: '汇', page: 'testpage', panel: 'daily_summary', title: '每日汇总', description: '按日/周/时间段维度汇总分析执行数据。' },
            { key: 'jira_lookup', label: 'Jira 查询', glyph: '查', page: 'testpage', panel: 'jira_lookup', title: 'Jira 查询', description: '通过 Jira 号或 JQL 查询 Bug 概要与根因。' },
            { key: 'app_log_download', label: 'app.log 下载', glyph: '志', page: 'testpage', panel: 'app_log_download', title: 'App.log 下载', description: '从远程服务器下载 app.log 日志文件。' },
            { key: 'time_extract', label: '时间批量提取', glyph: '时', page: 'testpage', panel: 'time_extract', title: '时间批量提取', description: '通过 JQL 或手动输入批量提取触发时间，并行提取并写入云端。' },
          ],
        },
      ],

    };
  },
  computed: {

    navigationRoutes() {
      return this.navigationEntries.flatMap(section =>
        section.items
          ? section.items.filter(item => !item.sectionTitle).map(item => ({ ...item, section: section.label }))
          : [{ ...section, section: '' }],
      );
    },
    activeNavigationEntry() {
      return this.navigationRoutes.find(item =>
        item.page === this.page &&
        (!item.tab || item.tab === this.tab) &&
        (!item.panel || item.panel === this.testPanel),
      ) || null;
    },
    activeNavigation() {
      return this.activeNavigationEntry?.key || (this.page === 'online' ? this.tab : this.page);
    },
    currentPageMeta() {
      const entry = this.activeNavigationEntry;
      return entry
        ? { group: entry.section, title: entry.title || entry.label, description: entry.description || '' }
        : { group: '', title: 'AI应用测评平台', description: '' };
    },
    currentDateLabel() {
      return new Intl.DateTimeFormat('zh-CN', {
        month: 'long', day: 'numeric', weekday: 'short',
      }).format(new Date());
    },
  },
  methods: {
    navigateTo(item) {
      this.page = item.page;
      if (item.tab) this.tab = item.tab;
      if (item.panel) this.testPanel = item.panel;
      if (window.matchMedia('(max-width: 680px)').matches) {
        this.sidebarCollapsed = true;
        localStorage.setItem('app_sidebar_collapsed', 'true');
      }
    },
    toggleSidebar() {
      this.sidebarCollapsed = !this.sidebarCollapsed;
      localStorage.setItem('app_sidebar_collapsed', String(this.sidebarCollapsed));
    },
  },
  async mounted() {
    const savedSidebarState = localStorage.getItem('app_sidebar_collapsed');
    this.sidebarCollapsed = savedSidebarState === null
      ? window.matchMedia('(max-width: 680px)').matches
      : savedSidebarState === 'true';
    const showApp = () => {
      const app = document.getElementById('app');
      if (app) app.classList.add('ready');
      const overlay = document.getElementById('loading-overlay');
      if (overlay) {
        overlay.classList.add('hide');
        setTimeout(() => overlay.remove(), 500);
      }
    };
    this.$nextTick(showApp);
  },
};
</script>

<style>
/* 全局样式：动画统一使用 transform/opacity，GPU 加速避免重绘抖动 */
  :root {
    --shell-navy: #102238;
    --shell-navy-deep: #0a1727;
    --shell-blue: #2f6fed;
    --shell-canvas: #f3f6fa;
    --shell-border: #e4eaf2;
    --shell-text: #172033;
    --shell-muted: #718096;
  }
  html, body { height: 100%; margin: 0; background: var(--shell-canvas); font-family: "Microsoft YaHei", "PingFang SC", sans-serif; color: var(--shell-text); }
  button, input, textarea, select { font: inherit; }
  #app { height: 100%; opacity: 0; transition: opacity .35s ease; }
  #app.ready { opacity: 1; }
  /* 页面加载遮罩：纯 CSS 动画，JS 加载前即可渲染 */
  #loading-overlay {
    position: fixed; inset: 0; z-index: 99999; display: flex; flex-direction: column;
    align-items: center; justify-content: center; background: #f0f2f5;
    transition: opacity .4s ease; }
  #loading-overlay.hide { opacity: 0; pointer-events: none; }
  .ld-spinner {
    width: 40px; height: 40px; border: 3.5px solid #d6e2ff; border-top-color: #2b5cad;
    border-radius: 50%; animation: ld-spin .7s linear infinite; }
  @keyframes ld-spin { to { transform: rotate(360deg); } }
  .ld-text { margin-top: 14px; color: #8a93a6; font-size: 14px; }
  .app-shell { height: 100%; display: grid; grid-template-columns: 248px minmax(0, 1fr); background: var(--shell-canvas);
    transition: grid-template-columns .25s ease; overflow: hidden; }
  .app-shell.sidebar-collapsed { grid-template-columns: 78px minmax(0, 1fr); }
  .app-sidebar { min-width: 0; display: flex; flex-direction: column; color: #dbe6f5;
    background:
      radial-gradient(circle at 18% 5%, rgba(47,111,237,.22), transparent 28%),
      linear-gradient(180deg, var(--shell-navy) 0%, var(--shell-navy-deep) 100%);
    border-right: 1px solid rgba(255,255,255,.06); overflow: hidden; }
  .brand { height: 76px; display: flex; align-items: center; gap: 12px; padding: 0 20px;
    border-bottom: 1px solid rgba(255,255,255,.08); box-sizing: border-box; white-space: nowrap; }
  .brand-mark { width: 38px; height: 38px; flex: 0 0 38px; display: grid; place-items: center; border-radius: 11px;
    background: linear-gradient(145deg, #5a91ff, #2f6fed); color: #fff; font-size: 13px; font-weight: 800;
    letter-spacing: .5px; box-shadow: 0 8px 20px rgba(47,111,237,.3); }
  .brand-copy { display: flex; flex-direction: column; min-width: 0; transition: opacity .2s ease; }
  .brand-copy strong { color: #fff; font-size: 17px; letter-spacing: .3px; }
  .brand-copy span { margin-top: 3px; color: #8395ad; font-size: 11px; }
  .primary-nav { flex: 1; padding: 16px 12px; overflow: auto; scrollbar-width: none; }
  .primary-nav::-webkit-scrollbar { display: none; }
  .nav-root-item { margin-bottom: 20px; }
  .nav-group + .nav-group { margin-top: 20px; }
  .nav-group { min-width: 0; }
  .nav-group-title { height: 20px; padding: 0 10px; color: #63758e; font-size: 10px; font-weight: 700;
    letter-spacing: 1.4px; white-space: nowrap; overflow: hidden; transition: opacity .2s ease; }
  .nav-subsection-title { margin: 12px 10px 5px; padding-top: 10px; color: #71839a; border-top: 1px solid rgba(255,255,255,.08);
    font-size: 10px; font-weight: 700; letter-spacing: 1px; white-space: nowrap; }
  .nav-item { position: relative; width: 100%; height: 44px; margin: 3px 0; padding: 0 12px; display: flex;
    align-items: center; gap: 12px; color: #9fb0c5; background: transparent; border: 0; border-radius: 9px;
    cursor: pointer; text-align: left; white-space: nowrap; transition: color .2s ease, background .2s ease, transform .2s ease; }
  .nav-item:hover { color: #fff; background: rgba(255,255,255,.07); transform: translateX(2px); }
  .nav-item.active { color: #fff; background: linear-gradient(90deg, rgba(47,111,237,.95), rgba(47,111,237,.68)); box-shadow: 0 8px 18px rgba(10,23,39,.28); }
  .nav-glyph { width: 24px; height: 24px; flex: 0 0 24px; display: grid; place-items: center; border: 1px solid currentColor;
    border-radius: 7px; font-size: 10px; font-weight: 800; line-height: 1; opacity: .9; }
  .nav-label { overflow: hidden; transition: opacity .15s ease; }
  .nav-active-mark { position: absolute; right: 8px; width: 4px; height: 4px; border-radius: 50%; background: #fff; }
  .sidebar-toggle { height: 54px; margin: 0 12px 14px; padding: 0 13px; display: flex; align-items: center; gap: 14px;
    color: #8295ad; background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.07); border-radius: 9px;
    cursor: pointer; white-space: nowrap; transition: color .2s ease, background .2s ease; }
  .sidebar-toggle:hover { color: #fff; background: rgba(255,255,255,.08); }
  .sidebar-toggle > span:first-child { width: 20px; font-size: 24px; line-height: 1; text-align: center; }
  .sidebar-collapsed .brand { padding: 0 20px; }
  .sidebar-collapsed .brand-copy, .sidebar-collapsed .nav-label, .sidebar-collapsed .nav-group-title { opacity: 0; pointer-events: none; }
  .sidebar-collapsed .nav-subsection-title { height: 1px; margin: 8px 0; padding: 0; overflow: hidden; border: 0; }
  .sidebar-collapsed .nav-item { padding: 0 15px; }
  .sidebar-collapsed .nav-item:hover { transform: none; }
  .sidebar-collapsed .nav-active-mark { display: none; }
  .sidebar-collapsed .sidebar-toggle { padding: 0 10px; justify-content: center; }
  .shell-main { min-width: 0; min-height: 0; display: flex; flex-direction: column; }
  .topbar { height: 64px; flex: 0 0 64px; padding: 0 28px; display: flex; align-items: center; justify-content: space-between;
    gap: 24px; background: rgba(255,255,255,.94); border-bottom: 1px solid var(--shell-border); box-sizing: border-box; backdrop-filter: blur(12px); }
  .topbar-context { min-width: 0; display: flex; align-items: center; gap: 10px; color: #8491a4; font-size: 12px; white-space: nowrap; }
  .topbar-context i { width: 1px; height: 14px; margin: 0 3px; background: #dce3ec; }
  .topbar-context strong { color: #344054; font-weight: 600; }
  .mobile-nav-toggle { display: none; width: 34px; height: 34px; color: #46556b; background: #f4f7fb; border: 1px solid #e2e8f0; border-radius: 8px; cursor: pointer; }

  .workspace { flex: 1; min-height: 0; padding: 26px 28px 28px; overflow-y: auto; box-sizing: border-box; }
  .workspace-heading { max-width: 1720px; margin: 0 auto 18px; display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; }
  .workspace-heading h1 { margin: 5px 0 5px; color: #172033; font-size: 25px; line-height: 1.2; letter-spacing: -.4px; }
  .workspace-heading p { margin: 0; color: var(--shell-muted); font-size: 13px; }
  .workspace-date { padding-bottom: 3px; color: #8a97a9; font-size: 12px; white-space: nowrap; }
  .workspace-content { max-width: 1720px; min-height: calc(100% - 78px); margin: 0 auto; }
  .root-tabs, .online-tabs { min-height: 100%; }
  .root-tabs > .el-tabs__header, .online-tabs > .el-tabs__header { display: none; }
  .root-tabs > .el-tabs__content, .online-tabs > .el-tabs__content { overflow: visible; }
  .online-tabs { border: 0; background: transparent; box-shadow: none; }
  .online-tabs > .el-tabs__content { padding: 0; }
  .module-main { width: 100%; min-width: 0; padding: 0 !important; display: flex; flex-direction: column; }
  .module-placeholder { position: relative; min-height: 420px; padding: clamp(28px, 7vw, 88px); overflow: hidden;
    display: flex; flex-direction: column; align-items: flex-start; justify-content: center;
    background: linear-gradient(135deg, #fff 0%, #f4f8fc 58%, #edf4fb 100%);
    border: 1px solid #e0e8f2; border-radius: 16px; box-shadow: 0 14px 40px rgba(31,59,115,.07); }
  .module-placeholder::after { content: ""; position: absolute; right: -72px; top: -105px; width: 300px; height: 300px;
    border: 1px solid rgba(47,111,237,.12); border-radius: 50%; box-shadow: 0 0 0 34px rgba(47,111,237,.035), 0 0 0 68px rgba(47,111,237,.025); }
  .placeholder-mark { width: 48px; height: 48px; margin-bottom: 24px; display: grid; place-items: center;
    color: #2f6fed; background: #eaf1ff; border: 1px solid #d6e4ff; border-radius: 14px; font-size: 13px; font-weight: 800; letter-spacing: .5px; }
  .module-placeholder h2 { margin: 14px 0 8px; color: #172b4d; font-size: 26px; letter-spacing: -.4px; }
  .module-placeholder p { max-width: 560px; margin: 0; color: #66758a; font-size: 14px; line-height: 1.8; }
  .placeholder-scope { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 24px; }
  .placeholder-scope span { padding: 7px 11px; color: #52647b; background: rgba(255,255,255,.8); border: 1px solid #e1e8f0; border-radius: 999px; font-size: 12px; }
  /* 统计卡片 */
  .stat-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 16px; }
  .stat-card { background: #fff; border-radius: 10px; padding: 16px 20px; box-shadow: 0 1px 4px rgba(0,0,0,.06);
    transition: transform .25s ease, box-shadow .25s ease; will-change: transform; }
  .stat-card:hover { transform: translateY(-4px); box-shadow: 0 6px 18px rgba(31,59,115,.15); }
  .stat-card .num { font-size: 28px; font-weight: 700; color: #1f3b73; }
  .stat-card .label { font-size: 13px; color: #8a93a6; margin-top: 4px; }
  /* 流程可视化 */
  .flow-wrap { background: #fff; border-radius: 10px; padding: 24px; margin-bottom: 16px; overflow-x: auto; }
  .flow-line { display: flex; align-items: stretch; gap: 0; min-width: 980px; }
  .flow-node { flex: 1; background: #f5f8ff; border: 1px solid #d6e2ff; border-radius: 10px; padding: 14px 12px;
    text-align: center; transition: transform .25s ease, box-shadow .25s ease; will-change: transform; }
  .flow-node:hover { transform: translateY(-4px) scale(1.02); box-shadow: 0 8px 20px rgba(43,92,173,.18); }
  .flow-node .icon { font-size: 22px; }
  .flow-node .title { font-weight: 600; font-size: 14px; color: #1f3b73; margin: 6px 0 4px; }
  .flow-node .desc { font-size: 12px; color: #8a93a6; line-height: 1.5; }
  .flow-node.manual { background: #fff8f0; border-color: #ffd9ad; }
  .flow-node.manual .title { color: #b25e09; }
  .flow-arrow { display: flex; align-items: center; padding: 0 8px; color: #2b5cad; font-size: 20px;
    animation: arrow-move 1.6s ease-in-out infinite; }
  @keyframes arrow-move { 0%,100% { transform: translateX(0); opacity: .55; } 50% { transform: translateX(4px); opacity: 1; } }
  .flow-branch { margin-top: 14px; display: flex; align-items: center; gap: 10px; min-width: 980px; }
  .branch-tag { font-size: 12px; color: #b25e09; white-space: nowrap; }
  /* 单Jira动态补充步骤 */
  .flow-steps-wrap { display: flex; align-items: flex-start; gap: 0; overflow-x: auto; padding: 16px 0; }
  .flow-step-node { flex: 1; min-width: 120px; max-width: 160px; border: 2px solid #e4e7ed; border-radius: 10px;
    padding: 12px 10px; text-align: center; transition: all .35s ease; position: relative; background: #fff; }
  .flow-step-node.pending { opacity: .5; }
  .flow-step-node.running { border-color: #409eff; background: #ecf5ff;
    box-shadow: 0 0 14px rgba(64,158,255,.35); animation: step-pulse 1.5s ease-in-out infinite; }
  .flow-step-node.success { border-color: #67c23a; background: #f0f9eb; }
  .flow-step-node.fail { border-color: #f56c6c; background: #fef0f0; }
  .flow-step-node.skipped { opacity: .4; border-style: dashed; }
  .flow-step-node.existing { border-color: #909399; background: #f4f4f5; }
  @keyframes step-pulse { 0%,100% { box-shadow: 0 0 8px rgba(64,158,255,.2); } 50% { box-shadow: 0 0 18px rgba(64,158,255,.5); } }
  .flow-step-node .step-icon { font-size: 24px; line-height: 1; }
  .flow-step-node .step-spinner { display: none; width: 22px; height: 22px; border: 2.5px solid #b3d8ff;
    border-top-color: #409eff; border-radius: 50%; animation: step-spin .7s linear infinite; margin: 0 auto 4px; }
  .flow-step-node.running .step-spinner { display: block; }
  .flow-step-node.running .step-icon { display: none; }
  @keyframes step-spin { to { transform: rotate(360deg); } }
  .flow-step-node .step-title { font-weight: 600; font-size: 13px; color: #1f3b73; margin: 6px 0 4px; }
  .flow-step-node .step-summary { font-size: 11px; color: #8a93a6; line-height: 1.4; word-break: break-all;
    max-height: 60px; overflow: hidden; text-overflow: ellipsis; }
  .flow-step-node .step-elapsed { font-size: 10px; color: #b0b8c8; margin-top: 4px; }
  .flow-step-arrow { display: flex; align-items: center; padding: 0 4px; color: #c0c4cc; font-size: 18px;
    transition: color .3s ease; margin-top: 20px; }
  .flow-step-arrow.done { color: #67c23a; }
  .flow-step-arrow.active { color: #409eff; animation: arrow-move 1.6s ease-in-out infinite; }
  .flow-step-arrow.error { color: #f56c6c; }
  /* 操作面板 */
  .op-grid { display: grid; grid-template-columns: 1.2fr 1fr; gap: 14px; margin-bottom: 16px; }
  .fade-enter-active, .fade-leave-active { transition: opacity .3s ease; }
  .fade-enter-from, .fade-leave-to { opacity: 0; }
  .section-title { font-size: 15px; font-weight: 600; color: #1f3b73; margin-bottom: 12px; }
  /* 功能测试面板：弹性铺满容器剩余高度，内容超高时面板内部滚动 */
  .test-panel { flex: 1; display: flex; flex-direction: column; min-height: 0; overflow-y: auto; }
  /* 面板子项不压缩，保证内容完整展示并触发滚动条 */
  .test-panel > * { flex-shrink: 0; }
  .test-panel .el-card { margin-top: 12px; }
  .test-panel .fill-card { flex: 1; display: flex; flex-direction: column; min-height: 320px; }
  .test-panel .fill-card .el-card__body { flex: 1; display: flex; flex-direction: column; }
  /* 提取结果块级布局：标签在上、内容在下，文本占满面板宽度不被截断 */
  .kv-block { margin-bottom: 14px; }
  .kv-label { font-weight: 600; color: #1f3b73; font-size: 13px; margin-bottom: 6px; }
  .kv-value { background: #f7f8fa; padding: 8px 12px; border-radius: 6px; font-size: 13px;
    line-height: 1.8; word-break: break-word; white-space: normal; }
  .kv-step { padding: 5px 10px; background: #f7f8fa; border-radius: 6px; margin-bottom: 5px;
    font-size: 13px; line-height: 1.7; word-break: break-word; }
  /* 配置字段行悬浮显示删除按钮：默认透明，hover 时优雅显现 */
  .cfg-field-row { display: flex; align-items: center; gap: 4px; min-width: 0; }
  .cfg-field-row > :first-child { flex: 1; min-width: 0; overflow: hidden; }
  .field-del-btn { flex-shrink: 0; width: 22px; height: 22px; border: none; background: transparent;
    color: transparent; font-size: 16px; line-height: 22px; text-align: center; border-radius: 4px;
    cursor: pointer; transition: all 0.2s ease; }
  .cfg-field-row:hover .field-del-btn { color: #c0c4cc; }
  .field-del-btn:hover { color: #f56c6c !important; background: #fef0f0; }
  /* 表单标签超长时 ellipsis 截断，悬浮 tooltip 显示完整文本 */
  .el-form-item__label { overflow: hidden !important; text-overflow: ellipsis !important; white-space: nowrap !important; }
  /* Markdown 预览区样式：支持图片、代码块、列表等 */
  .md-preview { max-height: 600px; overflow: auto; padding: 12px; font-size: 13px; line-height: 1.8; }
  .md-preview h1 { font-size: 18px; margin: 16px 0 8px; border-bottom: 1px solid #eee; padding-bottom: 6px; }
  .md-preview h2 { font-size: 16px; margin: 14px 0 6px; }
  .md-preview h3 { font-size: 15px; margin: 12px 0 4px; }
  .md-preview p { margin: 6px 0; }
  .md-preview img { max-width: 100%; border-radius: 6px; margin: 8px 0; box-shadow: 0 1px 4px rgba(0,0,0,.1); }
  .md-preview pre { background: #f5f7fa; padding: 10px 14px; border-radius: 6px; overflow-x: auto; font-size: 12px; margin: 8px 0; }
  .md-preview code { background: #f0f2f5; padding: 1px 5px; border-radius: 3px; font-size: 12px; }
  .md-preview pre code { background: none; padding: 0; }
  .md-preview blockquote { border-left: 3px solid #d6e2ff; margin: 8px 0; padding: 4px 12px; color: #5a6b8a; background: #f8f9fc; }
  .md-preview ul, .md-preview ol { margin: 6px 0; padding-left: 24px; }
  .md-preview li { margin: 3px 0; }
  .md-preview a { color: #409eff; }
  .md-preview hr { border: none; border-top: 1px solid #e4e7ed; margin: 12px 0; }
  .md-preview table { border-collapse: collapse; margin: 8px 0; width: 100%; }
  .md-preview th, .md-preview td { border: 1px solid #dcdfe6; padding: 6px 10px; text-align: left; font-size: 13px; }
  .md-preview th { background: #f5f7fa; font-weight: 600; }
  /* AI评论总结列截断样式 */
  .text-truncate-cell {
    display: block;
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    cursor: pointer;
  }
  @media (max-width: 900px) {
    .app-shell, .app-shell.sidebar-collapsed { grid-template-columns: 78px minmax(0, 1fr); }
    .brand { padding: 0 20px; }
    .brand-copy, .nav-label, .nav-group-title { opacity: 0; pointer-events: none; }
    .nav-subsection-title { height: 1px; margin: 8px 0; padding: 0; overflow: hidden; border: 0; }
    .nav-item { padding: 0 15px; }
    .nav-active-mark { display: none; }
    .sidebar-toggle { padding: 0 10px; justify-content: center; }
    .topbar { padding: 0 18px; }
    .topbar-context > span:first-of-type, .topbar-context > i { display: none; }
    .workspace { padding: 20px 18px; }
  }
  @media (max-width: 680px) {
    .app-shell, .app-shell.sidebar-collapsed { display: block; }
    .app-sidebar { position: fixed; inset: 0 auto 0 0; z-index: 50; width: 248px; transform: translateX(0); transition: transform .25s ease; box-shadow: 16px 0 36px rgba(10,23,39,.2); }
    .app-shell.sidebar-collapsed .app-sidebar { transform: translateX(-100%); }
    .app-sidebar .brand { padding: 0 20px; }
    .app-sidebar .brand-copy, .app-sidebar .nav-label, .app-sidebar .nav-group-title { opacity: 1; pointer-events: auto; }
    .app-sidebar .nav-subsection-title { height: auto; margin: 12px 10px 5px; padding-top: 10px; border-top: 1px solid rgba(255,255,255,.08); }
    .app-sidebar .nav-item { padding: 0 12px; }
    .app-sidebar .nav-active-mark { display: block; }
    .app-sidebar .sidebar-toggle { padding: 0 13px; justify-content: flex-start; }
    .shell-main { height: 100%; }
    .mobile-nav-toggle { display: inline-grid; place-items: center; }
    .topbar { height: 58px; flex-basis: 58px; }
    .mode-badge .status-item { width: 8px; height: 8px; padding: 0; border: 0; background: transparent; overflow: hidden; }
    .mode-badge .dot { flex: 0 0 7px; margin-left: 1px; }
    .workspace-heading { align-items: flex-start; }
    .workspace-date { display: none; }
  }
</style>
