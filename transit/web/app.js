// =========================================================
// 大台北即時轉乘 — 前端邏輯（P3 owns this file）
// 目前完成：搜尋頁互動 + 結果頁（一覽表 + 路線詳情時刻表）+ 除錯面板
// 資料來源：mock.json（USE_MOCK = true）／後端 /api/plans
// =========================================================

// 開發期資料來源切換：整合真實後端時改成 false
const USE_MOCK = false;
const API_BASE = 'http://localhost:8080';

// =========================================================
// 0. Debug — 開啟方式：網址加 ?debug=1、或按 Ctrl+Shift+D
//    關閉後設定會記在 localStorage，重新整理仍有效。
//    Console 也可用：__debug.on() / __debug.off() / __debug.state()
// =========================================================
const DEBUG_KEY = 'transit.debug';
const DEBUG_MAX_ROWS = 200;

let DEBUG_ON =
  new URLSearchParams(location.search).has('debug') ||
  localStorage.getItem(DEBUG_KEY) === '1';

const debugPanel = document.getElementById('debugPanel');
const debugLogEl = document.getElementById('debugLog');
const debugMetaEl = document.getElementById('debugMeta');
const debugFab = document.getElementById('debugFab');
const debugClearBtn = document.getElementById('debugClearBtn');
const debugCloseBtn = document.getElementById('debugCloseBtn');

const debugEntries = [];

const TAG_COLORS = {
  boot: '#4A7EBB',
  search: '#F29400',
  fetch: '#3D8B37',
  render: '#9F4F8B',
  ui: '#666666',
  error: '#C92A2A',
};

