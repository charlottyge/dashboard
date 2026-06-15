const LOCAL_PORTFOLIO_KEY = "a-share-dashboard-local-portfolio-v1";
const LOCAL_MARKDOWN_KEY = "a-share-dashboard-markdown-v1";

const tableLabels = {
  market_overview: "市场概览",
  market_sector_scan: "板块扫描",
  hot_board_front_core: "强板块中军 / 前排",
  pullback_setups: "热门股回踩观察",
  market_temperature: "竞价温度",
  sector_strength: "竞价板块强度",
  yesterday_strong_lines: "昨日强线竞价",
  watchlist_portfolio_open: "自选 / 持仓竞价",
  sector_first_impact: "第一轮冲击板块",
  candidate_first_impact: "第一轮冲击候选",
  portfolio_first_impact: "持仓第一轮冲击",
  candidate_scores: "10:30 候选评分",
  watchlist_portfolio_actions: "10:30 自选 / 持仓处理",
  portfolio_extra: "持仓额外信息",
  morning_mainlines: "上午主线",
  candidate_morning_check: "上午候选检查",
  portfolio_morning_plan: "午后预案",
  sector_afternoon_change: "午后板块变化",
  candidate_afternoon_restart: "午后候选重启",
  portfolio_afternoon_status: "午后持仓状态",
  market_close_confirm: "尾盘市场确认",
  sector_close_confirm: "尾盘板块确认",
  candidate_close_confirm: "尾盘候选确认",
  portfolio_close_confirm: "尾盘持仓确认",
  final_market: "盘后市场",
  final_sectors: "盘后板块",
  final_stocks: "盘后个股",
  portfolio_final_review: "盘后持仓复盘",
  strategy_summary: "策略汇总",
  strategy_candidates: "策略候选",
  strategy_candidates_float_excluded: "流通股过滤",
  strategy_candidates_float_unavailable: "流通股不可用",
};

let siteData = null;
let activeDay = null;
let activeCheckpointId = null;
let activeView = "radar";

function value(input, fallback = "-") {
  return input === null || input === undefined || input === "" ? fallback : input;
}

function escapeHtml(input) {
  return String(value(input, ""))
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function tableTitle(table) {
  const key = table.name.replace(/\.csv$/i, "");
  return tableLabels[key] || table.name;
}

function byId(id) {
  return document.getElementById(id);
}

function setupDateSelector() {
  const select = byId("date-select");
  if (!select) return;
  const days = siteData.timeline_days || [];
  select.innerHTML = days.map((day) => `<option value="${escapeHtml(day.date)}">${escapeHtml(day.date)}</option>`).join("");
  select.addEventListener("change", () => selectDay(select.value));
  if (days.length) selectDay(days[0].date);
}

function setupViewTabs() {
  document.querySelectorAll(".view-tab").forEach((button) => {
    button.addEventListener("click", () => {
      activeView = button.dataset.view;
      renderViewTabs();
    });
  });
  renderViewTabs();
}

function renderViewTabs() {
  document.querySelectorAll(".view-tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === activeView);
  });
  document.querySelectorAll(".app-view").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.viewPanel === activeView);
  });
}

function selectDay(date) {
  activeDay = (siteData.timeline_days || []).find((day) => day.date === date);
  activeCheckpointId = timelineCheckpoints(activeDay)?.[0]?.id || null;
  if (typeof renderPreopen === "function") renderPreopen(activeDay);
  renderTimeline();
}

function renderTimeline() {
  const checkpoints = timelineCheckpoints(activeDay);
  const subtitle = byId("timeline-subtitle");
  if (subtitle) {
    subtitle.textContent = activeDay
      ? `${activeDay.date} · ${checkpoints.length} 个 checkpoint`
      : "没有可展示的 checkpoint。";
  }
  const tabs = byId("checkpoint-tabs");
  if (!tabs) return;
  tabs.innerHTML = checkpoints
    .map(
      (item) => `
        <button class="checkpoint-tab ${item.id === activeCheckpointId ? "active" : ""}" data-id="${escapeHtml(item.id)}">
          <strong>${escapeHtml(item.label)}</strong>
          <span>${escapeHtml(item.decision?.risk_preference || "风险-")}</span>
        </button>
      `,
    )
    .join("");
  document.querySelectorAll(".checkpoint-tab").forEach((button) => {
    button.addEventListener("click", () => {
      activeCheckpointId = button.dataset.id;
      renderTimeline();
    });
  });
  const current = checkpoints.find((item) => item.id === activeCheckpointId) || checkpoints[0];
  renderCheckpoint(current);
}

function renderCheckpoint(checkpoint) {
  const target = byId("checkpoint-detail");
  if (!target) return;
  if (!checkpoint) {
    target.innerHTML = '<p class="empty">当前日期没有扫描结果。</p>';
    return;
  }
  if (isPreopenCheckpoint(checkpoint)) {
    target.innerHTML = renderPreopenTimeline();
    renderCheckpointTables(checkpoint);
    renderPortfolio();
    return;
  }
  const decision = checkpoint.decision || {};
  target.innerHTML = isStrategyCheckpoint(checkpoint)
    ? renderStrategyCheckpoint(checkpoint)
    : renderActionBrief(checkpoint);
  renderCheckpointTables(checkpoint);
  renderPortfolio();
}

function timelineCheckpoints(day) {
  if (!day) return [];
  return [
    {
      id: "preopen",
      label: "09:10 盘前预案",
      decision: { risk_preference: "预案" },
      tables: [],
    },
    ...(day.checkpoints || []),
  ];
}

function isPreopenCheckpoint(checkpoint) {
  return checkpoint?.id === "preopen";
}

function isStrategyCheckpoint(checkpoint) {
  return checkpoint?.id?.includes("strategy") || String(checkpoint?.label || "").includes("策略包");
}

function renderPreopenTimeline() {
  return renderPreopenContent(activeDay);
}

function renderActionBrief(checkpoint) {
  const decision = checkpoint.decision || {};
  const demo = checkpoint.demo_analysis || {};
  return `
    <section class="overview-panel">
      <div class="brief-kicker">${escapeHtml(checkpoint.label)}</div>
      <div class="overview-grid">
        ${renderMarketOverviewCard(checkpoint, decision, demo)}
        ${renderSectorOverviewCard(checkpoint)}
        ${renderPortfolioOverviewCard(checkpoint)}
        ${renderWatchlistOverviewCard(checkpoint)}
        ${renderNewCandidateOverviewCard(checkpoint)}
        ${renderAiActionPanel(checkpoint)}
      </div>
    </section>
    <section class="brief">
      <h3>持仓个股</h3>
      ${renderPortfolioWorkbench(checkpoint)}
    </section>
    <section class="brief">
      <h3>市场板块</h3>
      ${renderMarketSectorsSection(checkpoint, decision)}
    </section>
    <section class="brief">
      <h3>热门股回踩观察</h3>
      ${renderPullbackWorkbench(checkpoint)}
    </section>
    <section class="brief">
      <h3>Watchlist</h3>
      ${renderWatchlistWorkbench(checkpoint)}
    </section>
    <section class="brief">
      <h3>当日新增候选个股</h3>
      ${renderNewCandidatesWorkbench(checkpoint)}
    </section>
  `;
}

function renderMarketOverviewCard(checkpoint, decision, demo) {
  const analysis = checkpoint.ai_analysis || {};
  return `
    <article class="overview-card overview-card-wide">
      <h3>市场数据 + 盘面分析</h3>
      ${renderMarketSnapshot(checkpoint)}
      ${renderAiReviewParagraphs([
        analysis.summary || analysis.market_analysis || analysisTextForCheckpoint(checkpoint, decision, demo),
        analysis.index_breadth_analysis,
      ])}
    </article>
  `;
}

function renderAiAnalysisCard(checkpoint) {
  const analysis = checkpoint.ai_analysis || {};
  if (!Object.keys(analysis).length) return "";
  const sections = [
    ["盘面核心判断", analysis.summary || analysis.market_analysis],
    ["指数与赚钱效应", analysis.index_breadth_analysis],
    ["板块主线质量", analysis.sector_analysis],
    ["持仓分析", analysis.portfolio_analysis],
    ["Watchlist 分析", analysis.watchlist_analysis],
    ["新增候选分析", analysis.candidate_analysis],
  ].filter(([, text]) => text);
  return `
    <article class="overview-card overview-card-wide ai-analysis-card">
      <div class="ai-analysis-head">
        <span>AI 深度分析</span>
        ${analysis.generated_at ? `<em>${escapeHtml(analysis.generated_at)}</em>` : ""}
      </div>
      <h3>${escapeHtml(analysis.headline || "本时段深度分析")}</h3>
      <div class="ai-analysis-body">
        ${sections.map(([title, text]) => `
          <section>
            <h4>${escapeHtml(title)}</h4>
            <p>${escapeHtml(text)}</p>
          </section>
        `).join("")}
        ${renderAiAnalysisList("风险提醒", analysis.risk_warnings)}
        ${renderAiAnalysisList("下一步验证", analysis.next_validation)}
        ${renderAiAnalysisList("不要做什么", analysis.do_not_do)}
      </div>
    </article>
  `;
}

function renderAiAnalysisList(title, items) {
  const safeItems = Array.isArray(items) ? items.filter(Boolean) : [];
  if (!safeItems.length) return "";
  return `
    <section>
      <h4>${escapeHtml(title)}</h4>
      <ol>${safeItems.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ol>
    </section>
  `;
}

function renderSectorOverviewCard(checkpoint) {
  const sectors = sectorRowsForCheckpoint(checkpoint);
  const top = sectors.slice(0, 5).map((row) => row["板块"] || row["name"]).filter(Boolean);
  const analysis = checkpoint.ai_analysis || {};
  return `
    <article class="overview-card">
      <h3>板块分析概况</h3>
      <p>${escapeHtml(top.length ? `当前热门板块：${top.join("、")}。` : "当前板块强度不清晰。")}</p>
      ${renderAiReviewParagraphs([analysis.sector_analysis || `${sectorChangeText(checkpoint)} ${sectorFocusText(checkpoint)}`])}
    </article>
  `;
}

function renderPortfolioOverviewCard(checkpoint) {
  const items = portfolioSignalItems(checkpoint);
  const actionItems = items.filter((item) => item.priority === "P0" || item.tradeAlerts.length).slice(0, 3);
  const analysis = checkpoint.ai_analysis || {};
  return `
    <article class="overview-card">
      <h3>持仓概况</h3>
      <p>${escapeHtml(items.length ? `当前持仓 ${items.length} 只，${actionItems.length} 只需要重点看。` : "当前没有读取到持仓。")}</p>
      ${renderAiReviewParagraphs([analysis.portfolio_analysis || `${portfolioChangeText(checkpoint, items)} ${actionItems.length ? `重点：${actionItems.map((item) => `${item.name}（${item.action}）`).join("；")}。` : "暂无必须处理动作，继续看是否强于所属板块。"}`])}
    </article>
  `;
}

function renderWatchlistOverviewCard(checkpoint) {
  const items = watchlistSignalItems(checkpoint);
  const focus = items.filter((item) => watchlistBuyRating(item).startsWith("A")).slice(0, 4);
  const analysis = checkpoint.ai_analysis || {};
  return `
    <article class="overview-card">
      <h3>Watchlist 概况</h3>
      <p>${escapeHtml(items.length ? `最近日期 watchlist ${items.length} 只，A 评级 ${focus.length} 只。` : "没有读取到最近日期 watchlist。")}</p>
      ${renderAiReviewParagraphs([analysis.watchlist_analysis || `${watchlistChangeText(checkpoint, items)} ${focus.length ? `重点关注：${focus.map((item) => `${item.name}${item.sector ? ` / ${item.sector}` : ""}`).join("、")}。` : "暂无 A 评级重点项。"}`])}
    </article>
  `;
}

function renderNewCandidateOverviewCard(checkpoint) {
  const items = newCandidateItems(checkpoint);
  const groups = candidateGroups(items);
  const pullbacks = items.filter((item) => item.isPullback);
  const analysis = checkpoint.ai_analysis || {};
  return `
    <article class="overview-card">
      <h3>当日新增候选概况</h3>
      <p>${escapeHtml(items.length ? `当前新增候选 ${items.length} 只；当日回踩观察 ${pullbacks.length} 只，强板块强个股 ${groups.research.length} 只。` : "当前没有新增候选。")}</p>
      ${renderAiReviewParagraphs([analysis.candidate_analysis || `${candidateChangeText(checkpoint, items) || "较上一时间点：没有明显新增/退出变化。"} ${groups.research.length ? `重点：${groups.research.map((item) => item.stock).join("、")}。` : "没有直接升级为重点研究的新增候选。"}`])}
    </article>
  `;
}

function renderAiReviewParagraphs(texts) {
  const cleaned = texts.map(cleanAiText).filter(Boolean);
  if (!cleaned.length) return "";
  return `<div class="ai-inline-review">${cleaned.map((text) => `<p>${escapeHtml(text)}</p>`).join("")}</div>`;
}

