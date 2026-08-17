// ★ 擁有者：P3（README §7）。
//
// 全程不需要後端跑起來：USE_MOCK 為 true 時直接讀 mock.json。
// 第 7 小時合併後才改成 false（步驟 3.10）。

const USE_MOCK = true;
const API_BASE = 'http://localhost:8080';

// 四種交通工具圖示（步驟 3.4）。不要引入圖示套件。
const ICONS = {
  BUS: '🚌',
  METRO: '🚇',
  TRAIN: '🚆',
  HSR: '🚄',
};

const $ = (id) => document.getElementById(id);
const timers = [];

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

const mins = (s) => Math.round(s / 60);

// 步驟 3.8：等待倒數。waitSeconds 不為 null 時每秒遞減，≤ 0 顯示「已過站」
function startCountdown(el, seconds) {
  let left = seconds;
  const tick = () => {
    if (left <= 0) {
      el.textContent = '已過站';
      el.classList.add('passed');
      return;
    }
    const m = Math.floor(left / 60);
    const s = String(left % 60).padStart(2, '0');
    el.textContent = `${m}:${s}`;
    left -= 1;
  };
  tick();
  timers.push(setInterval(tick, 1000));
}

function renderStep(step) {
  if (step.type === 'WALK') {
    return `<li class="step walk">🚶 步行 ${mins(step.seconds)} 分（${step.meters} 公尺）</li>`;
  }
  const icon = ICONS[step.mode] || ICONS.BUS;
  return `<li class="step ride">
    <span class="icon">${icon}</span>
    <b>${step.routeName}</b>
    <span class="stops">${step.fromStop} → ${step.toStop}</span>
    <span class="dur">${mins(step.seconds)} 分 · ${step.stopCount} 站</span>
  </li>`;
}

// 步驟 3.3 / 3.5 / 3.7：卡片列表、即時徽章、展開步驟明細
function renderPlans(plans) {
  const box = $('plans');
  box.innerHTML = '';

  plans.forEach((plan, i) => {
    const card = document.createElement('article');
    card.className = 'card';

    const badge = plan.isLive ? '<span class="badge live">即時</span>' : '';
    const wait =
      plan.waitSeconds === null ? plan.waitSource : `等待 ${mins(plan.waitSeconds)} 分 · ${plan.waitSource}`;

    card.innerHTML = `
      <header>
        <span class="rank">${i + 1}</span>
        <span class="total">${mins(plan.realSeconds)} 分鐘</span>
        ${badge}
      </header>
      <p class="sub">轉乘 ${plan.transferCount} 次 · ${wait}</p>
      <p class="countdown-row${plan.waitSeconds === null ? ' hidden' : ''}">
        下一班進站倒數 <span class="countdown"></span>
      </p>
      <ul class="steps">${plan.steps.map(renderStep).join('')}</ul>
    `;

    // 步驟 3.7：點卡片展開／收合
    card.querySelector('header').addEventListener('click', () => card.classList.toggle('open'));

    if (plan.waitSeconds !== null) {
      startCountdown(card.querySelector('.countdown'), plan.waitSeconds);
    }
    box.appendChild(card);
  });
}

// 步驟 3.9：載入中／錯誤／無結果
function setLoading(on) {
  const btn = $('submit');
  btn.disabled = on;
  btn.textContent = on ? '查詢中…' : '查詢';
}

function showError(msg) {
  const el = $('error');
  el.textContent = msg;
  el.hidden = !msg;
}

function reset() {
  timers.splice(0).forEach(clearInterval);
  showError('');
  $('empty').hidden = true;
  $('reorder-banner').hidden = true;
  $('plans').innerHTML = '';
}

$('query-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  reset();
  setLoading(true);
  try {
    const data = await fetchPlans($('origin').value, $('destination').value);
    const plans = data.plans || [];
    if (!plans.length) {
      $('empty').hidden = false;
      return;
    }
    // 步驟 3.6：reordered 提示條——簡報的視覺重點
    $('reorder-banner').hidden = !data.reordered;
    renderPlans(plans);
  } catch (err) {
    showError(`查詢失敗：${err.message}`);
  } finally {
    setLoading(false);
  }
});

// 開頁就先查一次，方便開發時直接看到畫面
$('query-form').dispatchEvent(new Event('submit'));