function debugStamp() {
  const d = new Date();
  const p = (n, len = 2) => String(n).padStart(len, '0');
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`;
}

function shortJson(data) {
  if (data === undefined) return '';
  try {
    const s = JSON.stringify(data);
    return s.length > 160 ? `${s.slice(0, 160)}…` : s;
  } catch (err) {
    return String(data);
  }
}

function dlog(tag, message, data) {
  const entry = { time: debugStamp(), tag, message, data };
  debugEntries.push(entry);
  if (debugEntries.length > DEBUG_MAX_ROWS) debugEntries.shift();

  if (!DEBUG_ON) return;

  const color = TAG_COLORS[tag] || TAG_COLORS.ui;
  const args = [`%c${entry.time} %c${tag}%c ${message}`,
    'color:#999', `color:${color};font-weight:700`, 'color:inherit'];
  if (data !== undefined) args.push(data);
  (tag === 'error' ? console.error : console.log)(...args);

  appendDebugRow(entry);
  updateDebugMeta();
}

function appendDebugRow(entry) {
  if (!debugLogEl) return;
  const li = document.createElement('li');
  li.className = `debug-row debug-row--${entry.tag}`;
  li.innerHTML = `
    <span class="debug-row__time">${entry.time}</span>
    <span class="debug-row__tag">${escapeHtml(entry.tag)}</span>
    <span class="debug-row__msg">${escapeHtml(entry.message)}</span>
    ${entry.data !== undefined ? `<span class="debug-row__data">${escapeHtml(shortJson(entry.data))}</span>` : ''}`;
  debugLogEl.appendChild(li);
  while (debugLogEl.children.length > DEBUG_MAX_ROWS) debugLogEl.removeChild(debugLogEl.firstChild);
  debugLogEl.scrollTop = debugLogEl.scrollHeight;
}

function updateDebugMeta() {
  if (!debugMetaEl) return;
  const src = USE_MOCK ? 'mock.json' : API_BASE;
  const planCount = lastSearchData?.plans?.length ?? 0;
  debugMetaEl.textContent = `${src} · ${planCount} 方案 · ${debugEntries.length} 筆紀錄`;
}

// 量測一段流程花費多久；回傳的函式呼叫時會寫一筆 log
function dtimer(tag, label) {
  const t0 = performance.now();
  return (extra) => {
    const ms = Math.round(performance.now() - t0);
    dlog(tag, `${label} 完成（${ms} ms）`, extra);
    return ms;
  };
}

function renderDebugBacklog() {
  if (!debugLogEl) return;
  debugLogEl.innerHTML = '';
  debugEntries.forEach(appendDebugRow);
  updateDebugMeta();
}

function setDebug(on, opts = {}) {
  DEBUG_ON = on;
  localStorage.setItem(DEBUG_KEY, on ? '1' : '0');
  if (debugPanel) debugPanel.hidden = !on;
  if (debugFab) debugFab.hidden = !on;
  if (on) {
    renderDebugBacklog();
    if (!opts.silent) dlog('boot', 'Debug 已開啟（Ctrl+Shift+D 可關閉）');
  } else {
    console.log('%cDebug 已關閉（Ctrl+Shift+D 可再開啟）', 'color:#999');
  }
}

document.addEventListener('keydown', (e) => {
  if (e.ctrlKey && e.shiftKey && (e.key === 'D' || e.key === 'd')) {
    e.preventDefault();
    setDebug(!DEBUG_ON);
  }
});

debugCloseBtn?.addEventListener('click', () => setDebug(false));
debugFab?.addEventListener('click', () => {
  const collapsed = debugPanel.classList.toggle('debug-panel--collapsed');
  dlog('ui', collapsed ? '除錯面板收合' : '除錯面板展開');
});
debugClearBtn?.addEventListener('click', () => {
  debugEntries.length = 0;
  if (debugLogEl) debugLogEl.innerHTML = '';
  updateDebugMeta();
});

window.__debug = {
  on: () => setDebug(true),
  off: () => setDebug(false),
  entries: () => [...debugEntries],
  state: () => ({
    useMock: USE_MOCK,
    apiBase: API_BASE,
    origin: lastSearchOrigin,
    destination: lastSearchDestination,
    sort: currentSort,
    timeMode: searchTimeMode,
    selectedPlanIndex,
    data: lastSearchData,
  }),
};

window.addEventListener('error', (e) => {
  dlog('error', `未攔截的錯誤：${e.message}`, { file: e.filename, line: e.lineno });
});
window.addEventListener('unhandledrejection', (e) => {
  dlog('error', '未攔截的 Promise 錯誤', String(e.reason));
});

// 站名推薦清單（demo 用的靜態清單；之後可換成 Google Places 或後端提供的站點資料）
const STATIONS = [
  '台北車站', '台北 101', '士林夜市', '淡水捷運站', '新竹高鐵站',
  '西門町', '中山站', '板橋車站', '松山車站', '南港車站',
  '士林站', '北投站', '天母', '內湖', '松山機場',
  '桃園機場', '三重', '蘆洲', '新店', '永和',
  '中和', '大安森林公園站', '東門站', '忠孝復興站', '忠孝敦化站',
  '市政府站', '北車', '頂溪站', '景美站', '公館站',
  '古亭站', '大直', '劍潭站', '關渡', '紅樹林',
];

// ---------- DOM refs ----------
const liveClockTime = document.getElementById('liveClockTime');
const searchForm = document.getElementById('searchForm');
const originInput = document.getElementById('originInput');
const destinationInput = document.getElementById('destinationInput');
const swapBtn = document.getElementById('swapBtn');
const submitBtn = document.getElementById('submitBtn');
const submitBtnText = document.getElementById('submitBtnText');
const searchError = document.getElementById('searchError');
const searchCard = document.getElementById('searchCard');
const searchView = document.getElementById('searchView');
const resultsView = document.getElementById('resultsView');
const resultOrigin = document.getElementById('resultOrigin');
const resultDestination = document.getElementById('resultDestination');
const backToSearchBtn = document.getElementById('backToSearchBtn');
const routeQueryBar = document.getElementById('routeQueryBar');
const routeSummaryTable = document.getElementById('routeSummaryTable');
const planDetail = document.getElementById('planDetail');
const routeTabBtns = document.querySelectorAll('.route-tabs__btn');
const emptyState = document.getElementById('emptyState');
const prevTrainsBtn = document.getElementById('prevTrainsBtn');
const nextTrainsBtn = document.getElementById('nextTrainsBtn');

let lastSearchData = null;
let lastSearchOrigin = '';
let lastSearchDestination = '';
let selectedPlanIndex = 0;
let currentSort = 'recommended';

const dateInput = document.getElementById('dateInput');
const calendarBtn = document.getElementById('calendarBtn');
const hourSelect = document.getElementById('hourSelect');
const minuteSelect = document.getElementById('minuteSelect');
const nowTimeBtn = document.getElementById('nowTimeBtn');
const timeModeInput = document.getElementById('timeModeInput');

// ---------- 1. Header 即時時鐘（本系統核心概念的視覺化身）----------
function tickClock() {
  const now = new Date();
  const hh = String(now.getHours()).padStart(2, '0');
  const mm = String(now.getMinutes()).padStart(2, '0');
  const ss = String(now.getSeconds()).padStart(2, '0');
  liveClockTime.textContent = `${hh}:${mm}:${ss}`;
}
tickClock();
setInterval(tickClock, 1000);

// ---------- 2. 出發／到達欄位交換 ----------
swapBtn.addEventListener('click', () => {
  const tmp = originInput.value;
  originInput.value = destinationInput.value;
  destinationInput.value = tmp;
  dlog('ui', '交換出發／到達', { origin: originInput.value, destination: destinationInput.value });
});

// ---------- 3. 搜尋紀錄（demo 項目，點擊可快速填入）----------
document.querySelectorAll('.chip').forEach((chip) => {
  chip.addEventListener('click', () => {
    originInput.value = chip.dataset.origin;
    destinationInput.value = chip.dataset.destination;
    dlog('ui', '點擊搜尋紀錄', { origin: chip.dataset.origin, destination: chip.dataset.destination });
    searchForm.requestSubmit();
  });
});

// ---------- 4. 站名自動完成 ----------
// 依輸入的文字即時比對 STATIONS 清單，顯示可點選的建議清單。
function attachAutocomplete(input, listEl) {
  let activeIndex = -1;

  function render(items) {
    listEl.innerHTML = '';
    activeIndex = -1;
    if (items.length === 0) {
      listEl.hidden = true;
      return;
    }
    items.forEach((name) => {
      const li = document.createElement('li');
      li.textContent = name;
      li.addEventListener('mousedown', (e) => {
        // mousedown（早於 blur）才能在欄位失焦前完成選取
        e.preventDefault();
        input.value = name;
        listEl.hidden = true;
      });
      listEl.appendChild(li);
    });
    listEl.hidden = false;
  }

  function filterAndRender() {
    const q = input.value.trim();
    if (!q) {
      listEl.hidden = true;
      return;
    }
    const matches = STATIONS.filter((s) => s.includes(q)).slice(0, 8);
    render(matches);
  }

  input.addEventListener('input', filterAndRender);
  input.addEventListener('focus', filterAndRender);

  input.addEventListener('blur', () => {
    listEl.hidden = true;
  });

  input.addEventListener('keydown', (e) => {
    const items = Array.from(listEl.children);
    if (listEl.hidden || items.length === 0) return;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      activeIndex = (activeIndex + 1) % items.length;
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      activeIndex = (activeIndex - 1 + items.length) % items.length;
    } else if (e.key === 'Enter' && activeIndex >= 0) {
      e.preventDefault();
      input.value = items[activeIndex].textContent;
      listEl.hidden = true;
      return;
    } else if (e.key === 'Escape') {
      listEl.hidden = true;
      return;
    } else {
      return;
    }

    items.forEach((li, i) => li.classList.toggle('is-active', i === activeIndex));
  });
}

attachAutocomplete(originInput, document.getElementById('originSuggestions'));
attachAutocomplete(destinationInput, document.getElementById('destinationSuggestions'));

// ---------- 6. 日期：預設今天 + 日曆按鈕 ----------
function toDateInputValue(d) {
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
}
dateInput.value = toDateInputValue(new Date());
dateInput.min = toDateInputValue(new Date()); // 日曆today以前的日期不能選

calendarBtn.addEventListener('click', () => {
  // showPicker() 是較新的瀏覽器 API；不支援時退回 focus() 讓使用者自己點開
  if (typeof dateInput.showPicker === 'function') {
    try {
      dateInput.showPicker();
      return;
    } catch (err) {
      dlog('error', 'showPicker() 失敗，改用 focus()', String(err));
    }
  }
  dateInput.focus();
});

// ---------- 7. 時間：時／分下拉 + 目前時間按鈕 ----------
function populateTimeSelects() {
  for (let h = 0; h < 24; h++) {
    const opt = document.createElement('option');
    opt.value = String(h).padStart(2, '0');
    opt.textContent = String(h).padStart(2, '0');
    hourSelect.appendChild(opt);
  }
  for (let m = 0; m < 60; m++) {
    const opt = document.createElement('option');
    opt.value = String(m).padStart(2, '0');
    opt.textContent = String(m).padStart(2, '0');
    minuteSelect.appendChild(opt);
  }
}
populateTimeSelects();

function setToNow() {
  const now = new Date();
  hourSelect.value = String(now.getHours()).padStart(2, '0');
  minuteSelect.value = String(now.getMinutes()).padStart(2, '0');
}
setToNow();
nowTimeBtn.addEventListener('click', () => {
  setToNow();
  dlog('ui', '時間設為目前時間', `${hourSelect.value}:${minuteSelect.value}`);
});

// ---------- 8. 時間查詢模式 ----------
// 介面上的離開／到達切換鈕已拿掉，固定用「離開」這個模式；
// setTimeMode() 留著給「從網址參數還原查詢」用，讓舊的分享連結還能正確還原。
let searchTimeMode = 'depart';
function setTimeMode(mode) {
  searchTimeMode = mode;
  if (timeModeInput) timeModeInput.value = mode;
}

// ---------- 9. 表單送出：原地查詢，不跳頁、不整頁刷新 ----------
// 一律 preventDefault 擋掉原生 GET 導頁；驗證通過後改用 history.pushState
// 把查詢參數寫進網址（維持可分享連結、重新整理仍可還原），再直接呼叫
// runSearch() 原地更新結果，畫面不跳轉、不捲動。
searchForm.addEventListener('submit', (event) => {
  event.preventDefault();
  hideError();

  const origin = originInput.value.trim();
  const destination = destinationInput.value.trim();

  if (!origin || !destination) {
    dlog('error', '欄位驗證未通過：出發或到達為空');
    showError('請輸入出發與到達地點');
    return;
  }

  if (dateInput.value && dateInput.value < dateInput.min) {
    dlog('error', '欄位驗證未通過：日期早於今天', dateInput.value);
    showError('查詢日期不能早於今天');
    return;
  }

  dlog('search', '表單送出（原地查詢，不跳頁）', {
    origin,
    destination,
    date: dateInput.value,
    time: `${hourSelect.value}:${minuteSelect.value}`,
    mode: searchTimeMode,
  });

  const params = new URLSearchParams(new FormData(searchForm));
  const newUrl = `${location.pathname}?${params.toString()}`;
  history.pushState({ origin, destination }, '', newUrl);

  runSearch(origin, destination);
});

function showError(message) {
  searchError.textContent = message;
  searchError.hidden = false;
}

function hideError() {
  searchError.hidden = true;
  searchError.textContent = '';
}

function setLoading(isLoading) {
  submitBtn.disabled = isLoading;
  submitBtnText.textContent = isLoading ? '查詢中…' : '查詢轉乘方案';
}

// ---------- 10. 結果區：顯示／隱藏（原地換成結果畫面，不跳頁、不捲動）----------
function showResultsView() {
  emptyState.hidden = true;
  searchView.hidden = true;
  resultsView.hidden = false;
}

function hideResultsView() {
  resultsView.hidden = true;
}

// 「更改搜尋條件」：原地換回搜尋畫面，不捲動
backToSearchBtn.addEventListener('click', () => {
  dlog('ui', '回到搜尋條件');
  resultsView.hidden = true;
  searchView.hidden = false;
  originInput.focus({ preventScroll: true });
});

routeTabBtns.forEach((btn) => {
  btn.addEventListener('click', () => {
    routeTabBtns.forEach((b) => {
      b.classList.remove('route-tabs__btn--active');
      b.setAttribute('aria-selected', 'false');
    });
    btn.classList.add('route-tabs__btn--active');
    btn.setAttribute('aria-selected', 'true');
    currentSort = btn.dataset.sort;
    selectedPlanIndex = 0;
    dlog('ui', '切換排序', currentSort);
    if (lastSearchData) {
      renderResultsPage(lastSearchData, lastSearchOrigin, lastSearchDestination);
    }
  });
});

// 前／後三班：把查詢時間往前後推 15 分鐘再查一次
function shiftQueryTime(deltaMinutes) {
  if (!lastSearchOrigin || !lastSearchDestination) return;
  const dt = getQueryDateTime();
  dt.setMinutes(dt.getMinutes() + deltaMinutes);
  dateInput.value = toDateInputValue(dt);
  hourSelect.value = String(dt.getHours()).padStart(2, '0');
  minuteSelect.value = String(dt.getMinutes()).padStart(2, '0');
  dlog('search', `查詢時間位移 ${deltaMinutes} 分`, formatClock(dt));
  runSearch(lastSearchOrigin, lastSearchDestination);
}

prevTrainsBtn?.addEventListener('click', () => shiftQueryTime(-15));
nextTrainsBtn?.addEventListener('click', () => shiftQueryTime(15));

// ---------- 11. 結果頁：格式化工具 ----------
const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六'];

const MODE_LABELS = {
  BUS: '公車',
  METRO: '捷運',
  TRAIN: '台鐵',
  HSR: '高鐵',
};

const MODE_CLASS = {
  BUS: 'bus',
  METRO: 'metro',
  TRAIN: 'train',
  HSR: 'hsr',
  WALK: 'walk',
};

function getQueryDateTime() {
  const [y, m, d] = dateInput.value.split('-').map(Number);
  const h = parseInt(hourSelect.value, 10);
  const min = parseInt(minuteSelect.value, 10);
  return new Date(y, m - 1, d, h, min, 0);
}

function formatClock(date) {
  const hh = String(date.getHours()).padStart(2, '0');
  const mm = String(date.getMinutes()).padStart(2, '0');
  return `${hh}:${mm}`;
}

function formatDuration(seconds) {
  const mins = Math.round(seconds / 60);
  if (mins < 60) return `${mins} 分鐘`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m ? `${h} 小時 ${m} 分鐘` : `${h} 小時`;
}

function formatMeters(meters) {
  if (!meters) return '';
  return meters >= 1000 ? `${(meters / 1000).toFixed(1)} 公里` : `${meters} 公尺`;
}

function formatFare(value) {
  return value == null ? '—' : `NT$${value}`;
}

function formatQueryBarLabel(dt) {
  const y = dt.getFullYear();
  const mo = dt.getMonth() + 1;
  const d = dt.getDate();
  const wd = WEEKDAYS[dt.getDay()];
  const h = dt.getHours();
  const mm = String(dt.getMinutes()).padStart(2, '0');
  const period = h < 12 ? '上午' : '下午';
  const h12 = h === 0 ? 12 : h > 12 ? h - 12 : h;
  const modeLabel = { depart: '出發', arrive: '到達', first: '首班', last: '末班' }[searchTimeMode] || '出發';
  return `${y}年${mo}月${d}日（星期${wd}）${period}${h12}:${mm}${modeLabel}`;
}

function getPlanTimes(plan, departAt) {
  const start = new Date(departAt);
  const end = new Date(start.getTime() + plan.realSeconds * 1000);
  return { start, end };
}

// 「推薦路線」的加權分數：時間、票價、轉乘次數三者等權重（各 1/3）。
// 每個指標先在「這次查詢的所有方案」內做 min-max 正規化成 0~1 再加權加總，
// 分數越低代表越推薦。正規化是相對於同一批方案比較，跟絕對秒數/金額無關。
const RECOMMEND_WEIGHTS = { time: 1 / 3, fare: 1 / 3, transfer: 1 / 3 };

function buildRecommendScorer(plans) {
  if (plans.length === 0) return () => 0;

  const times = plans.map((p) => p.realSeconds);
  const transfers = plans.map((p) => p.transferCount);
  const fares = plans.map((p) => p.fare).filter((f) => f != null);

  const minTime = Math.min(...times);
  const maxTime = Math.max(...times);
  const minTransfer = Math.min(...transfers);
  const maxTransfer = Math.max(...transfers);
  const minFare = fares.length ? Math.min(...fares) : 0;
  const maxFare = fares.length ? Math.max(...fares) : 0;

  const normalize = (value, min, max) => (max === min ? 0 : (value - min) / (max - min));

  return (plan) => {
    const timeScore = normalize(plan.realSeconds, minTime, maxTime);
    const transferScore = normalize(plan.transferCount, minTransfer, maxTransfer);
    // 沒有票價資料的方案給中間值 0.5，不特別加分也不扣分
    const fareScore = plan.fare == null ? 0.5 : normalize(plan.fare, minFare, maxFare);
    return (
      RECOMMEND_WEIGHTS.time * timeScore +
      RECOMMEND_WEIGHTS.fare * fareScore +
      RECOMMEND_WEIGHTS.transfer * transferScore
    );
  };
}

function sortPlans(plans, sortKey) {
  const copy = [...plans];
  if (sortKey === 'recommended') {
    const score = buildRecommendScorer(copy);
    copy.sort((a, b) => score(a) - score(b) || a.realSeconds - b.realSeconds);
  } else if (sortKey === 'fastest') {
    copy.sort((a, b) => a.realSeconds - b.realSeconds);
  } else if (sortKey === 'fewest') {
    copy.sort((a, b) => a.transferCount - b.transferCount || a.realSeconds - b.realSeconds);
  } else if (sortKey === 'cheapest') {
    // 沒有票價資料的方案排在最後
    const fare = (p) => (p.fare == null ? Number.MAX_SAFE_INTEGER : p.fare);
    copy.sort((a, b) => fare(a) - fare(b) || a.realSeconds - b.realSeconds);
  } else if (sortKey === 'live') {
    copy.sort((a, b) => Number(b.isLive) - Number(a.isLive) || a.realSeconds - b.realSeconds);
  }
  return copy;
}

function getTotalMeters(steps) {
  return steps.reduce((sum, s) => sum + (s.meters || 0), 0);
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ---------- 12. 結果頁：渲染 ----------
function renderResultsPage(data, origin, destination) {
  const done = dtimer('render', '結果頁渲染');

  lastSearchData = data;
  lastSearchOrigin = origin;
  lastSearchDestination = destination;

  const departAt = getQueryDateTime();
  const plans = sortPlans(data.plans, currentSort);

  resultOrigin.textContent = origin;
  resultDestination.textContent = destination;
  routeQueryBar.textContent = formatQueryBarLabel(departAt);

  if (selectedPlanIndex >= plans.length) selectedPlanIndex = 0;

  routeSummaryTable.innerHTML = plans.map((plan, idx) => {
    const { start, end } = getPlanTimes(plan, departAt);
    const isActive = idx === selectedPlanIndex;
    const liveTag = plan.isLive ? '<span class="route-summary__live">即時</span>' : '';
    const waitInfo = plan.waitSeconds != null
      ? `<span class="route-summary__wait">候車 ${Math.round(plan.waitSeconds / 60)} 分（${escapeHtml(plan.waitSource)}）</span>`
      : `<span class="route-summary__wait">${escapeHtml(plan.waitSource || '班表推估')}</span>`;

    return `
      <button type="button"
              class="route-summary__row${isActive ? ' route-summary__row--active' : ''}"
              data-plan-index="${idx}"
              aria-pressed="${isActive}">
        <span class="route-summary__num">${idx + 1}</span>
        <span class="route-summary__times">
          ${formatClock(start)}<span class="route-summary__arrow">⇒</span>${formatClock(end)}
        </span>
        <span class="route-summary__duration">${formatDuration(plan.realSeconds)}</span>
        <span class="route-summary__fare">
          <span class="route-summary__fare-main">${formatFare(plan.fare)}</span>
          ${plan.icFare != null ? `<span class="route-summary__fare-ic">悠遊卡 ${formatFare(plan.icFare)}</span>` : ''}
        </span>
        <span class="route-summary__transfer">${plan.transferCount} 次轉乘</span>
        <span class="route-summary__meta">${liveTag}${waitInfo}</span>
        <span class="route-summary__modes">${renderModeIcons(plan.steps)}</span>
      </button>`;
  }).join('');

  routeSummaryTable.querySelectorAll('.route-summary__row').forEach((row) => {
    row.addEventListener('click', () => {
      selectedPlanIndex = Number(row.dataset.planIndex);
      dlog('ui', '選擇方案', { index: selectedPlanIndex + 1, sort: currentSort });
      renderResultsPage(data, origin, destination);
    });
  });

  if (plans.length > 0) {
    renderPlanDetail(plans[selectedPlanIndex], selectedPlanIndex, departAt);
    planDetail.hidden = false;
  } else {
    planDetail.hidden = true;
  }

  done({ plans: plans.length, sort: currentSort, selected: selectedPlanIndex + 1 });
}

function renderModeIcons(steps) {
  const modes = [];
  steps.forEach((s) => {
    if (s.type === 'RIDE' && !modes.includes(s.mode)) modes.push(s.mode);
  });
  return modes.map((m) =>
    `<span class="mode-dot mode-dot--${MODE_CLASS[m] || 'metro'}" title="${MODE_LABELS[m] || m}"></span>`
  ).join('');
}

function renderPlanDetail(plan, index, departAt) {
  const { start, end } = getPlanTimes(plan, departAt);
  const meters = getTotalMeters(plan.steps);
  const timeline = buildTimeline(plan, departAt, lastSearchDestination);

  planDetail.innerHTML = `
    <div class="plan-detail__header">
      <span class="plan-detail__num">${index + 1}</span>
      <div class="plan-detail__summary">
        <p class="plan-detail__times">
          <strong>${formatClock(start)}</strong> 出發
          <span class="plan-detail__arrow">›</span>
          <strong>${formatClock(end)}</strong> 到達
        </p>
        <p class="plan-detail__stats">
          期間 ${formatDuration(plan.realSeconds)}
          · 轉乘 ${plan.transferCount} 次
          ${meters ? `· 距離 ${formatMeters(meters)}` : ''}
        </p>
        <div class="plan-detail__tags">
          ${plan.isLive ? '<span class="plan-tag plan-tag--live">即時</span>' : ''}
          ${plan.transferCount === 0 ? '<span class="plan-tag plan-tag--easy">樂</span>' : ''}
          ${plan.realSeconds <= 1800 ? '<span class="plan-tag plan-tag--fast">快</span>' : ''}
        </div>
      </div>
      <div class="plan-detail__fare">
        <span class="plan-detail__fare-label">通常</span>
        <span class="plan-detail__fare-main">${formatFare(plan.fare)}</span>
        ${plan.icFare != null ? `<span class="plan-detail__fare-ic">悠遊卡 ${formatFare(plan.icFare)}</span>` : ''}
      </div>
    </div>

    <div class="timeline">${timeline}</div>`;
}

// ---------- 13. 時刻表時間軸 ----------
// 把 steps 轉成「車站節點 ↔ 乘車／步行區間」交錯的列表：
// 同一站的「到達 + 出發」會合併成一個節點（站內轉乘的步行寫成註記）。
function buildTimeline(plan, departAt, destinationName) {
  let cursor = new Date(departAt);
  const rows = [];
  let pending = null; // 上一段車的到站資訊：{ stop, arriveAt, mode, walk }

  const pushStation = (station) => rows.push({ kind: 'station', ...station });

  plan.steps.forEach((step) => {
    if (step.type === 'WALK') {
      if (pending) {
        // 下車之後的步行：先掛在到站節點上，等下一段車決定是同站轉乘還是跨站
        pending.walk = step;
      } else {
        rows.push({ kind: 'walk', step });
      }
      cursor = new Date(cursor.getTime() + step.seconds * 1000);
      return;
    }

    if (step.type !== 'RIDE') return;

    // step.waitSeconds 是選用欄位（候車）；它必須已經算在 plan.realSeconds 裡，
    // 否則時間軸的到站時間會跟上方一覽表的抵達時間對不起來。
    const waitSeconds = step.waitSeconds || 0;
    const departTime = new Date(cursor.getTime() + waitSeconds * 1000);
    const arriveTime = new Date(departTime.getTime() + step.seconds * 1000);

    if (pending && pending.stop === step.fromStop) {
      // 同一站轉乘 → 合併成「到達 / 出發」一個節點
      pushStation({
        name: step.fromStop,
        arriveAt: pending.arriveAt,
        departAt: departTime,
        mode: step.mode,
        walk: pending.walk,
        waitSeconds,
      });
    } else {
      if (pending) {
        pushStation({ name: pending.stop, arriveAt: pending.arriveAt, mode: pending.mode });
        if (pending.walk) rows.push({ kind: 'walk', step: pending.walk });
      }
      pushStation({ name: step.fromStop, departAt: departTime, mode: step.mode, waitSeconds });
    }

    pending = null;
    rows.push({ kind: 'ride', step });
    pending = { stop: step.toStop, arriveAt: arriveTime, mode: step.mode, walk: null };
    cursor = arriveTime;
  });

  if (pending) {
    pushStation({ name: pending.stop, arriveAt: pending.arriveAt, mode: pending.mode });
    if (pending.walk) {
      rows.push({ kind: 'walk', step: pending.walk });
      pushStation({ name: destinationName || '目的地', arriveAt: cursor });
    }
  }

  // 第一個／最後一個車站節點掛上「離開 / 到達」標籤
  const stationRows = rows.filter((r) => r.kind === 'station');
  if (stationRows.length) {
    stationRows[0].isStart = true;
    stationRows[stationRows.length - 1].isEnd = true;
  }

  return rows.map(renderTimelineRow).join('');
}

function renderTimelineRow(row) {
  if (row.kind === 'station') return renderStationRow(row);
  if (row.kind === 'ride') return renderRideRow(row.step);
  return renderWalkRow(row.step);
}

function renderStationRow(s) {
  const modeClass = MODE_CLASS[s.mode] || 'metro';
  const badge = s.isStart
    ? '<span class="tl-badge tl-badge--start">離開</span>'
    : s.isEnd
      ? '<span class="tl-badge tl-badge--end">到達</span>'
      : '';

  const notes = [];
  if (s.walk) {
    notes.push(`站內轉乘：步行 ${Math.round(s.walk.seconds / 60)} 分${s.walk.meters ? ` · ${formatMeters(s.walk.meters)}` : ''}`);
  }
  if (s.waitSeconds) {
    notes.push(`候車 ${Math.round(s.waitSeconds / 60)} 分`);
  }

  return `
    <div class="tl-row tl-row--station${s.isStart ? ' tl-row--start' : ''}${s.isEnd ? ' tl-row--end' : ''}">
      <div class="tl-row__time">
        ${s.arriveAt ? `<span class="tl-time tl-time--arrive">${formatClock(s.arriveAt)} 到達</span>` : ''}
        ${s.departAt ? `<span class="tl-time tl-time--depart">${formatClock(s.departAt)} 出發</span>` : ''}
      </div>
      <div class="tl-row__rail">
        <span class="tl-pin tl-pin--${modeClass}"></span>
      </div>
      <div class="tl-row__body">
        <div class="tl-station">
          ${badge}
          <strong class="tl-station__name">${escapeHtml(s.name)}</strong>
          <span class="tl-station__tools">
            <button type="button" class="tl-tool">區域地圖</button>
            <button type="button" class="tl-tool">時間表</button>
          </span>
        </div>
        ${notes.map((n) => `<p class="tl-note">${escapeHtml(n)}</p>`).join('')}
      </div>
    </div>`;
}

function renderRideRow(step) {
  const modeClass = MODE_CLASS[step.mode] || 'metro';
  const modeLabel = MODE_LABELS[step.mode] || step.mode;

  return `
    <div class="tl-row tl-row--ride tl-row--${modeClass}">
      <div class="tl-row__time">
        <span class="tl-time tl-time--dur">${Math.round(step.seconds / 60)} 分鐘</span>
        ${step.meters ? `<span class="tl-time tl-time--dist">${formatMeters(step.meters)}</span>` : ''}
      </div>
      <div class="tl-row__rail">
        <span class="tl-bar tl-bar--${modeClass}"></span>
      </div>
      <div class="tl-row__body">
        <p class="tl-ride__route">
          <span class="tl-mode-tag tl-mode-tag--${modeClass}">${escapeHtml(modeLabel)}</span>
          <strong>${escapeHtml(step.routeName)}</strong>
          <span class="tl-ride__dir">往 ${escapeHtml(step.toStop)}</span>
        </p>
        ${step.platform ? `<p class="tl-platform">${escapeHtml(step.platform)}</p>` : ''}
        <p class="tl-ride__detail">${step.stopCount ? `${step.stopCount} 站 · ` : ''}中間停靠</p>
      </div>
    </div>`;
}

function renderWalkRow(step) {
  return `
    <div class="tl-row tl-row--walk">
      <div class="tl-row__time">
        <span class="tl-time tl-time--dur">${Math.round(step.seconds / 60)} 分鐘</span>
        ${step.meters ? `<span class="tl-time tl-time--dist">${formatMeters(step.meters)}</span>` : ''}
      </div>
      <div class="tl-row__rail">
        <span class="tl-bar tl-bar--walk"></span>
      </div>
      <div class="tl-row__body">
        <p class="tl-ride__route"><span class="tl-mode-tag tl-mode-tag--walk">步行</span></p>
        <p class="tl-ride__detail">徒步移動</p>
      </div>
    </div>`;
}

// ---------- 14. 查詢主流程 ----------
async function runSearch(origin, destination) {
  setLoading(true);
  emptyState.hidden = true;
  selectedPlanIndex = 0;
  currentSort = 'recommended';
  routeTabBtns.forEach((b) => {
    const on = b.dataset.sort === 'recommended';
    b.classList.toggle('route-tabs__btn--active', on);
    b.setAttribute('aria-selected', String(on));
  });

  const url = USE_MOCK
    ? './mock.json'
    : `${API_BASE}/api/plans?origin=${encodeURIComponent(origin)}&destination=${encodeURIComponent(destination)}`;

  dlog('fetch', `送出請求（${USE_MOCK ? 'MOCK' : 'API'}）`, url);
  const done = dtimer('fetch', '取得資料');

  try {
    const res = await fetch(url);
    dlog('fetch', `回應 HTTP ${res.status}`, { ok: res.ok });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const data = await res.json();
    done({
      plans: data.plans?.length ?? 0,
      reordered: !!data.reordered,
      live: (data.plans || []).filter((p) => p.isLive).length,
    });

    if (!data.plans || data.plans.length === 0) {
      dlog('search', '查無路線');
      hideResultsView();
      emptyState.hidden = false;
    } else {
      renderResultsPage(data, origin, destination);
      showResultsView();
      dlog('search', '查詢完成', { origin, destination, plans: data.plans.length });
    }
  } catch (err) {
    dlog('error', '查詢失敗', String(err));
    hideResultsView();
    showError('查詢失敗，請稍後再試');
    console.error(err);
  } finally {
    setLoading(false);
    updateDebugMeta();
  }
}

// ---------- 15. 從網址參數還原查詢 ----------
// 表單送出時放行原生 GET，瀏覽器會整頁刷新到「目前網址 + 查詢參數」（等同點超連結）。
// 這裡在頁面重新載入後讀回那些參數，補回表單內容，並自動查一次、捲到結果區，
// 讓「按下查詢 → 整頁刷新 → 落在結果頁」的流程走完。
function restoreFromQueryString() {
  const params = new URLSearchParams(location.search);
  const origin = params.get('origin')?.trim();
  const destination = params.get('destination')?.trim();
  if (!origin || !destination) return false;

  originInput.value = origin;
  destinationInput.value = destination;
  if (params.has('date')) dateInput.value = params.get('date');
  if (params.has('hour')) hourSelect.value = params.get('hour');
  if (params.has('minute')) minuteSelect.value = params.get('minute');
  setTimeMode(params.get('mode') || 'depart');

  dlog('boot', '偵測到網址查詢參數，自動還原並查詢', { origin, destination });
  runSearch(origin, destination);
  return true;
}

// ---------- 啟動 ----------
setDebug(DEBUG_ON, { silent: true });
dlog('boot', '前端初始化完成', { USE_MOCK, API_BASE, stations: STATIONS.length });
restoreFromQueryString();