function cleanAiText(text) {
  return String(text || "")
    .replace(/(?:指数：)?(?:上证|深证成指|创业板|科创50|上证50|中证2000|中小100)[^。；]*[。；]/g, "")
    .replace(/(?:涨跌家数|涨停\/跌停|成交额|运行时间|数据源|来源|asof|checkpoint)[^。；]*[。；]/gi, "")
    .replace(/AI 分析|深度分析|本时段|当前 checkpoint/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function renderAiActionPanel(checkpoint) {
  const analysis = checkpoint.ai_analysis || {};
  if (!analysis.risk_warnings?.length && !analysis.next_validation?.length && !analysis.do_not_do?.length) return "";
  return `
    <article class="overview-card overview-card-wide ai-action-card">
      <h3>风险 / 下一步 / 不要做</h3>
      <div class="ai-action-strip">
      ${renderAiMiniList("风险", analysis.risk_warnings)}
      ${renderAiMiniList("下一步", analysis.next_validation)}
      ${renderAiMiniList("不要做", analysis.do_not_do)}
      </div>
    </article>
  `;
}

function renderAiMiniList(title, items) {
  const safeItems = Array.isArray(items) ? items.filter(Boolean).slice(0, 3) : [];
  if (!safeItems.length) return "";
  return `
    <section>
      <strong>${escapeHtml(title)}</strong>
      <ul>${safeItems.map((item) => `<li>${escapeHtml(cleanAiText(item) || item)}</li>`).join("")}</ul>
    </section>
  `;
}

function renderAnalysisMarkdown(text) {
  const blocks = String(text || "")
    .split(/\n{2,}/)
    .map((item) => item.trim())
    .filter(Boolean);
  if (!blocks.length) return '<p class="market-analysis">暂无盘面分析。</p>';
  return `
    <div class="market-analysis">
      ${blocks.map(renderAnalysisBlock).join("")}
    </div>
  `;
}

function renderAnalysisBlock(block) {
  const [head, ...rest] = block.split(/：/);
  if (rest.length && head.length <= 12) {
    return `
      <section class="analysis-block">
        <h4>${escapeHtml(head)}</h4>
        <p>${escapeHtml(rest.join("：").trim())}</p>
      </section>
    `;
  }
  return `<section class="analysis-block"><p>${escapeHtml(block)}</p></section>`;
}

function renderMarketSnapshot(checkpoint) {
  const market = ["market_overview.csv", "market_close_confirm.csv", "final_market.csv"]
    .map((name) => firstTableRow(checkpoint, name))
    .find((row) => Object.keys(row).length) || {};
  const summary = checkpoint.summary || {};
  const indexText = market["指数涨幅"] || indexPartsFromMarket(market, true).join(" / ");
  const cells = [
    ["指数", indexText || "-"],
    ["成交额", formatAmount(market["成交额预估"] || market["成交额"] || "")],
    ["涨跌家数", market["涨跌家数"] || "-"],
    ["涨停/跌停", market["涨停/跌停"] || "-"],
  ];
  return `
    <div class="market-snapshot">
      ${cells
        .map(
          ([label, text]) => `
            <div>
              <span>${escapeHtml(label)}</span>
              <strong>${escapeHtml(text)}</strong>
            </div>
          `,
        )
        .join("")}
    </div>
    ${summary.snapshot_warning ? `<p class="snapshot-warning">${escapeHtml(summary.snapshot_warning)}</p>` : ""}
  `;
}

function snapshotModeText(mode) {
  if (mode === "historical_intraday") return "历史分时回看";
  if (mode === "live_preview") return "实时预览";
  if (mode === "live_checkpoint") return "实时 checkpoint";
  return mode || "-";
}

function indexPartsFromMarket(market, includeMissing = false) {
  const keys = ["上证", "深证成指", "创业板", "科创50", "上证50", "中证2000", "中小100"];
  return keys
    .map((key) => {
      const current = market[key] || market[`${key}涨幅`] || "";
      if (!current && !includeMissing) return "";
      return `${key} ${current ? `${current}%` : "-"}`;
    })
    .filter(Boolean);
}

function sectorRowsForCheckpoint(checkpoint) {
  return tableRows(checkpoint, "market_sector_scan.csv").length
    ? tableRows(checkpoint, "market_sector_scan.csv")
    : tableRows(checkpoint, "sector_close_confirm.csv").length
      ? tableRows(checkpoint, "sector_close_confirm.csv")
      : tableRows(checkpoint, "final_sectors.csv");
}

function sectorChangeText(checkpoint) {
  const previous = previousCheckpoint(checkpoint);
  if (!previous) return "较上一时间点：这是当前日期第一个可比时段。";
  const currentNames = sectorRowsForCheckpoint(checkpoint).slice(0, 6).map((row) => row["板块"] || row["name"]).filter(Boolean);
  const prevNames = sectorRowsForCheckpoint(previous).slice(0, 6).map((row) => row["板块"] || row["name"]).filter(Boolean);
  const added = currentNames.filter((name) => !prevNames.includes(name)).slice(0, 3);
  const dropped = prevNames.filter((name) => !currentNames.includes(name)).slice(0, 3);
  const parts = [];
  if (added.length) parts.push(`${added.join("、")} 强度改善`);
  if (dropped.length) parts.push(`${dropped.join("、")} 强度回落`);
  return parts.length ? `较上一时间点：${parts.join("；")}。` : "较上一时间点：板块强弱结构变化不大，继续看中军和扩散。";
}

function sectorFocusText(checkpoint) {
  const rows = sectorRowsForCheckpoint(checkpoint);
  const names = rows.slice(0, 3).map((row) => row["板块"] || row["name"]).filter(Boolean);
  if (!names.length) return "关注重点：先等待板块成交额、涨家率和领涨股重新清晰。";
  return `关注重点：${names.join("、")} 的成交额、涨家率和领涨股是否同步，同时看中军是否站稳 VWAP。`;
}

function renderPortfolioWorkbench(checkpoint) {
  const signals = portfolioSignalItems(checkpoint);
  const priority = checkpoint.decision?.portfolio_priority || [];
  if (!signals.length && !priority.length) return '<p class="empty">暂无持仓数据。请检查最近日期 portfolio.md 是否有持仓块。</p>';
  return `
    <div class="priority-defs">
      <span><b>P0</b> 必须处理</span>
      <span><b>P1</b> 重点观察</span>
      <span><b>P2</b> 正常持有</span>
      <span><b>P3</b> 暂不关注</span>
    </div>
    ${signals.length ? `<div class="stock-signal-grid">${signals.map(renderPortfolioSignalCard).join("")}</div>` : ""}
  `;
}

function renderMarketSectorsSection(checkpoint, decision) {
  return `
    <div class="section-note">${escapeHtml(sectorChangeText(checkpoint))}</div>
    <div class="mainline-groups compact">
      ${renderMainlineGroup("仍在走强", (decision.confirmed_mainlines || []).slice(0, 4), "strong")}
      ${renderMainlineGroup("走弱 / 不再主攻", (decision.weakening_mainlines || []).slice(0, 4), "weak")}
      ${renderMainlineGroup("新改善方向", (decision.new_improving_lines || []).slice(0, 4), "improving")}
    </div>
  `;
}

function renderPullbackWorkbench(checkpoint) {
  const rows = tableRows(checkpoint, "pullback_setups.csv");
  if (!rows.length) {
    return '<p class="empty">暂无热门股回踩观察。只把曾经强过、板块还没死、回踩关键线附近的个股放进这里。</p>';
  }
  const groups = [
    ["已确认", rows.filter((row) => row["分类"] === "回踩确认")],
    ["待确认", rows.filter((row) => row["分类"] === "回踩待确认" || row["分类"] === "只观察")],
    ["失败/剔除", rows.filter((row) => row["分类"] === "失败/剔除")],
  ].filter(([, items]) => items.length);
  return `
    <div class="section-note">回踩确认 ≠ 立即买入；它只表示强股从“不可追高”变成“有观察价值”。板块弱、跌破均线、只因跌多反弹的，不算机会。</div>
    <div class="pullback-groups">
      ${groups.map(([title, items]) => renderPullbackGroup(title, items)).join("")}
    </div>
  `;
}

function renderPullbackGroup(title, rows) {
  return `
    <section class="pullback-group">
      <div class="pullback-group-title">
        <h4>${escapeHtml(title)}</h4>
        <span>${escapeHtml(rows.length)} 条</span>
      </div>
      <div class="stock-signal-grid">
        ${rows.slice(0, title === "失败/剔除" ? 4 : 8).map(renderPullbackCard).join("")}
      </div>
    </section>
  `;
}

function renderPullbackCard(row) {
  const stock = row["股票"] || "-";
  const metrics = [
    row["当前涨幅"] !== "" ? `涨幅 ${row["当前涨幅"]}%` : "",
    row["板块排名"] !== "" ? `板块 #${row["板块排名"]}` : "",
    row["分数"] !== "" ? `分数 ${row["分数"]}` : "",
  ].filter(Boolean);
  const lines = [
    row["MA5"] ? `MA5 ${row["MA5"]}` : "",
    row["MA10"] ? `MA10 ${row["MA10"]}` : "",
    row["MA20"] ? `MA20 ${row["MA20"]}` : "",
    row["VWAP"] ? `VWAP ${row["VWAP"]}` : "",
    row["上午低点"] ? `低点 ${row["上午低点"]}` : "",
  ].filter(Boolean);
  return `
    <article class="stock-signal-card pullback-card ${row["分类"] === "回踩确认" ? "urgent" : ""}">
      <strong>${escapeHtml(stock)}</strong>
      <span>${escapeHtml([row["板块"], row["回踩类型"]].filter(Boolean).join(" · "))}</span>
      <p>${escapeHtml(row["走势自然语言"] || row["状态"] || "")}</p>
      <div class="pill-row compact">
        ${metrics.map((item) => `<span class="pill">${escapeHtml(item)}</span>`).join("")}
      </div>
      <em>状态：${escapeHtml(row["状态"] || row["分类"] || "-")} · ${escapeHtml(row["VWAP状态"] || "")}</em>
      <em>关键线：${escapeHtml(lines.join(" / ") || "-")}</em>
      <em>下一步：${escapeHtml(row["下一步"] || "-")}</em>
      ${row["风险"] ? `<em class="risk-text">风险：${escapeHtml(row["风险"])}</em>` : ""}
    </article>
  `;
}

function sectorTeachingText(name) {
  if (/CPO|光通信|光纤|算力|半导体|芯片|存储/.test(name)) return "科技成长方向，重点看中军承接和个股扩散。";
  if (/煤炭|石油|电力|银行|保险|红利/.test(name)) return "资源/防守方向，重点看是否能在科技分歧时逆势。";
  if (/次新/.test(name)) return "情绪弹性方向，重点看次日承接，不适合只按涨幅追。";
  return "只看涨幅不够，还要看成交额、中军和持续性。";
}

function renderWatchlistWorkbench(checkpoint) {
  const items = watchlistSignalItems(checkpoint);
  if (!items.length) return '<p class="empty">暂无最近日期 watchlist 数据。</p>';
  const focusItems = items.filter(isWorthWatching).sort(watchlistSort);
  const backupItems = items.filter((item) => !isWorthWatching(item)).sort(watchlistSort);
  const focusA = focusItems.filter(isBuyRatingA);
  const focusHidden = focusItems.filter((item) => !isBuyRatingA(item));
  const backupA = backupItems.filter(isBuyRatingA);
  const backupHidden = backupItems.filter((item) => !isBuyRatingA(item));
  return `
    ${renderWatchlistBucket("重点", focusA, focusHidden)}
    ${renderWatchlistBucket("备选", backupA, backupHidden)}
  `;
}

function renderWatchlistBucket(title, visible, hidden) {
  return `
    <section class="watchlist-bucket">
      <h4>${escapeHtml(title)}</h4>
      ${visible.length ? `<div class="stock-signal-grid">${visible.map(renderWatchlistSignalCard).join("")}</div>` : '<p class="empty">暂无 A 评级。</p>'}
      ${
        hidden.length
          ? `<details class="collapsed-stock-list">
              <summary>展开${escapeHtml(title)}里的非 A 评级（${hidden.length} 只）</summary>
              <div class="stock-signal-grid">${hidden.map(renderWatchlistSignalCard).join("")}</div>
            </details>`
          : ""
      }
    </section>
  `;
}

function renderNewCandidatesWorkbench(checkpoint) {
  const items = newCandidateItems(checkpoint);
  const groups = candidateGroups(items);
  if (!items.length) return '<p class="empty">当前时段没有新增候选。</p>';
  return `
    <div class="candidate-layers">
      ${renderCandidateLayer("当日回踩观察", "回踩且待确认，重点看 VWAP、均线和板块是否继续承接。", groups.pullbackWatch)}
      ${renderCandidateLayer("强板块、强个股、有承接", "板块强、个股强、承接相对清楚；仍然不是直接买入。", groups.research)}
      ${
        groups.hidden.length
          ? `<details class="collapsed-stock-list">
              <summary>展开其他新增候选（${groups.hidden.length} 只）</summary>
              <div class="candidate-layers compact">
                ${renderCandidateLayer("继续观察", "有异动但还需要下一 checkpoint 证明。", groups.observe)}
                ${renderCandidateLayer("不建议追高", "涨幅过高、VWAP 失守、长上影或承接未知。", groups.avoid)}
              </div>
            </details>`
          : ""
      }
    </div>
  `;
}

function currentWatchlistItems() {
  return siteData?.watchlist?.current_items || [];
}

function portfolioSignalItems(checkpoint) {
  return mergedHoldings().map((holding) => {
    const name = holding.name || holding.stock || holding.code || "-";
    const row = findStockContextRowInCheckpoint(checkpoint, name, holding.code);
    const priorityItem = (checkpoint.decision?.portfolio_priority || []).find((item) => stockMatches(item.stock, name, holding.code));
    const priority = priorityItem?.priority || "P2";
    return buildStockSignal({
      name,
      code: holding.code || "",
      priority,
      priorityItem,
      sector: row["板块"] || holding.sector || "",
      role: holding.role || "持仓",
      note: holding.note || "",
      row,
      kind: "portfolio",
    });
  });
}

function watchlistSignalItems(checkpoint) {
  return currentWatchlistItems().map((item) => {
    const row = findStockContextRowInCheckpoint(checkpoint, item.name, item.code);
    return buildStockSignal({
      name: item.name || item.code || "-",
      code: item.code || "",
      priority: item.priority || "P2",
      sector: row["板块"] || row["匹配板块"] || item.sector || "",
      role: item.role || "watchlist",
      note: item.note || item.raw || "",
      row,
      kind: "watchlist",
    });
  });
}

function newCandidateItems(checkpoint) {
  const watchKeys = new Set(currentWatchlistItems().map((item) => normalizeStockKey(`${item.name || ""}${item.code || ""}`)));
  const holdKeys = new Set(mergedHoldings().map((item) => normalizeStockKey(`${item.name || ""}${item.code || ""}`)));
  const standardRows = candidateRowsForCheckpoint(checkpoint).rows;
  const pullbackRows = tableRows(checkpoint, "pullback_setups.csv");
  return [...pullbackRows, ...standardRows]
    .map(candidateInsight)
    .filter((item) => {
      const key = normalizeStockKey(item.stock);
      if (!key) return false;
      const inWatch = [...watchKeys].some((watchKey) => watchKey && (watchKey.includes(key) || key.includes(watchKey)));
      const inHold = [...holdKeys].some((holdKey) => holdKey && (holdKey.includes(key) || key.includes(holdKey)));
      return !inWatch && !inHold;
    });
}

function buildStockSignal({ name, code, priority, priorityItem, sector, role, note, row, kind }) {
  const tradeAlerts = tradeAlertTexts(row);
  const news = meaningfulExternalText(row["新闻"] || row["news"]);
  const announcement = meaningfulExternalText(row["公告"] || row["announcement"]);
  const action = stockSignalAction(priority, tradeAlerts, kind);
  return { name, code, priority, priorityItem, sector, role, note, row, kind, tradeAlerts, news, announcement, action };
}

function renderPortfolioSignalCard(item) {
  const insight = buildPortfolioInsight(item.priorityItem || { stock: [item.name, item.code].filter(Boolean).join(" "), priority: item.priority });
  const plan = portfolioTimeframePlan(item, insight);
  const abnormal = abnormalMoveText(item);
  return `
    <article class="stock-signal-card portfolio-signal-card ${item.priority === "P0" ? "urgent" : ""}">
      <div class="candidate-topline">
        <strong>${escapeHtml([item.name, item.code].filter(Boolean).join(" "))}</strong>
      </div>
      <p>走势 / 成交量：${escapeHtml(stockTrendVolumeText(item))}</p>
      <p>状态：${escapeHtml(portfolioStatusText(item, insight))}</p>
      <p>观察线：短线 ${escapeHtml(plan.lines.short)}｜中线 ${escapeHtml(plan.lines.mid)}｜长线 ${escapeHtml(plan.lines.long)}</p>
      <p>动作：短线 ${escapeHtml(plan.actions.short)}｜中线 ${escapeHtml(plan.actions.mid)}｜长线 ${escapeHtml(plan.actions.long)}</p>
      ${abnormal ? `<p>异动：${escapeHtml(abnormal)}</p>` : ""}
      ${item.news ? `<p>新闻：${escapeHtml(item.news)}</p>` : ""}
      ${item.announcement ? `<p>公告：${escapeHtml(item.announcement)}</p>` : ""}
    </article>
  `;
}

function renderWatchlistSignalCard(item) {
  return `
    <article class="stock-signal-card ${item.priority === "P0" ? "urgent" : ""}">
      <div class="candidate-topline">
        <strong>${escapeHtml([item.name, item.code].filter(Boolean).join(" "))}</strong>
      </div>
      <p>走势 / 成交量：${escapeHtml(stockTrendVolumeText(item))}</p>
      <p>板块情况：${escapeHtml(watchlistSectorText(item))}</p>
      <p>为什么值得关注：${escapeHtml(watchlistFocusReason(item))}</p>
      <p>下一步动作：${escapeHtml(watchlistNextAction(item))}</p>
      <p>买入评级：${escapeHtml(watchlistBuyRating(item))}</p>
    </article>
  `;
}

function tradeAlertTexts(row) {
  const alerts = [];
  const pct = row["当前涨幅"] || row["当前涨幅%"] || row["收盘涨幅"] || row["pct"] || "";
  const drawdown = num(row["高点回撤%"] || row["今日高点回撤%"]);
  const vwap = candidateVwapState(row);
  const relative = row.relative_strength_vs_sector || row["是否强于板块"] || "";
  if (pct !== "") alerts.push(`涨幅 ${pct}%`);
  if (vwap === "下") alerts.push("VWAP 下方，承接不足");
  if (vwap === "上") alerts.push("VWAP 上方，承接尚可");
  if (drawdown <= -4) alerts.push(`高点回撤 ${drawdown}%`);
  if (relative === "False" || relative === "否") alerts.push("弱于所属板块");
  if (row.invalid_condition === "是") alerts.push("触发风险条件");
  return alerts;
}

function meaningfulExternalText(text) {
  const value = String(text || "").trim();
  if (!value) return "";
  if (/未接入|unavailable|暂无|无明显|没有/.test(value)) return "";
  return value;
}

function stockTrendVolumeText(item) {
  const row = item.row || {};
  const trend = row["走势自然语言"] || row["走势"] || row["日K形态"] || trendLanguage(row);
  return [trend, volumeLanguage(row)].filter(Boolean).join(" ");
}

function trendLanguage(row) {
  const pct = row["当前涨幅"] || row["当前涨幅%"] || row["收盘涨幅"] || row["pct"] || "";
  const drawdown = num(row["高点回撤%"] || row["今日高点回撤%"]);
  const vwap = candidateVwapState(row);
  const parts = [];
  if (pct !== "") parts.push(`当前涨幅 ${pct}%`);
  if (vwap === "上") parts.push("价格在 VWAP 上方，盘中承接尚可");
  if (vwap === "下") parts.push("价格在 VWAP 下方，承接偏弱");
  if (drawdown <= -5) parts.push(`高点回撤 ${drawdown}%，冲高回落明显`);
  else if (drawdown < 0) parts.push(`高点回撤 ${drawdown}%，仍需看回落承接`);
  if (!parts.length) return "走势数据不足，先按下一 checkpoint 复核。";
  return `${parts.join("，")}。`;
}

function abnormalMoveText(item) {
  const row = item.row || {};
  const alerts = (item.tradeAlerts || []).filter((text) => /回撤|风险|弱于|VWAP 下方/.test(text));
  const risk = meaningfulExternalText(row["异动"] || row["异常"] || row["风险标记"] || "");
  return [risk, ...alerts].filter(Boolean).join("；");
}

function volumeLanguage(row) {
  const ratio = num(row["量比"] || row["volume_ratio"]);
  const amount = row["成交额"] || row["成交额(亿)"] || "";
  const parts = [];
  if (ratio >= 3) parts.push(`量比 ${ratio.toFixed(1)}，明显放量`);
  else if (ratio >= 1.5) parts.push(`量比 ${ratio.toFixed(1)}，温和放量`);
  else if (ratio > 0 && ratio < 0.8) parts.push(`量比 ${ratio.toFixed(1)}，成交偏缩`);
  else if (ratio > 0) parts.push(`量比 ${ratio.toFixed(1)}，成交正常`);
  if (amount !== "") parts.push(`成交额 ${formatAmount(amount)}`);
  return parts.length ? `成交量：${parts.join("，")}。` : "";
}

function isWorthWatching(item) {
  const row = item.row || {};
  const pct = num(row["当前涨幅"] || row["当前涨幅%"] || row["收盘涨幅"] || row["pct"]);
  const vwap = candidateVwapState(row);
  const strong = row.relative_strength_vs_sector === "True" || row["是否强于板块"] === "是";
  const source = `${row["来源"] || ""} ${item.note || ""}`;
  if (item.priority === "P0" || item.priority === "P1") return true;
  if (vwap === "上" && (strong || pct >= 2)) return true;
  if (/放量突破|缩量回踩|策略|重点|核心/.test(source) && vwap !== "下") return true;
  return false;
}

function isBuyRatingA(item) {
  return watchlistBuyRating(item).startsWith("A");
}

function watchlistSort(a, b) {
  const rank = { P0: 0, P1: 1, P2: 2, P3: 3 };
  const ar = rank[a.priority] ?? 4;
  const br = rank[b.priority] ?? 4;
  if (ar !== br) return ar - br;
  return watchScore(b) - watchScore(a);
}

function watchScore(item) {
  const row = item.row || {};
  let score = 0;
  if (candidateVwapState(row) === "上") score += 2;
  if (row.relative_strength_vs_sector === "True" || row["是否强于板块"] === "是") score += 2;
  if (num(row["当前涨幅"] || row["当前涨幅%"] || row["收盘涨幅"] || row["pct"]) >= 2) score += 1;
  if (num(row["量比"] || row["volume_ratio"]) >= 1.5) score += 1;
  return score;
}

function watchlistSectorText(item) {
  const row = item.row || {};
  const sector = item.sector || "未匹配板块";
  const sectorPct = row["板块涨幅"] || row["sector_pct"] || "";
  const relative = row.relative_strength_vs_sector === "True" || row["是否强于板块"] === "是"
    ? "强于所属板块"
    : row.relative_strength_vs_sector === "False" || row["是否强于板块"] === "否"
    ? "弱于所属板块"
    : "相对板块强弱待确认";
  return `${sector}${sectorPct !== "" ? `涨幅 ${sectorPct}%` : ""}，${relative}。`;
}

function watchlistFocusReason(item) {
  const row = item.row || {};
  const reasons = [];
  if (candidateVwapState(row) === "上") reasons.push("站在 VWAP 上方，说明盘中承接暂时可看");
  if (num(row["量比"] || row["volume_ratio"]) >= 1.5) reasons.push("成交量放大，资金参与度提高");
  if (row.relative_strength_vs_sector === "True" || row["是否强于板块"] === "是") reasons.push("强于所属板块，不是单纯跟涨");
  if (item.priority === "P0" || item.priority === "P1") reasons.push("watchlist 重要级靠前，需要优先验证");
  if (!reasons.length) return "暂时没有形成强信号，放在折叠区，只做低频观察。";
  return `${reasons.join("；")}。`;
}

function watchlistNextAction(item) {
  const row = item.row || {};
  const rating = watchlistBuyRating(item);
  if (rating.includes("不追")) return "不追高；等回落承接、VWAP 修复或下一 checkpoint 重新确认。";
  if (rating.includes("观察买点")) return "只在站稳 VWAP、强于板块且回撤不破关键位时观察，不把单点信号当买入指令。";
  return "继续跟踪板块和个股承接，未触发条件前不行动。";
}

function watchlistBuyRating(item) {
  const row = item.row || {};
  const pct = num(row["当前涨幅"] || row["当前涨幅%"] || row["收盘涨幅"] || row["pct"]);
  const drawdown = num(row["高点回撤%"] || row["今日高点回撤%"]);
  const vwap = candidateVwapState(row);
  const strong = row.relative_strength_vs_sector === "True" || row["是否强于板块"] === "是";
  if (pct >= 8 || drawdown <= -5 || vwap === "下") return "C｜不追";
  if (vwap === "上" && strong && pct >= 1.5) return "A｜观察买点";
  if (isWorthWatching(item)) return "B｜继续观察";
  return "D｜低优先";
}

function portfolioStatusText(item, insight) {
  const map = {
    P0: "必须处理：风险已触发或接近触发，先看修复，不补弱。",
    P1: "重点观察：还没完全失效，但接近关键位置。",
    P2: "正常持有：未见明确失效，按计划等待下一次确认。",
    P3: "暂不关注：当前没有明确触发条件，低频复核。",
  };
  return `${map[item.priority] || map.P2} ${insight.status || ""}`.trim();
}

function portfolioTimeframePlan(item, insight) {
  const row = item.row || {};
  const current = row["当前价"] || row.current_price || "";
  const shortRisk = row["关键位"] || row["上午低点"] || "VWAP / 上午低点";
  const midRisk = row["昨收"] || row["昨日低点"] || row["计划失效线"] || "昨日低点 / 5日线";
  const longRisk = row["中线失效线"] || row["长期逻辑"] || "持仓 thesis / 周线结构";
  const weak = item.priority === "P0" || candidateVwapState(row) === "下";
  const active = candidateVwapState(row) === "上" && (row.relative_strength_vs_sector === "True" || row["是否强于板块"] === "是");
  return {
    lines: {
      short: current ? `当前 ${current}，看 ${shortRisk}` : shortRisk,
      mid: midRisk,
      long: longRisk,
    },
    actions: {
      short: weak ? "不补仓；下一 checkpoint 不修复则降风险" : active ? "继续看 VWAP 和板块强弱" : "等待承接确认",
      mid: weak ? "跌破计划线则降低仓位或退出观察" : "只要逻辑线未破，按中线计划复核",
      long: "只看 thesis 是否失效，不因盘中单点波动改长期判断",
    },
  };
}

function stockSignalAction(priority, alerts, kind) {
  if (priority === "P0") return "优先处理，不补弱；下一 checkpoint 仍不修复则降风险。";
  if (alerts.some((text) => text.includes("VWAP 下方") || text.includes("弱于"))) return kind === "portfolio" ? "先观察修复，不加仓。" : "只观察，不追。";
  if (alerts.some((text) => text.includes("VWAP 上方"))) return "继续观察是否强于板块，不把单点信号当买入指令。";
  return "等待下一 checkpoint 数据确认。";
}

function findStockContextRowInCheckpoint(checkpoint, name, code = "") {
  const rows = (checkpoint?.tables || []).flatMap((table) => table.rows || []);
  return rows.find((row) => stockMatches(row["股票"] || `${row.name || ""} ${row.code || ""}`, name, code)) || {};
}

function stockMatches(input, name, code = "") {
  const key = normalizeStockKey(input);
  const nameKey = normalizeStockKey(name);
  const codeKey = normalizeStockKey(code);
  return Boolean(key && ((nameKey && (key.includes(nameKey) || nameKey.includes(key))) || (codeKey && key.includes(codeKey))));
}

function portfolioChangeText(checkpoint, items) {
  const previous = previousCheckpoint(checkpoint);
  if (!previous) return "较上一时间点：这是当前日期第一个持仓扫描时段。";
  const before = portfolioSignalItems(previous);
  const beforeRisk = new Set(before.filter((item) => item.priority === "P0" || item.tradeAlerts.length).map((item) => normalizeStockKey(item.name)));
  const nowRisk = new Set(items.filter((item) => item.priority === "P0" || item.tradeAlerts.length).map((item) => normalizeStockKey(item.name)));
  const eased = [...beforeRisk].filter((key) => !nowRisk.has(key)).slice(0, 3);
  const added = [...nowRisk].filter((key) => !beforeRisk.has(key)).slice(0, 3);
  const parts = [];
  if (added.length) parts.push(`${added.join("、")} 新增风险/异动`);
  if (eased.length) parts.push(`${eased.join("、")} 不再触发上一时段风险`);
  return parts.length ? `较上一时间点：${parts.join("；")}。` : "较上一时间点：持仓风险结构变化不大。";
}

function watchlistChangeText(checkpoint, items) {
  const previous = previousCheckpoint(checkpoint);
  if (!previous) return "较上一时间点：这是当前日期第一个 watchlist 扫描时段。";
  const before = watchlistSignalItems(previous);
  const beforeStrong = new Set(before.filter((item) => item.tradeAlerts.some((text) => text.includes("VWAP 上方"))).map((item) => normalizeStockKey(item.name)));
  const nowStrong = new Set(items.filter((item) => item.tradeAlerts.some((text) => text.includes("VWAP 上方"))).map((item) => normalizeStockKey(item.name)));
  const improved = [...nowStrong].filter((key) => !beforeStrong.has(key)).slice(0, 3);
  const faded = [...beforeStrong].filter((key) => !nowStrong.has(key)).slice(0, 3);
  const parts = [];
  if (improved.length) parts.push(`${improved.join("、")} 新站上/维持承接`);
  if (faded.length) parts.push(`${faded.join("、")} 承接信号消失`);
  return parts.length ? `较上一时间点：${parts.join("；")}。` : "较上一时间点：watchlist 变化不大，继续按板块和重要级观察。";
}

function groupBy(items, keyFn) {
  const groups = new Map();
  for (const item of items) {
    const key = keyFn(item);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  }
  return groups;
}

function analysisTextForCheckpoint(checkpoint, decision, demo) {
  if (isAfterCloseCheckpoint(checkpoint)) return afterCloseReviewText(checkpoint);
  if (isTurnoverCheckpoint(checkpoint)) return turnoverConfirmText(checkpoint);
  return demo.verdict || conclusionText(decision);
}

function isAfterCloseCheckpoint(checkpoint) {
  return checkpoint?.id === "scan_1510" || String(checkpoint?.label || "").includes("盘后");
}

function isTurnoverCheckpoint(checkpoint) {
  return checkpoint?.id === "scan_1030" || String(checkpoint?.label || "").includes("10:30");
}

function turnoverConfirmText(checkpoint) {
  const market = firstTableRow(checkpoint, "market_overview.csv");
  const sectors = tableRows(checkpoint, "market_sector_scan.csv");
  const candidates = candidateRowsForCheckpoint(checkpoint).rows;
  const topSectors = sectors.slice(0, 3).map((row) => row["板块"]).filter(Boolean);
  const [up, down] = parsePair(market["涨跌家数"]);
  const vwapUp = candidates.filter((row) => candidateVwapState(row) === "上").length;
  const candidateCount = candidates.length;
  const indexText = indexPartsFromMarket(market).join("、");
  const breadth = up && down && up < down
    ? `但涨跌家数为 ${up}/${down}，仍是跌多涨少，说明不是普涨，而是少数强方向拉动指数。`
    : `涨跌家数为 ${market["涨跌家数"] || "-"}，需要继续看赚钱效应是否扩散。`;
  const vwapQuality = vwapUp === 0
    ? `候选 ${candidateCount} 条里没有站上 VWAP 的明确买点，这是承接不足信号。当前不能把板块涨幅等同于个股承接。`
    : `候选 ${candidateCount} 条里有 ${vwapUp} 条站上 VWAP，但仍要区分中军承接和小票脉冲，不能只看板块涨幅。`;
  const mainline = topSectors.length
    ? `板块强势方向集中在 ${topSectors.join("、")}，说明资金早盘回流 AI 硬件 / 光通信方向。`
    : "板块强度不清晰，10:30 不能升级为主线确认。";
  return [
    `10:30 换手确认：指数强、科技强，但个股仍分化。${indexText}，${breadth}`,
    `${mainline}${vwapQuality}`,
    turnoverHoldingSentence(checkpoint),
    turnoverCandidateSentence(checkpoint),
    "操作倾向：10:30 不追高，只观察核心股能否重新站稳 VWAP；11:20 如果核心股仍不能收回 VWAP，早盘科技强度要从“主线确认”降级为“冲高反抽”。",
  ].join("\n\n");
}

function turnoverHoldingSentence(checkpoint) {
  const p0 = (checkpoint.decision?.portfolio_priority || []).filter((item) => item.priority === "P0").slice(0, 3);
  if (!p0.length) return "持仓处理：暂无 P0，但仍要看持仓是否强于所属板块，不能因为指数强就默认个股安全。";
  return `持仓处理：${p0.map((item) => item.stock).join("、")} 是 P0。问题不是“跌了所以危险”，而是科技指数很强时它没有同步修复；没有明确价格线时，先用 VWAP、所属板块强弱和 11:20 是否修复来执行，不补弱。`;
}

function turnoverCandidateSentence(checkpoint) {
  const items = candidateRowsForCheckpoint(checkpoint).rows.map(candidateInsight);
  const named = items.filter((item) => /中际旭创|新易盛|罗博特科|天孚通信|亨通光电/.test(item.stock)).slice(0, 4);
  const sample = named.length ? named : candidateGroups(items).research.slice(0, 3);
  if (!sample.length) return "候选观察：当前候选只作为观察池，不是买入清单。";
  return `候选观察：${sample.map((item) => `${item.stock}｜${candidateRole(item)}`).join("；")}。11:20 看它们是否强于板块并站稳 VWAP；如果核心股不稳，单独弹性票强不算主线确认。`;
}

function afterCloseReviewText(checkpoint) {
  const market = ["market_overview.csv", "final_market.csv"].map((name) => firstTableRow(checkpoint, name)).find((row) => Object.keys(row).length) || {};
  const sectors = tableRows(checkpoint, "final_sectors.csv").length ? tableRows(checkpoint, "final_sectors.csv") : tableRows(checkpoint, "market_sector_scan.csv");
  const topSectors = sectors.slice(0, 3).map((row) => row["板块"] || row["name"]).filter(Boolean);
  const indexText = indexPartsFromMarket(market);
  const [up, down] = parsePair(market["涨跌家数"]);
  const [limitUp, limitDown] = parsePair(market["涨停/跌停"]);
  const breadthText = up && down && up < down ? `但涨跌家数为 ${up}/${down}，说明指数上涨并不等于普涨，资金集中在少数方向。` : `涨跌家数为 ${market["涨跌家数"] || "-"}，需要结合板块扩散判断赚钱效应。`;
  const topText = topSectors.length ? `收盘强势方向是 ${topSectors.join("、")}。${afterCloseSectorQuality(topSectors)}` : "收盘强势方向不清晰，明天先看竞价和 09:45 承接。";
  const emotionText = limitUp || limitDown ? `涨停 ${limitUp} 家、跌停 ${limitDown} 家，情绪没有崩，但整体扩散不足。` : "";
  return [
    `今日盘面：指数修复，但个股分化。${indexText.join("、")}，${breadthText}`,
    `${emotionText} 结论是：今天适合复盘强线验证，不适合把指数上涨理解成随便买都能赚钱。`,
    `主线与板块结构：${topText}`,
    afterCloseHoldingSentence(checkpoint),
    afterCloseCandidateSentence(checkpoint),
    `明日预案：第一，看 ${topSectors[0] || "强势方向"} 是否只是当日情绪，还是能在竞价和 09:45 延续；第二，看资源/防守方向能否在科技分歧时逆势；第三，如果科创/创业继续强但个股仍跌多涨少，就降低出手频率，只看强分支确认。`,
  ].filter(Boolean).join("\n\n");
}

function afterCloseSectorQuality(names) {
  return names.map((name) => {
    if (/次新/.test(name)) return `${name}偏情绪弹性，持续性要看明天竞价和 09:45 承接，不能因为涨幅靠前就追。`;
    if (/石油|煤炭|电力|银行|保险|红利/.test(name)) return `${name}偏资源/防守修复，只有在科技分歧时仍强，才说明防守线有效。`;
    if (/CPO|光通信|半导体|芯片|科创|电子/.test(name)) return `${name}偏科技成长，重点看是否从指数强扩散到个股赚钱效应。`;
    return `${name}需要看中军、领涨股、补涨是否同步，不能只看板块涨幅。`;
  }).join(" ");
}

function afterCloseHoldingSentence(checkpoint) {
  const priorities = checkpoint.decision?.portfolio_priority || [];
  const p0 = priorities.filter((item) => item.priority === "P0");
  const p1 = priorities.filter((item) => item.priority === "P1");
  if (p0.length) return `持仓验证：${p0.slice(0, 3).map((item) => item.stock).join("、")} 仍是 P0，说明风险没有消失，明天开盘先看修复线，不补弱。`;
  if (p1.length) return `持仓验证：暂无 P0，但 ${p1.slice(0, 3).map((item) => item.stock).join("、")} 仍需重点观察。没有 P0 不代表全部强，只代表暂未触发最紧急风控。`;
  return "持仓验证：暂无 P0/P1 风险，但这不等于持仓都强，只说明没有触发紧急风控，明天仍要看是否强于所属板块。";
}

function afterCloseCandidateSentence(checkpoint) {
  const { rows } = candidateRowsForCheckpoint(checkpoint);
  const items = rows.map(candidateInsight);
  const focus = candidateGroups(items).research.slice(0, 3);
  const risky = items.filter((item) => item.riskLevel === "high").slice(0, 3);
  if (focus.length) return `候选验证：${focus.map((item) => item.stock).join("、")} 放入明日观察池；明天不看“是否继续涨”，而看高开后能否承接、是否强于板块、是否站稳 VWAP。`;
  if (risky.length) return `候选验证：${risky.map((item) => item.stock).join("、")} 更适合放入不追高清单，明天只看修复和承接，不做开盘追涨。`;
  return `候选验证：当前候选 ${items.length} 条，盘后只做明日观察池，不再使用“下一 checkpoint”盘中话术。`;
}

function renderHoldingSummary(checkpoint) {
  const priorities = checkpoint.decision?.portfolio_priority || [];
  const p0 = priorities.filter((item) => item.priority === "P0").slice(0, 3);
  const p1 = priorities.filter((item) => item.priority === "P1").slice(0, 3);
  const changeText = holdingChangeText(checkpoint);
  const text = isTurnoverCheckpoint(checkpoint) && p0.length
    ? `${p0.map((item) => item.stock).join("、")} 是 P0。科技指数强时仍未同步修复，说明要看个股承接；没有明确价格线时，不写假修复线，11:20 以 VWAP / 板块强弱 / 风控线确认。`
    : p0.length
    ? `优先处理：${p0.map((item) => item.stock).join("、")}。先看修复线，不补弱。`
    : p1.length
      ? `重点观察：${p1.map((item) => item.stock).join("、")}。站回修复线才说明风险缓和。`
      : "暂无 P0/P1 持仓风险，按尾盘或下一 checkpoint 复核。";
  return `
    <article class="summary-box">
      <h4>持仓总结</h4>
      <p>${escapeHtml(text)}</p>
      ${changeText ? `<p class="summary-change">${escapeHtml(changeText)}</p>` : ""}
    </article>
  `;
}

function renderCandidateSummary(checkpoint) {
  const { rows } = candidateRowsForCheckpoint(checkpoint);
  const items = rows.map(candidateInsight);
  const risky = items.filter((item) => item.riskLevel === "high").slice(0, 3);
  const focus = candidateGroups(items).research.slice(0, 3);
  const changeText = candidateChangeText(checkpoint, items);
  const text = isTurnoverCheckpoint(checkpoint)
    ? turnoverCandidateSummaryText(items)
    : isAfterCloseCheckpoint(checkpoint)
    ? focus.length
      ? `明日观察：${focus.map((item) => item.stock).join("、")}；明天看竞价、09:45 承接和 VWAP，不追高。`
      : risky.length
        ? `明日不追：${risky.map((item) => item.stock).join("、")} 已有承接或高位风险。`
        : `当前候选 ${items.length} 条，盘后只进入明日观察池。`
    : focus.length
      ? `重点研究：${focus.map((item) => item.stock).join("、")}；仍需下一 checkpoint 确认。`
      : risky.length
        ? `不建议追高：${risky.map((item) => item.stock).join("、")} 已有承接或高位风险。`
        : `当前候选 ${items.length} 条，先按板块、VWAP、回撤分层观察。`;
  return `
    <article class="summary-box">
      <h4>候选总结</h4>
      <p>${escapeHtml(text)}</p>
      ${changeText ? `<p class="summary-change">${escapeHtml(changeText)}</p>` : ""}
    </article>
  `;
}

function previousCheckpoint(checkpoint) {
  const checkpoints = activeDay?.checkpoints || [];
  const index = checkpoints.findIndex((item) => item.id === checkpoint?.id);
  if (index <= 0) return null;
  if (isStrategyCheckpoint(checkpoint)) return checkpoints[index - 1];
  for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
    if (!isStrategyCheckpoint(checkpoints[cursor])) return checkpoints[cursor];
  }
  return null;
}

function holdingChangeText(checkpoint) {
  const previous = previousCheckpoint(checkpoint);
  if (!previous || isStrategyCheckpoint(previous)) return "";
  const prevImportant = (previous.decision?.portfolio_priority || []).filter((item) => ["P0", "P1"].includes(item.priority));
  if (!prevImportant.length) return "";
  const current = checkpoint.decision?.portfolio_priority || [];
  const currentKeys = new Set(current.filter((item) => ["P0", "P1"].includes(item.priority)).map((item) => normalizeStockKey(item.stock)));
  const missing = prevImportant.filter((item) => !currentKeys.has(normalizeStockKey(item.stock))).slice(0, 3);
  if (!missing.length) return "";
  return `较上一时间点：${missing.map((item) => item.stock).join("、")} 不再列入 P0/P1，说明当前表里没有继续触发高优先级风险；但这不是“完全安全”，仍要看是否强于板块和 VWAP。`;
}

function candidateChangeText(checkpoint, currentItems) {
  const previous = previousCheckpoint(checkpoint);
  if (!previous || isStrategyCheckpoint(previous)) return "";
  const prevItems = candidateRowsForCheckpoint(previous).rows.map(candidateInsight);
  const prevMentioned = candidateGroups(prevItems).research.concat(prevItems.filter((item) => item.riskLevel === "high")).slice(0, 5);
  if (!prevMentioned.length) return "";
  const currentByKey = new Map(currentItems.map((item) => [normalizeStockKey(item.stock), item]));
  const currentResearchKeys = new Set(candidateGroups(currentItems).research.map((item) => normalizeStockKey(item.stock)));
  const changed = prevMentioned
    .filter((item) => !currentResearchKeys.has(normalizeStockKey(item.stock)))
    .slice(0, 3)
    .map((item) => {
      const now = currentByKey.get(normalizeStockKey(item.stock));
      if (!now) return `${item.stock} 未进入当前候选表，说明当前时点没有继续满足候选输出条件`;
      if (now.riskLevel === "high") return `${item.stock} 风险升高，转为不追高/只观察`;
      if (now.vwap && now.vwap !== "上") return `${item.stock} 未站稳 VWAP，不能继续当重点`;
      return `${item.stock} 仍在池内但不再是前三重点，优先级下降`;
    });
  return changed.length ? `较上一时间点：${changed.join("；")}。` : "";
}

function turnoverCandidateSummaryText(items) {
  const key = items.filter((item) => /中际旭创|新易盛|罗博特科|天孚通信|亨通光电/.test(item.stock)).slice(0, 3);
  const list = key.length ? key : candidateGroups(items).research.slice(0, 3);
  if (!list.length) return `当前候选 ${items.length} 条，只作为观察池；10:30 先看 VWAP 承接，不把候选当买入清单。`;
  return `${list.map((item) => `${item.stock}｜${candidateRole(item)}`).join("；")}。11:20 看是否站稳 VWAP、强于板块；不满足就只算冲高观察。`;
}

function renderDecisionLists(decision) {
  return `
    <div class="decision-grid">
      ${renderItemList("市场情绪", buildMarketEmotionItems(decision), renderEmotionItem)}
      ${renderItemList("确认主线", decision.confirmed_mainlines, renderLineItem)}
      ${renderItemList("走弱方向", decision.weakening_mainlines, renderLineItem)}
      ${renderItemList("新改善方向", decision.new_improving_lines, renderLineItem)}
      ${renderItemList("持仓优先级", decision.portfolio_priority, renderPortfolioPriority)}
      ${renderItemList("下一 checkpoint 看什么", decision.next_checkpoint_watch, renderWatchItem)}
    </div>
  `;
}

function conclusionTitle(decision) {
  return `当前盘面：${value(decision.market_state, "暂无清晰主线")}`;
}

function conclusionText(decision) {
  const focus = (decision.confirmed_mainlines || []).slice(0, 3).map((item) => item.name);
  const weak = (decision.weakening_mainlines || []).slice(0, 3).map((item) => item.name);
  const parts = [];
  if (focus.length) parts.push(`${focus.join("、")}仍然较强，但需要看结构和中军承接。`);
  if (weak.length) parts.push(`${weak.join("、")}走弱或反抽失败，暂时不要当主攻。`);
  if (!parts.length) parts.push("当前没有足够明确的主线，先等下一 checkpoint 的板块成交、VWAP 和持仓风险信号。");
  parts.push(actionBias(decision) === "等确认" ? "当前适合观察承接，不适合盲目追涨。" : "当前可以继续跟踪强线，但仍以证伪条件为准。");
  return parts.join("");
}

function mainlineState(decision) {
  if ((decision.confirmed_mainlines || []).length && (decision.weakening_mainlines || []).length) return "分化";
  if ((decision.confirmed_mainlines || []).length) return "延续";
  if ((decision.new_improving_lines || []).length) return "切换观察";
  if ((decision.weakening_mainlines || []).length) return "走弱";
  return "不明朗";
}

function actionBias(decision) {
  if (decision.risk_preference === "低") return "等确认";
  if ((decision.do_not_chase || []).length >= 3) return "不追高";
  if ((decision.confirmed_mainlines || []).length) return "看承接";
  return "等待";
}

function renderFocusList(decision) {
  const items = (decision.confirmed_mainlines || []).slice(0, 5);
  if (!items.length) return '<p class="muted">暂无优先方向。</p>';
  return `<ol class="brief-list">${items.map((item) => `<li>${renderHumanLine(item, "focus")}</li>`).join("")}</ol>`;
}

function renderHumanLine(item, mode) {
  const label = humanStage(item);
  const explanation = lineExplanation(item, mode);
  const watch = lineWatch(item);
  const lesson = beginnerLesson(item, mode);
  return `
    <strong>${escapeHtml(item.name)}</strong>
    <span>${escapeHtml(label)}</span>
    <p>${escapeHtml(explanation)}</p>
    <em>看什么：${escapeHtml(watch)}</em>
    <small>小白解释：${escapeHtml(lesson)}</small>
  `;
}

function humanStage(item) {
  const map = {
    mainline_candidate: "主线候选",
    confirming: "确认中",
    high_crowding: "拥挤偏高",
    two_day_acceleration: "连续加速",
    rebound_only: "仅反抽",
    late_diffusion: "末端扩散",
    temperature_indicator: "温度计",
    defense_failed: "防守失效",
    downgraded: "已降级",
    watch: "观察",
  };
  const stage = map[item.stage] || item.stage || "观察";
  const structure = item.structure_state ? ` / ${item.structure_state}` : "";
  return `${stage}${structure}`;
}

function lineExplanation(item, mode) {
  if (mode === "weak") {
    if (item.rebound_type === "failed_rebound") return "旧方向反抽失败，今天不要再当主攻。";
    return "方向转弱或强度回落，先作为风险/温度计观察。";
  }
  if (item.crowding_signal === "high_crowding") return "涨幅或热度偏高，不能只看涨幅追。";
  if (item.structure_state === "结构待验证") return "强度靠前，但中军、领涨股、补涨结构还没完全确认。";
  if (item.structure_state === "结构健康") return "中军、领涨股和板块宽度较同步，值得继续观察承接。";
  return "仍然较强，下一步重点看是否能维持成交和 VWAP 承接。";
}

function lineWatch(item) {
  if (item.crowding_signal === "high_crowding") return "领涨股是否冲高回落，中军是否继续站稳 VWAP。";
  if (item.structure_state === "结构待验证") return "下一 checkpoint 是否仍在前 5/前 10，核心股是否站稳 VWAP。";
  return "板块成交不明显掉队，核心股不跌破 VWAP 或上午低点。";
}

function beginnerLesson(item, mode) {
  if (mode === "weak") {
    if (item.rebound_type === "failed_rebound") return "反抽失败的意思是资金试过修复但没有成功，不要因为它以前强就幻想马上回来。";
    return "走弱方向只适合当风险温度计，不适合作为今天主攻。先看它能否重新放量修复。";
  }
  if (item.crowding_signal === "high_crowding") return "涨得多不等于可以买。越靠近高位，越需要看有没有人愿意在回落时承接。";
  if (item.structure_state === "结构待验证") return "涨幅靠前只说明资金正在看它；中军稳、领涨股不炸、补涨跟上，才更像主线。";
  if (item.structure_state === "结构健康") return "中军和领涨股一起强，说明不是少数小票乱冲，信号质量更高。";
  return "VWAP 可以理解成当天资金平均成本，站在上方说明承接还可以，跌破则说明追涨资金容易被套。";
}

function renderPortfolioBrief(decision) {
  const items = (decision.portfolio_priority || []).slice(0, 6);
  if (!items.length) return '<p class="muted">暂无持仓风险优先级。</p>';
  return `<div class="priority-list">${items.map(renderPriorityCard).join("")}</div>`;
}

function renderPriorityCard(item) {
  const detail = buildPortfolioInsight(item);
  const isP0 = detail.priority === "P0";
  return `
    <article class="priority-card ${isP0 ? "p0" : ""}">
      <div class="priority-topline">
        <strong>${escapeHtml(detail.label)}｜${escapeHtml(detail.stock)}</strong>
        <span>${escapeHtml(detail.type)}</span>
      </div>
      <p>为什么是 ${escapeHtml(detail.priority)}：${escapeHtml(detail.why)}</p>
      <p>成本 / 当前 / 盈亏：${escapeHtml(detail.position)}</p>
      <p>状态：${escapeHtml(detail.status)}</p>
      <p>关键线：${escapeHtml(detail.lines)}</p>
      <p>动作：${escapeHtml(detail.action)}</p>
    </article>
  `;
}

function buildPortfolioInsight(item) {
  const row = findStockContextRow(item.stock);
  const holding = findHoldingForStock(item.stock);
  const stock = item.stock || row["股票"] || row.name || "-";
  const priority = item.priority || "P3";
  const current = row["当前价"] || row.current_price || "";
  const pct = row["当前涨幅"] || row.pct || row["收盘涨幅"] || "";
  const vwap = row["VWAP上/下"] || row["VWAP状态"] || (row.is_above_vwap === "True" ? "上" : row.is_above_vwap === "False" ? "下" : "");
  const drawdown = row["高点回撤%"] || row["今日高点回撤%"] || "";
  const relative = row.relative_strength_vs_sector || row["是否强于板块"] || "";
  const reason = item.reason && !String(item.reason).includes("按风险条件") ? item.reason : portfolioReasonFromRow(row, item);
  const label = priorityLabel(priority);
  const type = holdingTypeFromRow(row, item);
  const statusParts = [];
  if (reason) statusParts.push(reason);
  if (current) statusParts.push(`当前 ${current}`);
  if (pct) statusParts.push(`涨幅 ${pct}%`);
  if (vwap) statusParts.push(`VWAP ${vwap}`);
  if (drawdown) statusParts.push(`高点回撤 ${drawdown}%`);
  if (relative) statusParts.push(`相对板块 ${relative}`);
  return {
    stock,
    priority,
    label,
    type,
    why: portfolioWhy(priority, row, item),
    position: portfolioPositionText(holding, current),
    status: statusParts.join("；") || "暂无明确触发条件，按下一 checkpoint 继续观察。",
    lines: portfolioLines(row, item),
    action: portfolioAction(row, item),
  };
}

function priorityLabel(priority) {
  const map = {
    P0: "P0｜必须处理",
    P1: "P1｜重点观察",
    P2: "P2｜正常持有",
    P3: "P3｜暂不关注",
  };
  return map[priority] || `${priority || "P3"}｜待确认`;
}

function holdingTypeFromRow(row, item) {
  const pct = num(row["当前涨幅"] || row.pct || row["收盘涨幅"]);
  const reason = `${item.reason || ""} ${row["日K形态"] || ""} ${row["走势自然语言"] || ""}`;
  if ((item.priority || "") === "P0" || pct < -3) return "亏损风险仓";
  if (pct >= 6 || reason.includes("强阳") || reason.includes("长上影")) return "高位利润仓";
  if (reason.includes("中线") || reason.includes("thesis")) return "中线观察仓";
  return "短线题材仓";
}

function portfolioReasonFromRow(row, item) {
  if (item.invalid_condition === "是") return "风险条件已触发或接近触发";
  if (row["VWAP上/下"] === "下" || row["VWAP状态"] === "下") return "跌到 VWAP 下方，需要确认是否修复";
  if (num(row["高点回撤%"] || row["今日高点回撤%"]) <= -4) return "冲高回落较明显，需要保护利润或降风险";
  if (row.relative_strength_vs_sector === "False" || row["是否强于板块"] === "否") return "弱于所属板块，逻辑线需要复核";
  return item.reason || "暂无明确触发条件";
}

function portfolioLines(row, item) {
  const trigger = item.trigger_price && !String(item.trigger_price).includes("按风险") ? item.trigger_price : "";
  const current = num(row["当前价"] || row.current_price || "");
  if (trigger) return `修复 VWAP｜风险 ${trigger}｜止损 计划失效线`;
  if (current) {
    const repair = (current * 1.015).toFixed(2);
    const risk = (current * 0.985).toFixed(2);
    const stop = (current * 0.965).toFixed(2);
    if ((item.priority || "") === "P0") return `修复 ${repair}：站回才说明风险缓和｜风险 ${risk}：跌破说明继续走弱｜止损 ${stop}：跌破不再等待`;
    if ((item.priority || "") === "P1") return `强势 ${repair}：站上继续持有｜保护 ${risk}：跌破先降风险｜趋势 ${stop}：跌破降为观察仓`;
    return `观察 VWAP：确认承接｜风险 ${risk}：跌破要复核｜失效 ${stop}：跌破说明短线逻辑坏了`;
  }
  return "修复 VWAP｜风险 上午低点｜止损 昨日低点 / 计划失效线";
}

function portfolioAction(row, item) {
  if (item.priority === "P0") return "下一 checkpoint 仍未修复就减仓；跌破止损线不再等待。";
  if (item.priority === "P1") return "重点观察修复线，站回继续看，跌破保护线先降风险。";
  if (item.priority === "P2") return "正常持有观察，尾盘复核 VWAP、板块强弱和逻辑线。";
  return "低优先级，暂不处理，只在尾盘或下个 checkpoint 复核。";
}

function portfolioWhy(priority, row, item) {
  if (priority === "P0") return portfolioReasonFromRow(row, item) || "已经触发或接近触发风险条件，必须确认。";
  if (priority === "P1") return "还没完全触发风险，但接近关键位置，需要重点观察。";
  if (priority === "P2") return "暂时没有明显失效，按计划持有并等待下一次确认。";
  return "当前没有明确触发条件，优先级低。";
}

function portfolioPositionText(holding, current) {
  const cost = num(holding.avg_cost || holding.cost || "");
  const price = num(current || holding.current_snapshot || "");
  const parts = [];
  parts.push(cost ? `成本 ${cost}` : "成本 -");
  parts.push(price ? `当前 ${price}` : "当前 -");
  if (cost && price) parts.push(`盈亏 ${(((price - cost) / cost) * 100).toFixed(1)}%`);
  else parts.push("盈亏 -");
  return parts.join("｜");
}

function findHoldingForStock(stock) {
  const rows = mergedHoldings();
  const needle = normalizeStockKey(stock);
  if (!needle) return {};
  return rows.find((row) => {
    const key = normalizeStockKey(`${row.name || ""} ${row.code || ""}`);
    return key && (key.includes(needle) || needle.includes(key));
  }) || {};
}

function findStockContextRow(stock) {
  const checkpoint = currentCheckpoint();
  const rows = (checkpoint?.tables || []).flatMap((table) => table.rows || []);
  const needle = normalizeStockKey(stock);
  if (!needle) return {};
  return rows.find((row) => {
    const key = normalizeStockKey(row["股票"] || `${row.name || ""} ${row.code || ""}`);
    return key && (key.includes(needle) || needle.includes(key));
  }) || {};
}

function normalizeStockKey(input) {
  return String(input || "").replace(/\s+/g, "").replace(/[^\u4e00-\u9fa5A-Za-z0-9*]/g, "");
}

function actionFromPriority(item) {
  if (item.priority === "P0") return "不补仓，若下一 checkpoint 仍未修复则降风险。";
  if (item.priority === "P1") return "高优先观察，等关键位或 VWAP 结果。";
  if (item.priority === "P2") return "正常持有观察，不因单点波动处理。";
  return "低优先级，暂不处理。";
}

function renderMainlineGroups(decision) {
  const strong = (decision.confirmed_mainlines || []).slice(0, 5);
  const weak = (decision.weakening_mainlines || []).slice(0, 5);
  const improving = (decision.new_improving_lines || []).slice(0, 5);
  return `
    <div class="mainline-groups">
      ${renderMainlineGroup("仍在走强", strong, "strong")}
      ${renderMainlineGroup("走弱 / 不再主攻", weak, "weak")}
      ${renderMainlineGroup("新改善方向", improving, "improving")}
    </div>
  `;
}

function renderMainlineGroup(title, items, mode) {
  if (!items.length) return `<div class="mainline-group"><h4>${escapeHtml(title)}</h4><p class="muted">暂无。</p></div>`;
  return `
    <div class="mainline-group">
      <h4>${escapeHtml(title)}</h4>
      <ul>${items.map((item) => `<li>${renderHumanLine(item, mode)}</li>`).join("")}</ul>
    </div>
  `;
}

function renderNextWatch(decision) {
  const watches = decision.next_checkpoint_watch || [];
  if (!watches.length) return '<p class="muted">暂无下一步观察。</p>';
  return `<ol class="next-watch">${watches.slice(0, 6).map((item) => `<li><strong>${escapeHtml(item)}</strong><p>确认：成交和涨家率维持、核心股站稳 VWAP。证伪：强度掉队、领涨股冲高回落或持仓风险继续触发。</p></li>`).join("")}</ol>`;
}

function renderTurnoverWatch(checkpoint) {
  const sectors = tableRows(checkpoint, "market_sector_scan.csv");
  const top = sectors.slice(0, 3).map((row) => row["板块"]).filter(Boolean).join(" / ") || "早盘强线";
  const p0 = (checkpoint.decision?.portfolio_priority || []).filter((item) => item.priority === "P0").slice(0, 2);
  const p0Text = p0.length ? `${p0.map((item) => item.stock).join("、")} 是否修复` : "弱持仓是否强于所属板块";
  const items = [
    `${top} 是否 11:20 仍在前 5 / 前 10。`,
    "中际旭创 / 新易盛等核心股是否站稳 VWAP。",
    p0Text,
    "如果候选仍普遍低于 VWAP，科技回流降级为冲高反抽。",
  ];
  return `<ol class="next-watch">${items.map((item) => `<li><strong>${escapeHtml(item)}</strong><p>确认：板块成交和涨家率维持、核心股站稳 VWAP、候选不再只是冲高。证伪：核心股跌回 VWAP 下方或领涨股冲高回落。</p></li>`).join("")}</ol>`;
}

function renderTomorrowWatch(checkpoint) {
  const sectors = tableRows(checkpoint, "final_sectors.csv").length ? tableRows(checkpoint, "final_sectors.csv") : tableRows(checkpoint, "market_sector_scan.csv");
  const names = sectors.slice(0, 3).map((row) => row["板块"] || row["name"]).filter(Boolean);
  const items = [
    `${names[0] || "强势方向"} 是否延续，而不是一日情绪。`,
    `${names.filter((name) => /石油|煤炭|电力/.test(name)).join(" / ") || "资源/防守线"} 是否能在科技分歧时逆势。`,
    "科创/创业强势是否扩散到个股，而不是只有指数强。",
  ];
  return `<ol class="next-watch">${items.map((item) => `<li><strong>${escapeHtml(item)}</strong><p>确认：竞价不过热，09:45 仍有成交和涨家率支撑，中军不跌破 VWAP。证伪：高开低走、只有小票脉冲、涨跌家数继续恶化。</p></li>`).join("")}</ol>`;
}

function renderAvoidList(checkpoint) {
  if (isAfterCloseCheckpoint(checkpoint)) return renderAfterCloseAvoidList(checkpoint);
  if (isTurnoverCheckpoint(checkpoint)) return renderTurnoverAvoidList(checkpoint);
  const decision = checkpoint?.decision || {};
  const { rows } = candidateRowsForCheckpoint(checkpoint);
  const riskyCandidates = rows.map(candidateInsight).filter((item) => item.riskLevel === "high").slice(0, 3);
  const p0 = (decision.portfolio_priority || []).filter((item) => item.priority === "P0").slice(0, 3);
  const items = [];
  if ((decision.confirmed_mainlines || []).some((item) => item.structure_state === "结构待验证")) {
    items.push("不要因为板块涨幅靠前就直接追。结构待验证时，要先看中军、领涨股和 VWAP。");
  }
  if (p0.length) {
    items.push(`不要补弱势持仓。${p0.map((item) => item.stock).join("、")} 是优先处理对象，先看修复线。`);
  }
  if ((decision.weakening_mainlines || []).length) {
    items.push(`不要把走弱方向当主攻。${decision.weakening_mainlines.slice(0, 3).map((item) => item.name).join("、")} 先按退潮/温度计处理。`);
  }
  if (decision.data_quality?.fallback_used || checkpoint?.summary?.fallback_used) {
    items.push("不要在数据 fallback 较多时放大仓位。板块粒度变粗时，要用个股承接交叉验证。");
  }
  if (riskyCandidates.length) {
    items.push(`不要把候选池当买入清单。${riskyCandidates.map((item) => item.stock).join("、")} 已有追高或承接风险。`);
  }
  if (!items.length) items.push("不要临盘改计划。没有清晰确认前，只做观察和记录。");
  return `<ol class="avoid-list">${items.slice(0, 5).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ol>`;
}

function renderTurnoverAvoidList(checkpoint) {
  const candidates = candidateRowsForCheckpoint(checkpoint).rows;
  const vwapUp = candidates.filter((row) => candidateVwapState(row) === "上").length;
  const items = [
    "不要把科技指数大涨等同于个股可买，涨跌家数弱时先看承接。",
    "不要因为 CPO / 光通信涨幅靠前就追高，10:30 的任务是确认换手，不是追第一波。",
    "不要补 P0 弱持仓。指数强而个股不修复，问题更可能在个股承接。",
    "不要把候选池当买入清单，核心股没有站稳 VWAP 前只观察。",
  ];
  if (vwapUp === 0) items.unshift("候选 0 条站上 VWAP 时，当前没有形成可执行买点。");
  return `<ol class="avoid-list">${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ol>`;
}

function renderAfterCloseAvoidList(checkpoint) {
  const sectors = tableRows(checkpoint, "final_sectors.csv").length ? tableRows(checkpoint, "final_sectors.csv") : tableRows(checkpoint, "market_sector_scan.csv");
  const top = sectors.slice(0, 3).map((row) => row["板块"] || row["name"]).filter(Boolean).join("、");
  const items = [
    "不要把指数上涨理解成普涨。涨跌家数弱时，低位随便扩散买容易踩弱票。",
    `不要因为 ${top || "强势板块"} 涨幅靠前就追。盘后只做明日验证计划。`,
    "不要把暂无 P0 理解成持仓全部安全，它只代表没有触发最紧急风控。",
    "不要把候选池当买入清单，明天先看竞价、09:45 承接和 VWAP。",
    "不要把短线题材仓在盘后复盘里改口成中线仓。",
  ];
  return `<ol class="avoid-list">${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ol>`;
}

function renderPreopen(day) {
  const target = byId("preopen-content");
  if (!target) return;
  target.innerHTML = renderPreopenContent(day);
}

function renderPreopenContent(day) {
  if (!day) {
    return '<p class="empty">暂无盘前预案。</p>';
  }
  const plan = preopenPlanForDay(day);
  const checkpoints = day.checkpoints || [];
  const first = checkpoints.find((item) => !isStrategyCheckpoint(item)) || checkpoints[0];
  const latest = [...checkpoints].reverse().find((item) => !isStrategyCheckpoint(item)) || checkpoints[checkpoints.length - 1];
  const strategy = checkpoints.find(isStrategyCheckpoint);
  const sectors = tableRows(first, "market_sector_scan.csv").slice(0, 8);
  const latestSectors = tableRows(latest, "market_sector_scan.csv").slice(0, 8);
  const strongLines = sectors.slice(0, 4);
  const weakLines = (latest?.decision?.weakening_mainlines || []).slice(0, 4);
  const tempLines = preopenTemperatureLines(sectors, latestSectors);
  const focusSectors = preopenFocusSectors(strongLines, latestSectors);
  const candidateItems = candidateRowsForCheckpoint(strategy || first).rows.map(candidateInsight);
  const candidatePlan = candidateGroups(candidateItems);
  const portfolioItems = preopenPortfolioPlan(latest, plan);
  const fallbackUsed = Boolean(first?.summary?.fallback_used || latest?.summary?.fallback_used);
  const errorCount = Number(first?.summary?.error_count || 0) + Number(latest?.summary?.error_count || 0);
  const headline = plan?.headline || (fallbackUsed
    ? "数据有 fallback，今天只做验证，不放大仓位。"
    : "高位分化后的验证日，不追高，等 09:45 / 10:30 确认。");
  const keyPoints = plan?.key_points?.length
    ? plan.key_points
    : [
        `${focusSectors[0]?.name || "昨日强线"} 是否能在 09:45 继续有成交和涨家率支撑。`,
        "旧主线温度计是否拖累科技风险偏好。",
        "持仓里 P0 / P1 是否开盘修复，不能把弱票中线化。",
      ];
  const planBranches = plan?.observation_focus?.branches || [];
  const planHoldings = plan?.observation_focus?.holdings || [];

  return `
    <section class="preopen-hero">
      <span class="brief-kicker">${escapeHtml(plan?.date || day.date)} · 盘前预案</span>
      <h2>${escapeHtml(headline)}</h2>
      <p>盘前信息的目标不是收集新闻，而是在开盘前 5 分钟回答：今天验证什么，什么情况下不该动手。</p>
      <div class="pill-row">
        <span class="pill">风险偏好：${escapeHtml(plan?.risk_preference || (fallbackUsed ? "中等偏低" : "中等"))}</span>
        <span class="pill">主线状态：${escapeHtml(plan?.mainline_state || "分化验证")}</span>
        <span class="pill">操作倾向：${escapeHtml(plan?.action_bias || "不追高，等确认")}</span>
      </div>
    </section>

    <section class="preopen-card">
      <h3>今日最重要的 3 件事</h3>
      <ol class="preopen-list">
        ${keyPoints.slice(0, 3).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
      </ol>
    </section>

    <div class="preopen-grid two">
      <section class="preopen-card">
        <h3>昨日强弱线验证</h3>
        ${renderPreopenLineGroup("昨日强线", strongLines.map((row) => ({
          name: row["板块"] || "-",
          status: "昨日/早盘强分支",
          confirm: "09:45 仍在前 10，10:30 中军站稳 VWAP",
          invalid: "高开低走，领涨股冲高回落，中军跌破 VWAP",
        })))}
        ${renderPreopenLineGroup("昨日分歧线", weakLines.map((item) => ({
          name: item.name,
          status: humanStage(item),
          confirm: "中军止跌并收回 VWAP",
          invalid: "低开低走，只有小票脉冲",
        })))}
        ${renderPreopenLineGroup("旧主线温度计", tempLines.map((name) => ({
          name,
          status: "科技情绪温度计",
          confirm: "稳住则科技修复可信度上升",
          invalid: "继续弱则降低科技风险偏好",
        })))}
      </section>

      <section class="preopen-card">
        <h3>周末新闻 / 外围线索</h3>
        ${renderPreopenWeekendNews(plan)}
      </section>
    </div>

    <section class="preopen-card">
      <h3>今日重点观察板块</h3>
      ${planBranches.length ? renderPreopenPlanBranches(planBranches) : `<div class="preopen-sector-grid">${focusSectors.map(renderPreopenSectorCard).join("") || '<p class="empty">暂无重点观察板块。</p>'}</div>`}
    </section>

    <section class="preopen-card">
      <h3>今日持仓预案</h3>
      ${
        planHoldings.length
          ? renderPreopenPlanHoldings(planHoldings)
          : portfolioItems.length
            ? `<div class="priority-list">${portfolioItems.map(renderPriorityCard).join("")}</div>`
            : '<p class="empty">暂无持仓预案。请先在持仓管理里补充持仓。</p>'
      }
    </section>

    <section class="preopen-card">
      <h3>今日候选池预案</h3>
      <div class="candidate-layers">
        ${renderCandidateLayer("A. 可重点研究", "最多 3 个，开盘后仍需确认，不是买入清单。", candidatePlan.research)}
        ${renderCandidateLayer("B. 只观察不追", "最多 5 个，有异动但还未证明。", candidatePlan.observe)}
        ${renderCandidateLayer("C. 暂不看 / 不追高", "高拥挤、反抽失败、数据不可信或信息优先级低。", candidatePlan.avoid)}
      </div>
    </section>

    <div class="preopen-grid two">
      <section class="preopen-card avoid-box">
        <h3>今日不要做什么</h3>
        ${renderPreopenDoNotDo(fallbackUsed, plan)}
      </section>
      <section class="preopen-card">
        <h3>数据可信度</h3>
        ${renderSignalRows([
          ["盘前计划日期", plan?.date || day.date, plan?.source?.primary || "来自本地静态数据"],
          ["盘前新闻", plan?.source?.external_news_status ? "待核验" : "未接入", plan?.source?.external_news_status || "不要把新闻框架当实时新闻"],
          ["外围数据", "未接入", "需要后续接入数据源"],
          ["持仓成本", siteData.portfolio?.modified ? "已读取" : "未读取", siteData.portfolio?.source || "portfolio.md"],
          ["fallback", fallbackUsed ? "是" : "否", fallbackUsed ? "今日信号权重降低，只观察不放大仓位" : "信号权重正常"],
          ["错误数", String(errorCount), "采集错误越多，越要降低行动强度"],
        ])}
      </section>
    </div>
  `;
}

function preopenPlanForDay(day) {
  const plan = siteData?.preopen_plan || {};
  if (!Object.keys(plan).length) return null;
  if (plan.date && day?.date && plan.date !== day.date) return null;
  return plan;
}

function renderPreopenWeekendNews(plan) {
  const items = plan?.weekend_news || [];
  if (!items.length) {
    return `
      <div class="preopen-note">
        <strong>当前状态</strong>
        <p>尚未接入实时新闻、外围指数、汇率和商品数据。盘前只预留判断框架，避免把旧数据当实时信号。</p>
      </div>
      ${renderSignalRows([
        ["政策 / 产业新闻", "待更新", "只记录会改变预案的催化，不做新闻堆叠"],
        ["海外映射", "待更新", "重点看纳指、费半、英伟达/台积电 ADR 对科技情绪的影响"],
        ["大宗商品", "待更新", "重点看铜、煤、油、黄金是否改变资源/防守线预案"],
        ["汇率 / 港股科技", "待更新", "只判断是否扰动 A 股风险偏好"],
      ])}
    `;
  }
  return `
    <div class="signal-list">
      ${items.map((item) => `
        <div class="preopen-note">
          <strong>${escapeHtml(item.title)}</strong>
          <p>${escapeHtml(item.impact)}</p>
          <p>${escapeHtml([item.status, item.source].filter(Boolean).join(" · "))}</p>
        </div>
      `).join("")}
    </div>
  `;
}

function renderPreopenPlanBranches(items) {
  return `
    <div class="preopen-sector-grid">
      ${items.map((item) => `
        <article class="preopen-sector-card">
          <strong>${escapeHtml(item.branch)}</strong>
          <span>${escapeHtml([item.tag, item.anchors].filter(Boolean).join(" · "))}</span>
          <p>观察条件：${escapeHtml(item.condition || "-")}</p>
          <p>降级条件：${escapeHtml(item.downgrade || "-")}</p>
        </article>
      `).join("")}
    </div>
  `;
}

function renderPreopenPlanHoldings(items) {
  return `
    <div class="preopen-line-group">
      ${items.map((item) => `
        <article class="preopen-line">
          <strong>${escapeHtml(item.stock)}</strong>
          <p>今日第一身份：${escapeHtml(item.identity || "-")}</p>
          <p>买入观察条件：${escapeHtml(item.condition || "-")}</p>
          <p>卖出 / 降级观察条件：${escapeHtml(item.downgrade || "-")}</p>
          <p>动作语言：${escapeHtml(item.action || "-")}</p>
        </article>
      `).join("")}
    </div>
  `;
}

function preopenTemperatureLines(...sectorGroups) {
  const names = sectorGroups.flat().map((row) => row["板块"] || "").filter(Boolean);
  const matched = names.filter((name) => /CPO|光通信|光纤|PCB|存储|算力|AI/.test(name));
  return [...new Set(matched)].slice(0, 4).concat(["CPO / 光通信"].filter((name) => !matched.length)).slice(0, 4);
}

function preopenFocusSectors(strongRows, latestRows) {
  const rows = [...strongRows, ...latestRows];
  const seen = new Set();
  return rows
    .map((row) => ({
      name: row["板块"] || "-",
      role: "今日验证方向",
      pct: row["涨幅"] || row["板块涨幅"] || "",
    }))
    .filter((item) => {
      if (seen.has(item.name)) return false;
      seen.add(item.name);
      return item.name && item.name !== "-";
    })
    .slice(0, 5);
}

function renderPreopenLineGroup(title, items) {
  return `
    <div class="preopen-line-group">
      <h4>${escapeHtml(title)}</h4>
      ${
        items.length
          ? items.slice(0, 4).map((item) => `
            <article class="preopen-line">
              <strong>${escapeHtml(item.name)}</strong>
              <p>状态：${escapeHtml(item.status)}</p>
              <p>今日验证：${escapeHtml(item.confirm)}</p>
              <p>失效：${escapeHtml(item.invalid)}</p>
            </article>
          `).join("")
          : '<p class="empty">暂无。</p>'
      }
    </div>
  `;
}

function renderSignalRows(rows) {
  return `<div class="signal-list">${rows.map(([label, valueText, note]) => `
    <div class="signal-row">
      <strong>${escapeHtml(label)}</strong>
      <span>${escapeHtml(valueText)}</span>
      <em>${escapeHtml(note)}</em>
    </div>
  `).join("")}</div>`;
}

function renderPreopenSectorCard(item) {
  return `
    <article class="preopen-sector-card">
      <strong>${escapeHtml(item.name)}</strong>
      <span>${escapeHtml([item.role, item.pct ? `${item.pct}%` : ""].filter(Boolean).join(" · "))}</span>
      <p>盘前条件：竞价不宜高开过多，只看确认。</p>
      <p>09:45 确认：板块仍在前 10，中军不杀。</p>
      <p>10:30 确认：换手后仍站 VWAP。</p>
      <p>风险：若只有小票冲，视为补涨末端。</p>
    </article>
  `;
}

function preopenPortfolioPlan(latest, plan = null) {
  const planRows = plan?.observation_focus?.holdings || [];
  if (planRows.length) {
    return planRows.map((row) => ({
      stock: row.stock,
      priority: row.identity?.includes("风险") ? "P0" : row.identity?.includes("温度计") ? "P1" : "P2",
      reason: row.action || row.identity || "盘前持仓观察",
      trigger_price: "",
      invalid_condition: row.downgrade || "",
    }));
  }
  const priority = (latest?.decision?.portfolio_priority || []).slice(0, 6);
  if (priority.length) return priority;
  return mergedHoldings().slice(0, 6).map((row) => ({
    stock: [row.name, row.code].filter(Boolean).join(" ") || row.code || row.name,
    priority: "P2",
    reason: row.note || "盘前持仓观察",
    trigger_price: "",
    invalid_condition: "",
  }));
}

function renderPreopenDoNotDo(fallbackUsed, plan = null) {
  const items = plan?.do_not_do?.length ? [...plan.do_not_do] : [
    "不要因为竞价涨幅靠前就追高。",
    "不要补弱于板块的亏损仓。",
    "不要把反抽失败当成新主线。",
    "不要因为昨天卖飞，就在今天开盘情绪化追回。",
    "不要把短线题材仓改口成中线仓。",
  ];
  if (fallbackUsed) items.push("不要在数据 fallback 较多时放大仓位。");
  return `<ol class="avoid-list">${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ol>`;
}

function currentCheckpoint() {
  const checkpoints = activeDay?.checkpoints || [];
  return checkpoints.find((item) => item.id === activeCheckpointId) || checkpoints[0];
}

function renderCheckpointTables(checkpoint) {
  const target = byId("checkpoint-tables");
  if (!target) return;
  const subtitle = byId("tables-subtitle");
  if (isPreopenCheckpoint(checkpoint)) {
    if (subtitle) subtitle.textContent = "09:10 盘前预案 · 使用上一交易日数据、watchlist 和 portfolio 缓存生成。";
    target.innerHTML = '<p class="empty">盘前预案没有单独扫描表；请查看时间轴中的预案内容。</p>';
    return;
  }
  if (subtitle) {
    subtitle.textContent = checkpoint
      ? `${checkpoint.label} · ${checkpoint.directory}`
      : "当前 checkpoint 的原始输出表。";
  }
  target.innerHTML = checkpoint ? (checkpoint.tables || []).map(renderTable).join("") : '<p class="empty">暂无数据表。</p>';
}

function buildMarketEmotionItems(decision) {
  const checkpoint = currentCheckpoint();
  const market = firstTableRow(checkpoint, "market_overview.csv");
  const sectors = tableRows(checkpoint, "market_sector_scan.csv");
  const amount = market["成交额预估"] || market["成交额"] || market["market_amount"] || "";
  const upDown = market["涨跌家数"] || market["up_down_count"] || "";
  const limit = market["涨停/跌停"] || market["limit_up_down_count"] || "";
  const pctParts = market["指数涨幅"] ? [`指数 ${market["指数涨幅"]}%`] : indexPartsFromMarket(market);
  const sectorDistribution = summarizeSectorDistribution(sectors);
  const score = marketEmotionScore({ pctParts, amount, upDown, limit, sectors, decision });
  const quality = decision.data_quality || {};
  return [
    { label: "市场状态", value: value(decision.market_state, "暂无") },
    { label: "市场涨幅", value: pctParts.join(" / ") || "-" },
    { label: "成交量", value: amount ? `${formatAmount(amount)} · ${amountPulse(amount)}` : "-" },
    { label: "涨跌数量", value: upDown || "-" },
    { label: "涨停 / 跌停", value: limit || "-" },
    { label: "市场情绪评分", value: score },
    { label: "市场板块分布", value: sectorDistribution },
    { label: "风险偏好", value: value(decision.risk_preference, "暂无") },
    { label: "数据质量", value: quality.fallback_used ? "部分 fallback" : "正常" },
  ];
}

function firstTableRow(checkpoint, tableName) {
  return tableRows(checkpoint, tableName)[0] || {};
}

function tableRows(checkpoint, tableName) {
  const table = (checkpoint?.tables || []).find((item) => item.name === tableName);
  return table?.rows || [];
}

function summarizeSectorDistribution(rows) {
  if (!rows.length) return "-";
  const top = rows.slice(0, 5).map((row) => {
    const name = row["板块"] || row["sector"] || "-";
    const pct = row["涨幅"] || row["板块涨幅"] || "";
    return pct === "" ? name : `${name} ${pct}%`;
  });
  return top.join(" / ");
}

function marketEmotionScore({ upDown, limit, sectors, decision }) {
  let score = 50;
  const [up, down] = parsePair(upDown);
  const [limitUp, limitDown] = parsePair(limit);
  if (up + down > 0) score += ((up - down) / (up + down)) * 25;
  score += Math.min(limitUp, 80) * 0.25;
  score -= Math.min(limitDown, 80) * 0.35;
  const strongSectors = sectors.filter((row) => num(row["涨幅"]) > 1).length;
  score += Math.min(strongSectors, 10);
  if (decision.data_quality?.fallback_used) score -= 5;
  return `${Math.max(0, Math.min(100, Math.round(score)))} / 100`;
}

function parsePair(value) {
  const matches = String(value || "").match(/-?\d+(\.\d+)?/g) || [];
  return [Number(matches[0] || 0), Number(matches[1] || 0)];
}

function num(value) {
  const parsed = Number(String(value || "").replace(/,/g, ""));
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatAmount(value) {
  const amount = num(value);
  if (!amount) return value;
  if (amount >= 1000000000000) return `${(amount / 1000000000000).toFixed(2)} 万亿`;
  if (amount >= 100000000) return `${(amount / 100000000).toFixed(0)} 亿`;
  return String(value);
}

function amountPulse(value) {
  const amount = num(value);
  if (!amount) return "成交未知";
  if (amount >= 1000000000000) return "成交放大";
  if (amount >= 800000000000) return "成交正常";
  return "成交缩小";
}

function renderItemList(title, items, renderer) {
  const safeItems = Array.isArray(items) ? items : [];
  return `
    <div class="decision-box">
      <h3>${escapeHtml(title)}</h3>
      ${
        safeItems.length
          ? `<ul>${safeItems.slice(0, 8).map((item) => `<li>${renderer(item)}</li>`).join("")}</ul>`
          : '<p class="muted">暂无。</p>'
      }
    </div>
  `;
}

function renderLineItem(item) {
  const tags = [
    item.stage,
    item.rebound_type && item.rebound_type !== "none" ? item.rebound_type : "",
    item.crowding_signal && item.crowding_signal !== "normal" ? item.crowding_signal : "",
    item.two_day_acceleration ? "two_day_acceleration" : "",
  ].filter(Boolean);
  const structure = item.structure_state
    ? `结构：${item.structure_state}${item.structure_score !== undefined ? `(${item.structure_score})` : ""}`
    : "";
  return `
    <strong>${escapeHtml(item.name)}</strong>
    <span>${escapeHtml(tags.join(" · ") || item.theme_tier || item.intraday_state || "")}</span>
    ${structure ? `<b class="structure-note">${escapeHtml(structure)}</b>` : ""}
    <em>${escapeHtml(item.reason || "")}</em>
  `;
}

function renderEmotionItem(item) {
  return `<strong>${escapeHtml(item.label)}</strong><span>${escapeHtml(item.value)}</span>`;
}

function candidateRowsForCheckpoint(checkpoint = currentCheckpoint()) {
  const tables = checkpoint?.tables || [];
  const candidateNames = [
    "candidate_first_impact.csv",
    "candidate_scores.csv",
    "candidate_morning_check.csv",
    "candidate_afternoon_restart.csv",
    "candidate_close_confirm.csv",
    "final_stocks.csv",
    "strategy_candidates.csv",
  ];
  const table = candidateNames.map((name) => tables.find((item) => item.name === name)).find(Boolean);
  if (!table) return { rows: [], source: "" };
  return {
    source: tableLabels[table.name.replace(/\.csv$/i, "")] || table.name,
    rows: table.rows || [],
  };
}

function firstImpactCandidates() {
  const { rows } = candidateRowsForCheckpoint();
  return rows.map((row) => ({
    stock: row["股票"] || [row["name"], row["code"]].filter(Boolean).join(" ") || "-",
    sector: row["板块"] || row["匹配板块"] || row["sector"] || "",
    pct: row["当前涨幅"] || row["当前涨幅%"] || row["pct"] || "",
    reason: row["走势自然语言"] || row["命中原因"] || row["setup_pass_reasons"] || row["来源"] || "",
  }));
}

function renderStrategyCheckpoint(checkpoint) {
  const table = (checkpoint?.tables || []).find((item) => item.name === "strategy_candidates.csv");
  const rows = table?.rows || [];
  const groups = groupByStrategy(rows);
  return `
    <section class="strategy-only">
      <div class="strategy-header">
        <span class="brief-kicker">${escapeHtml(checkpoint.label)}</span>
        <h2>策略包候选</h2>
        <p>${escapeHtml(table ? `${rows.length}/${table.row_count} 条候选，按策略类型分类。` : "当前策略包没有候选表。")}</p>
      </div>
      ${
        groups.length
          ? groups.map(([strategy, items]) => renderStrategyGroup(strategy, items)).join("")
          : '<p class="empty">当前策略包没有候选。</p>'
      }
    </section>
  `;
}

function groupByStrategy(rows) {
  const groups = new Map();
  for (const row of rows) {
    const strategy = row["策略"] || "未标注策略";
    if (!groups.has(strategy)) groups.set(strategy, []);
    groups.get(strategy).push(row);
  }
  return [...groups.entries()].sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0], "zh-CN"));
}

