// ★ 擁有者：P3（README §7）。本檔由 P4 建立骨架，邏輯全部由 P3 實作。
// ★ P4 到此為止，之後不再修改 web/ 底下任何檔案。
//
// 全程不需要後端跑起來：USE_MOCK 為 true 時直接讀 mock.json。
// 第 7 小時合併後才改成 false（步驟 3.10）。
//
// 注意：mock.json 在上一層目錄。P4 已建好 web/mock.json -> ../mock.json 的 symlink
// （已加進 .gitignore），所以在 web/ 起 server 時 './mock.json' 直接可用，不會有兩份漂移。

const USE_MOCK = true;
const API_BASE = 'http://localhost:8080';

// 四種交通工具圖示（步驟 3.4）。不要引入圖示套件。
const ICONS = {
  BUS: '🚌',
  METRO: '🚇',
  TRAIN: '🚆',
  HSR: '🚄',
};

function buildUrl(from, to) {
  return USE_MOCK
    ? './mock.json'
    : `${API_BASE}/api/plans?origin=${encodeURIComponent(from)}&destination=${encodeURIComponent(to)}`;
}

async function fetchPlans(from, to) {
  const res = await fetch(buildUrl(from, to));
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// TODO(P3, 步驟 3.3 / 3.5 / 3.7)：渲染方案卡片
//   排名數字、realSeconds/60 取整顯示「N 分鐘」、isLive 綠色徽章、
//   副標「轉乘 N 次 · 等待 N 分 · {waitSource}」、點擊展開 RIDE 步驟明細
//   ★ waitSeconds 可能是 null，副標要處理這種情況
function renderPlans(plans) {
  throw new Error('not implemented');
}

// TODO(P3, 步驟 3.8)：等待倒數
//   waitSeconds 不為 null 時用 setInterval 每秒遞減；≤ 0 顯示「已過站」
//   ★ 重新查詢時記得 clearInterval，否則舊的計時器會一直跑
function startCountdown(el, seconds) {
  throw new Error('not implemented');
}

// TODO(P3, 步驟 3.9)：載入中（按鈕變「查詢中…」並停用）、錯誤（紅字）、無結果
function setLoading(on) {
  throw new Error('not implemented');
}

document.getElementById('query-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  // TODO(P3, 步驟 3.2)：接上 fetchPlans → renderPlans
  //   並依 data.reordered 決定 #reorder-banner 的 hidden
});