function renderStrategyGroup(strategy, rows) {
  return `
    <section class="strategy-group">
      <div class="strategy-group-title">
        <h3>${escapeHtml(strategy)}</h3>
        <span>${escapeHtml(rows.length)} 条</span>
      </div>
      <div class="strategy-candidate-grid">
        ${rows.map(renderStrategyCandidateCard).join("")}
      </div>
    </section>
  `;
}

function renderStrategyCandidateCard(row) {
  const stock = row["股票"] || "-";
  const metrics = [
    row["当前价"] ? `现价 ${row["当前价"]}` : "",
    row["当前涨幅%"] ? `涨幅 ${row["当前涨幅%"]}%` : "",
    row["开盘涨幅%"] ? `开盘 ${row["开盘涨幅%"]}%` : "",
    row["高点回撤%"] ? `回撤 ${row["高点回撤%"]}%` : "",
  ].filter(Boolean);
  const board = [
    row["匹配板块"] || "",
    row["板块涨幅%"] ? `${row["板块涨幅%"]}%` : "",
  ].filter(Boolean);
  return `
    <article class="strategy-candidate-card">
      <strong>${escapeHtml(stock)}</strong>
      <span>${escapeHtml(metrics.join(" · ") || "-")}</span>
      <p>命中原因：${escapeHtml(row["命中原因"] || "-")}</p>
      <p>板块：${escapeHtml(board.join(" · ") || "未匹配")}</p>
      <p>过滤：${escapeHtml(row["过滤说明"] || row["流通股过滤"] || "-")}</p>
    </article>
  `;
}

function renderCandidateDashboard(checkpoint) {
  const { rows, source } = candidateRowsForCheckpoint(checkpoint);
  const items = rows.map(candidateInsight);
  const groups = candidateGroups(items);
  return `
    <section class="candidate-dashboard">
      <div class="candidate-header">
        <div>
          <h3>候选 Dashboard</h3>
          <p>${escapeHtml(source || "当前时段候选")} · ${items.length} 条，已按可决策程度分层</p>
        </div>
      </div>
      ${
        items.length
          ? `<div class="candidate-layers">
              ${renderCandidateLayer("A. 可重点研究", "板块强、个股强、承接相对清楚；仍然不是直接买入。", groups.research)}
              ${renderCandidateLayer("B. 继续观察", "有异动或在自选池，但还需要下一 checkpoint 证明。", groups.observe)}
              ${renderCandidateLayer("C. 不建议追高", "涨幅过高、VWAP 失守、长上影或承接未知。", groups.avoid)}
            </div>`
          : '<p class="empty">当前时段没有候选表。</p>'
      }
    </section>
  `;
}

function candidateGroups(items) {
  const pullbackWatch = [];
  const research = [];
  const observe = [];
  const avoid = [];
  const used = new Set();
  for (const item of items) {
    if (item.isPullback && /待确认|只观察/.test(item.category || "")) {
      pullbackWatch.push({ ...item, coach: "回踩观察只看承接确认，不提前当成买点。" });
      used.add(item.key);
    }
  }
  for (const item of items) {
    if (used.has(item.key)) continue;
    if (item.riskLevel === "high") {
      avoid.push({ ...item, coach: "先等回落承接或尾盘确认，不要把高风险候选当买点。" });
    } else if (research.length < 3 && item.riskLevel === "low" && candidateStrengthScore(item) >= 2) {
      research.push({ ...item, coach: "可以重点研究，但只在板块和 VWAP 继续确认后考虑。" });
    } else if (observe.length < 5) {
      observe.push({ ...item, coach: "放在观察池，等下一 checkpoint 证明它不是一波冲高。" });
    } else {
      avoid.push({ ...item, coach: "信息优先级靠后，不要因为候选数量多就分散注意力。" });
    }
  }
  return { pullbackWatch: pullbackWatch.slice(0, 8), research, observe, avoid, hidden: observe.concat(avoid) };
}

function candidateStrengthScore(item) {
  let score = 0;
  if (item.isPullback && item.category === "回踩确认") score += 2;
  if (item.source.includes("放量突破") || item.source.includes("策略")) score += 1;
  if (item.vwap === "上") score += 1;
  if (num(item.pct) > 0 && num(item.pct) < 9) score += 1;
  if (item.sector) score += 1;
  return score;
}

function renderCandidateLayer(title, description, items) {
  return `
    <div class="candidate-layer">
      <div class="candidate-layer-title">
        <h4>${escapeHtml(title)}</h4>
        <span>${escapeHtml(items.length)} 条</span>
      </div>
      <p>${escapeHtml(description)}</p>
      ${
        items.length
          ? `<div class="candidate-grid">${items.map(renderCandidateCard).join("")}</div>`
          : '<p class="empty">暂无。</p>'
      }
    </div>
  `;
}

function renderCandidateCard(item) {
  return `
    <article class="candidate-card risk-${escapeHtml(item.riskLevel)}">
      <div class="candidate-topline">
        <strong>${escapeHtml(item.stock)}</strong>
        <b>${escapeHtml(item.riskLabel)}</b>
      </div>
      <span>${escapeHtml([item.sector, item.pct ? `${item.pct}%` : "", item.vwap ? `VWAP ${item.vwap}` : ""].filter(Boolean).join(" · "))}</span>
      <p>候选原因：${escapeHtml(item.reason)}</p>
      <p>板块：${escapeHtml(item.sector || "未匹配")}</p>
      <p>风险评估：${escapeHtml(item.riskText)}</p>
      <p>为什么不是直接买：${escapeHtml(item.coach || candidateCoach(item))}</p>
      <em>${escapeHtml(item.source || "候选")}</em>
    </article>
  `;
}

function candidateInsight(row) {
  const stock = row["股票"] || [row["name"], row["code"]].filter(Boolean).join(" ") || "-";
  const sector = row["板块"] || row["匹配板块"] || row["sector"] || "";
  const pct = row["当前涨幅"] || row["当前涨幅%"] || row["收盘涨幅"] || row["pct"] || "";
  const vwap = candidateVwapState(row);
  const isPullback = Boolean(row["回踩类型"] || row["setup"]);
  const source = row["来源"] || row["来源(缩量回踩/放量突破/watchlist/portfolio)"] || row["策略"] || row["10:30来源"] || "";
  const reason = isPullback
    ? [row["回踩类型"], row["状态"], row["下一步"]].filter(Boolean).join("；")
    : row["走势自然语言"] || row["命中原因"] || row["setup_pass_reasons"] || source || "当前时段候选";
  const risk = candidateRisk(row);
  return {
    key: normalizeStockKey(stock),
    stock,
    sector,
    pct,
    vwap,
    source,
    reason,
    isPullback,
    category: row["分类"] || "",
    status: row["状态"] || "",
    riskLevel: risk.level,
    riskLabel: risk.label,
    riskText: risk.text,
  };
}

function candidateRisk(row) {
  const flags = [];
  const drawdown = num(row["高点回撤%"] || row["今日高点回撤%"]);
  const pct = num(row["当前涨幅"] || row["当前涨幅%"] || row["收盘涨幅"] || row["pct"]);
  const vwap = candidateVwapState(row);
  const candle = row["日K形态"] || "";
  const source = row["来源"] || row["来源(缩量回踩/放量突破/watchlist/portfolio)"] || row["策略"] || "";
  const riskMark = row["风险标记"] || "";
  const pullbackRisk = row["风险"] || "";
  if (vwap === "下") flags.push("VWAP 下方，承接不足");
  if (drawdown <= -5) flags.push(`高点回撤 ${drawdown}%`);
  if (candle.includes("长上影")) flags.push("长上影，追高风险");
  if (pct >= 9) flags.push("涨幅接近涨停，不能追高");
  if (riskMark && riskMark !== "normal") flags.push(riskMark);
  if (pullbackRisk) flags.push(pullbackRisk);
  if (source.includes("watchlist") && !source.includes("放量突破")) flags.push("自选观察，仍需触发条件");
  if (!flags.length) {
    return { level: "low", label: "风险低", text: "未见明显回撤或 VWAP 失守，继续看板块强度和成交确认。" };
  }
  const level = flags.length >= 2 || vwap === "下" || drawdown <= -5 ? "high" : "mid";
  return {
    level,
    label: level === "high" ? "风险高" : "风险中",
    text: flags.join("；"),
  };
}

function candidateVwapState(row) {
  const direct = row["VWAP上/下"] || row["VWAP状态"] || "";
  if (direct) return direct;
  const distance = row["VWAP距离%"];
  if (distance !== undefined && distance !== "") return num(distance) >= 0 ? "上" : "下";
  const text = row["走势自然语言"] || "";
  if (text.includes("VWAP 上方")) return "上";
  if (text.includes("VWAP 下方")) return "下";
  return "";
}

function candidateRole(item) {
  const text = `${item.stock} ${item.sector} ${item.source}`;
  if (/中际旭创/.test(text)) return "CPO 中军 / 容量核心";
  if (/新易盛|天孚通信/.test(text)) return "CPO 弹性核心";
  if (/罗博特科/.test(text)) return "光通信 / 设备弹性观察";
  if (/亨通光电|光通信|光纤/.test(text)) return "光通信链条验证";
  if (/CPO/.test(text)) return "CPO 方向观察";
  if (/watchlist/.test(text)) return "自选验证";
  if (/策略/.test(text)) return "策略候选";
  return "候选观察";
}

function candidateCoach(item) {
  if (item.riskLevel === "high") return "风险已经露出来了，先等修复，不要用追涨去证明自己判断正确。";
  if (item.riskLevel === "mid") return "信号还不完整，要等下一 checkpoint 确认承接和板块强度。";
  return "低风险候选也不是买入指令，只是值得继续研究的对象。";
}

function renderCandidateItem(item) {
  return `<strong>${escapeHtml(item.stock)}</strong><span>${escapeHtml([item.sector, item.pct].filter(Boolean).join(" · "))}</span><em>${escapeHtml(item.reason)}</em>`;
}

function renderPortfolioPriority(item) {
  return `<strong>${escapeHtml(item.priority)} · ${escapeHtml(item.stock)}</strong><span>${escapeHtml(item.action_type || "")}</span><em>${escapeHtml(item.reason || "")}</em>`;
}

function renderWatchItem(item) {
  return `<strong>${escapeHtml(item)}</strong>`;
}

function renderTable(table) {
  const columns = table.columns || [];
  const rows = visibleRowsForTable(table);
  if (!columns.length) {
    return `<div class="table-card"><h3>${escapeHtml(tableTitle(table))}</h3><p class="empty">表格为空。</p></div>`;
  }
  const visibleColumns = visibleColumnsForTable(table, columns);
  const head = visibleColumns.map((column) => `<th>${escapeHtml(column)}</th>`).join("");
  const body = rows
    .map((row) => `<tr>${visibleColumns.map((column) => `<td>${escapeHtml(row[column])}</td>`).join("")}</tr>`)
    .join("");
  return `
    <div class="table-card">
      <h3>${escapeHtml(tableTitle(table))} · ${rows.length}/${table.row_count} 行</h3>
      <div class="table-scroll">
        <table>
          <thead><tr>${head}</tr></thead>
          <tbody>${body}</tbody>
        </table>
      </div>
    </div>
  `;
}

function visibleColumnsForTable(table, columns) {
  if (table.name === "market_sector_scan.csv") {
    const preferred = ["时间", "板块", "板块来源", "板块类型", "涨幅", "涨家率", "涨停数", "状态(延续/分歧/切换)", "领涨股"];
    const selected = preferred.filter((column) => columns.includes(column));
    return selected.length ? selected : columns.filter((column) => !column.includes("排名")).slice(0, 12);
  }
  return columns.slice(0, 16);
}

function visibleRowsForTable(table) {
  const rows = table.rows || [];
  if (table.name === "market_sector_scan.csv") {
    return rows.slice(0, 8);
  }
  return rows;
}

function localHoldings() {
  try {
    return JSON.parse(localStorage.getItem(LOCAL_PORTFOLIO_KEY) || "[]");
  } catch {
    return [];
  }
}

function saveLocalHoldings(rows) {
  localStorage.setItem(LOCAL_PORTFOLIO_KEY, JSON.stringify(rows));
}

function mergedHoldings() {
  const historyRows = activeDay?.date ? siteData.portfolio_history?.[activeDay.date]?.base_holdings : null;
  const baseRows = historyRows?.length ? historyRows : siteData.portfolio?.base_holdings || [];
  return baseRows.map((row) => ({ ...row, source: row.source || "portfolio.md" }));
}

function setupPortfolio() {
  if (!byId("portfolio-form")) return;
  const meta = byId("portfolio-meta");
  if (meta) {
    meta.textContent = `portfolio.md：${value(siteData.portfolio?.modified, "未读取")} · 前端保存只存在当前浏览器`;
  }
  byId("portfolio-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const row = {
      code: byId("holding-code").value.trim(),
      name: byId("holding-name").value.trim(),
      shares_total: byId("holding-shares").value,
      avg_cost: byId("holding-cost").value,
      note: byId("holding-note").value.trim(),
    };
    if (!row.code && !row.name) return;
    const rows = localHoldings().filter((item) => String(item.code || item.name) !== String(row.code || row.name));
    rows.push(row);
    saveLocalHoldings(rows);
    event.target.reset();
    renderPortfolio();
  });
  byId("clear-local-portfolio")?.addEventListener("click", () => {
    saveLocalHoldings([]);
    renderPortfolio();
  });
  renderPortfolio();
}

function renderPortfolio() {
  const rows = mergedHoldings();
  const decision = currentCheckpoint()?.decision || {};
  const priorityItems = decision.portfolio_priority || [];
  const table = {
    name: "portfolio_combined.csv",
    columns: ["source", "code", "name", "shares_total", "avg_cost", "current_snapshot", "last_add_price", "shares_added_recently", "note"],
    rows,
    row_count: rows.length,
  };
  const target = byId("portfolio-table");
  if (target) {
    target.innerHTML = `
      <div class="portfolio-priority-panel">
        <h3>当前 checkpoint 持仓处理</h3>
        ${priorityItems.length ? `<div class="priority-list">${priorityItems.slice(0, 8).map(renderPriorityCard).join("")}</div>` : '<p class="empty">当前 checkpoint 暂无持仓优先级。</p>'}
      </div>
      ${renderTable(table)}
    `;
  }
}

function markdownItems() {
  try {
    return JSON.parse(localStorage.getItem(LOCAL_MARKDOWN_KEY) || "[]");
  } catch {
    return [];
  }
}

function saveMarkdownItems(items) {
  localStorage.setItem(LOCAL_MARKDOWN_KEY, JSON.stringify(items));
}

function currentMarkdownId() {
  return byId("markdown-id")?.value || "";
}

function createMarkdownItem() {
  const now = new Date().toISOString();
  return {
    id: `md-${Date.now()}`,
    title: "未命名笔记",
    body: "",
    created_at: now,
    updated_at: now,
  };
}

function setupMarkdown() {
  if (!byId("markdown-form")) return;
  byId("new-markdown")?.addEventListener("click", () => {
    const item = createMarkdownItem();
    const items = [item, ...markdownItems()];
    saveMarkdownItems(items);
    loadMarkdownIntoEditor(item);
    renderMarkdownList();
  });
  byId("markdown-form").addEventListener("submit", (event) => {
    event.preventDefault();
    saveCurrentMarkdown();
  });
  byId("download-markdown")?.addEventListener("click", downloadCurrentMarkdown);
  byId("delete-markdown")?.addEventListener("click", deleteCurrentMarkdown);

  const items = markdownItems();
  if (items.length) {
    loadMarkdownIntoEditor(items[0]);
  } else {
    loadMarkdownIntoEditor(createMarkdownItem(), false);
  }
  renderMarkdownList();
}

function renderMarkdownList() {
  const items = markdownItems();
  const activeId = currentMarkdownId();
  const target = byId("markdown-list");
  if (!target) return;
  target.innerHTML = items.length
    ? items
        .map(
          (item) => `
            <button class="markdown-item ${item.id === activeId ? "active" : ""}" data-id="${escapeHtml(item.id)}">
              <strong>${escapeHtml(item.title || "未命名笔记")}</strong>
              <span>${escapeHtml(displayDate(item.updated_at || item.created_at))}</span>
            </button>
          `,
        )
        .join("")
    : '<p class="empty">还没有 Markdown 笔记。</p>';
  document.querySelectorAll(".markdown-item").forEach((button) => {
    button.addEventListener("click", () => {
      const item = markdownItems().find((entry) => entry.id === button.dataset.id);
      if (item) loadMarkdownIntoEditor(item);
      renderMarkdownList();
    });
  });
}

function loadMarkdownIntoEditor(item, persist = true) {
  if (byId("markdown-id")) byId("markdown-id").value = item.id;
  if (byId("markdown-title")) byId("markdown-title").value = item.title || "";
  if (byId("markdown-body")) byId("markdown-body").value = item.body || "";
  if (persist && !markdownItems().some((entry) => entry.id === item.id)) {
    saveMarkdownItems([item, ...markdownItems()]);
  }
}

function saveCurrentMarkdown() {
  const id = currentMarkdownId() || `md-${Date.now()}`;
  const now = new Date().toISOString();
  const title = byId("markdown-title")?.value.trim() || "未命名笔记";
  const body = byId("markdown-body")?.value || "";
  const items = markdownItems();
  const existing = items.find((item) => item.id === id);
  const next = {
    id,
    title,
    body,
    created_at: existing?.created_at || now,
    updated_at: now,
  };
  saveMarkdownItems([next, ...items.filter((item) => item.id !== id)]);
  loadMarkdownIntoEditor(next, false);
  renderMarkdownList();
}

function deleteCurrentMarkdown() {
  const id = currentMarkdownId();
  if (!id) return;
  const items = markdownItems().filter((item) => item.id !== id);
  saveMarkdownItems(items);
  loadMarkdownIntoEditor(items[0] || createMarkdownItem(), false);
  renderMarkdownList();
}

function downloadCurrentMarkdown() {
  const title = byId("markdown-title")?.value.trim() || "untitled";
  const body = byId("markdown-body")?.value || "";
  const filename = `${slugify(title)}.md`;
  const blob = new Blob([`# ${title}\n\n${body}\n`], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function slugify(value) {
  return String(value)
    .trim()
    .replace(/[\\/:*?"<>|]+/g, "-")
    .replace(/\s+/g, "-")
    .slice(0, 80) || "untitled";
}

function displayDate(value) {
  if (!value) return "-";
  return String(value).slice(0, 10);
}

function renderWeekly(weekly) {
  const meta = byId("weekly-meta");
  const link = byId("weekly-link");
  const preview = byId("weekly-preview");
  if (!meta || !link || !preview) return;
  if (!weekly) {
    meta.textContent = "还没有周报。";
    link.style.display = "none";
    preview.innerHTML = '<p class="empty">暂无周报预览。</p>';
    return;
  }
  meta.textContent = `${weekly.name} · ${weekly.modified}`;
  link.href = weekly.published_path;
  preview.innerHTML = markdownPreview(weekly.text || "");
}

function markdownPreview(text) {
  const lines = text.split("\n");
  const html = [];
  let inTable = false;
  let tableRows = [];
  function flushTable() {
    if (!inTable) return;
    html.push(`<pre>${escapeHtml(tableRows.filter((line) => !/^\|\s*-/.test(line)).slice(0, 18).join("\n"))}</pre>`);
    inTable = false;
    tableRows = [];
  }
  for (const line of lines.slice(0, 220)) {
    if (line.startsWith("|")) {
      inTable = true;
      tableRows.push(line);
      continue;
    }
    flushTable();
    if (line.startsWith("### ")) html.push(`<h3>${escapeHtml(line.slice(4))}</h3>`);
    else if (line.startsWith("## ")) html.push(`<h2>${escapeHtml(line.slice(3))}</h2>`);
    else if (line.startsWith("# ")) html.push(`<h1>${escapeHtml(line.slice(2))}</h1>`);
    else if (line.trim()) html.push(`<p>${escapeHtml(line)}</p>`);
  }
  flushTable();
  return html.join("");
}

function renderFiles(files) {
  const target = byId("recent-files");
  if (!target) return;
  target.innerHTML = (files || [])
    .slice(0, 40)
    .map(
      (file) => `
        <div class="file-item">
          <strong>${escapeHtml(file.name)}</strong>
          <span>${escapeHtml(file.relative_path)}</span>
          <span>${escapeHtml(file.modified)} · ${Math.round(file.size / 1024)} KB</span>
        </div>
      `,
    )
    .join("");
}

async function main() {
  const response = await fetch("./data/site.json");
  siteData = await response.json();
  if (byId("generated-at")) byId("generated-at").textContent = siteData.generated_at || "-";
  setupDateSelector();
  setupViewTabs();
  setupPortfolio();
  setupMarkdown();
  renderWeekly(siteData.latest_weekly);
  renderFiles(siteData.recent_exports);
}

main().catch((error) => {
  document.body.innerHTML = `<main><section class="section"><p class="empty">读取静态数据失败：${escapeHtml(error.message)}</p></section></main>`;
});
