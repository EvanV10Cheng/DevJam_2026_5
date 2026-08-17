# 大台北即時轉乘系統 — 四人分工開發規格

> **本文件可直接交給 AI agent 執行。** 指派方式：告訴 agent「你是 P1，請從第 5 節開始執行」。
>
> 文件結構：
> - 第 0–4 節：**全員共同**。開工前所有人都要讀完。
> - 第 5–8 節：**各自負責**。只讀自己那一節，不要動別人的檔案。
> - 第 9–12 節：合併、階段二、風險、驗收。

---

## 0. 給 AI Agent 的執行規則

1. **只修改你被指派的檔案。** 每一節開頭都寫明「你擁有的檔案」與「你禁止修改的檔案」。需要別人的功能時，直接 import 他的函式並相信簽章，不要去看或改他的實作。
2. **契約已凍結。** 第 3 節的 JSON 欄位名稱、第 4 節的函式簽章，任何人都不得單方面修改。需要改動時停下來詢問使用者。
3. **不要重構、不要加抽象層、不要引入額外套件。** 相依套件只有 `fastapi`、`uvicorn`、`httpx`。這是 24 小時期限下的刻意取捨。
4. **每個步驟都有驗收條件**，是可執行的指令或可觀察的現象。通過才進下一步。
5. **卡超過 30 分鐘就走降級路徑。** 每個高風險步驟都寫了降級方案，走降級不算失敗。
6. **絕不讓整個請求失敗。** 任何外部 API 失敗都要有回傳預設值的路徑。

---

## 1. 專案目標與範圍

### 核心價值主張（簡報唯一要講的一句話）

> Google Maps 用**靜態班表**算路線，不知道車現在在哪裡。我們用 Google 找候選、用 TDX 補**即時到站**，重新排序後最快的方案常常不是 Google 排第一的那個。

### 關鍵架構決策

**多模式轉乘不自己算。** Google Routes API 的 `TRANSIT` 模式在大台北已涵蓋台鐵、高鐵、捷運、公車，轉乘組合也已算好。自建圖跑最短路徑在 24 小時內做不完，做出來也不會比 Google 好。

**唯一自己做的是疊上即時資料。** 這是 Google 沒有的資訊，也是本系統存在的理由。

### 兩個階段

| | 階段一（0–10h） | 階段二（10–22h） |
|---|---|---|
| 客戶端 | 網頁（HTML + 原生 JS） | Flutter Android App |
| 後端 | FastAPI | **完全不變** |
| 理由 | 省掉 Android SDK 設定、模擬器啟動、建置等待 | 同一個 API，等於照著網頁版再寫一次 UI |

### 範圍界定

| 包含 | 不包含 |
|---|---|
| 大台北：台鐵、高鐵、捷運、公車 | 其他縣市 |
| **第一段搭乘**的即時到站疊加 | 全程每一段的即時資料 |
| 依實際總時間重新排序 | 自建圖與最短路徑演算法 |
| Cloud Run 部署 | Firebase、Redis、使用者帳號、地圖繪製 |

---

## 2. 【共同】第 1 小時：唯一的同步時段

這一小時全員一起做，做完之後各做各的，**中間不開會**，第 7 小時才再合併。

### 2.1 取得金鑰（0–30 分）★ 不可跳過、不可延後

| # | 動作 | 負責 | 驗收條件 |
|---|---|---|---|
| A | 註冊 TDX（tdx.transportdata.tw）→ 會員專區 → 建立應用程式 | P2 | 手上有 client id 與 secret |
| B | Google Cloud 建專案 → 啟用 **Routes API** → 建立 API key | P1 | Console 顯示 Routes API 已啟用 |
| C | **設定 Routes API 每日用量上限 1000 次** | P1 | 配額頁面顯示上限 |
| D | 把金鑰貼進共用的私訊或記事本，全員複製到各自的 `.env` | 全員 | 各自 `.env` 存在 |

> 這半小時什麼程式都不要寫。金鑰申請是唯一無法靠寫程式解決的環節，必須最先排除。

### 2.2 建立專案骨架（30–50 分）

P4 執行，建立以下結構並 commit 到 main 分支：

```
transit/
├── main.py             # P4     組裝、排序、API 端點
├── google_client.py    # P1     Google Routes 串接
├── tdx_client.py       # P2     TDX 即時到站
├── mock.json           # P4     假資料，解鎖 P3
├── check_contract.py   # P4     契約檢查器，§9.4 逐欄位比對用
├── requirements.txt    # P4
├── Dockerfile          # P4
├── .dockerignore       # P4     擋住 .env 與 .venv，不讓它們進 image
├── .env                # 全員（已在 .gitignore）
├── .env.example        # P4     金鑰欄位範本，複製成 .env 後填值
├── .gitignore
├── fixtures/           # P1     Google 原始回傳存檔
└── web/                # P3
    ├── index.html
    └── app.js
```

`google_client.py` 與 `tdx_client.py` 先只放函式簽章與 `return` 假值（見第 4 節），讓 `main.py` 一開始就能跑起來。

`.gitignore` 內容：
```
.env
__pycache__/
*.pyc
.venv/
web/mock.json
```

`.dockerignore` 內容。**沒有這個檔，`Dockerfile` 的 `COPY . .` 會把 `.env` 打進 image**，與 §8「金鑰用 Secret Manager，不要把 `.env` 打進 image」直接衝突，image 推上去就是金鑰外洩；順便擋掉 `.venv/`，否則 image 會肥好幾百 MB：
```
.env
.venv/
__pycache__/
*.pyc
web/mock.json
fixtures/
.git/
.gitignore
```

`requirements.txt` 內容：
```
fastapi
uvicorn[standard]
httpx
```

### 2.3 開分支（50–60 分）

```bash
git checkout -b p1/google      # P1
git checkout -b p2/tdx         # P2
git checkout -b p3/web         # P3
git checkout -b p4/assemble    # P4
```

**每個人只改自己那一個檔案，所以合併時衝突機率極低。**

### 2.4 怎麼啟動這個專案（全員必讀）

#### ★ 最容易浪費半小時的坑：`--env-file`

**本機啟動後端一定要帶 `--env-file .env`。**

```bash
uvicorn main:app --port 8080 --env-file .env
```

`google_client.py` 與 `tdx_client.py` 在 **import 的當下**就用 `os.getenv()` 把金鑰讀成模組層級變數，而專案裡沒有任何程式會自動載入 `.env`。少了這個參數，兩邊的金鑰都是空字串，症狀是：

| 你看到的錯誤 | 真正的原因 |
|---|---|
| Google Routes 回 **403** | `GOOGLE_MAPS_API_KEY` 是空字串 |
| TDX 取 token 回 **401** | `TDX_CLIENT_ID` / `TDX_CLIENT_SECRET` 是空字串 |

這兩個錯誤碼看起來都像「金鑰申請錯了」，會讓 P1 或 P2 跑回 Console 重新申請金鑰，白白燒掉半小時。**先確認 `--env-file` 有帶，再去懷疑金鑰本身。**

`--env-file` 是 `uvicorn[standard]` 的內建功能，不需要額外裝套件（不違反 §0 規則 3）。

不用 uvicorn 直接跑（例如寫測試腳本）時的等效寫法：

```bash
set -a; source .env; set +a       # 之後這個 shell 怎麼跑都讀得到
```

**Cloud Run 上不需要這個參數**，`--set-secrets` 會直接把 secret 注入成真的環境變數。

#### 第一次設定（每人做一次）

```bash
cd transit
cp .env.example .env              # 然後把 §2.1 拿到的金鑰填進去
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

#### 日常啟動

**後端（P1 / P2 / P4）**

```bash
cd transit
.venv/bin/uvicorn main:app --port 8080 --env-file .env
```

驗證：

```bash
curl localhost:8080/healthz                       # 應回 {"ok":true}
curl -G --data-urlencode "origin=台北車站" \
        --data-urlencode "destination=淡水捷運站" \
        localhost:8080/api/plans
```

> **中文參數一定要 URL-encode。** 直接寫 `curl "localhost:8080/api/plans?origin=台北車站"` 會讓 uvicorn 判定成 Invalid HTTP request，curl 收到空回應，看起來像後端壞了。用 `-G --data-urlencode` 就不會有這問題。§9.3 驗收時會踩到。

**網頁（P3）**

```bash
cd transit/web
ln -sf ../mock.json mock.json     # 只需做一次；已在 .gitignore
python -m http.server 5500
```

開 <http://localhost:5500>。`USE_MOCK = true` 時完全不需要後端。

> 用 symlink 而不是複製，是為了避免 `mock.json` 出現兩份各自漂移的版本。

**Docker（P4，部署前驗證）**

```bash
cd transit
docker build -t transit-api .
docker run --rm -e PORT=8080 -p 8080:8080 transit-api
```

`PORT` 要用環境變數餵，因為 Cloud Run 就是這樣注入的——本機用寫死的 8080 測不出 `$PORT` 沒接好的問題。

#### 檢查契約有沒有跑掉

```bash
python check_contract.py mock.json
python check_contract.py "http://localhost:8080/api/plans?origin=台北車站&destination=淡水捷運站"
```

兩邊都要 0 個錯誤，而且欄位名稱與型別必須一致。這就是 §9.4 的驗收方式——用眼睛比對在第 7 小時的時間壓力下一定會漏掉。

---

## 3. 【共同】API 契約（已凍結）

只有一個端點。不使用 Pydantic model，直接回傳 dict。

### `GET /api/plans?origin={字串}&destination={字串}`

起訖點**直接傳字串**給 Google Routes API 的 `address` 欄位，不需要 Places Autocomplete。

### 回傳最外層

| 欄位 | 型別 | 產出者 | 說明 |
|---|---|---|---|
| `queryTime` | int | P4 | 查詢時刻（epoch 秒） |
| `plans` | list | P4 | 依 `realSeconds` 遞增排序 |
| `googleOrder` | list[int] | P4 | Google 原始順序的 `realSeconds`，用於對照 |
| `reordered` | bool | P4 | **true 代表我們的第一名與 Google 不同——這是專案成功的證據** |

### plan 物件

| 欄位 | 型別 | 產出者 | 說明 |
|---|---|---|---|
| `totalSeconds` | int | **P1** | Google 估的行程時間（不含等待） |
| `transferCount` | int | **P1** | 轉乘次數 |
| `steps` | list | **P1** | 步驟陣列 |
| `polyline` | str | **P1** | 整條路線的 encoded polyline（階段二地圖用，階段一不用） |
| `waitSeconds` | int \| null | **P4** | 真實等待秒數，查不到為 `null` |
| `waitSource` | str | **P4** | `"即時"` / `"班表推估"` / `"末班已過"` |
| `realSeconds` | int | **P4** | `totalSeconds + (waitSeconds or 0)`，**排序依據** |
| `isLive` | bool | **P4** | `waitSource == "即時"` |

### step 物件

`type` 為 `"WALK"` 時：

| 欄位 | 型別 | 說明 |
|---|---|---|
| `type` | str | `"WALK"` |
| `seconds` | int | 步行秒數 |
| `meters` | int | 步行公尺 |

`type` 為 `"RIDE"` 時：

| 欄位 | 型別 | 說明 |
|---|---|---|
| `type` | str | `"RIDE"` |
| `mode` | str | `"BUS"` / `"METRO"` / `"TRAIN"` / `"HSR"` |
| `routeName` | str | 路線名稱，例如 `"307"`、`"淡水信義線"` |
| `fromStop` | str | 上車站名 |
| `toStop` | str | 下車站名 |
| `seconds` | int | 乘車秒數 |
| `stopCount` | int | 經過站數 |

### ★ 契約的硬性規則

**所有欄位一律存在，就算值是 null。** 不可以寫成「查得到才加這個 key」。

理由：JavaScript 對缺欄位寬容（`undefined` 不會爆），**但階段二的 Dart 不是**——`jsonDecode` 給 null，當成 `int` 用就直接拋 exception，App 當場閃退。現在守住這條規則，階段二才不用回頭改後端。

---

## 4. 【共同】main.py 架構與函式簽章

### 資料流

```
GET /api/plans?origin=&destination=
        ↓
① plans = await google_client.get_routes(origin, destination)      ← P1
        ↓  每個 plan 已有 totalSeconds / transferCount / steps / polyline
        ↓
② 對每個 plan，取出第一個 RIDE step
   若 mode == "BUS"：
       secs, src = await tdx_client.get_eta(routeName, fromStop)    ← P2
   否則：
       secs, src = None, "班表推估"
   （用 asyncio.gather 併發處理所有 plan）
        ↓
③ plan["waitSeconds"] = secs
   plan["waitSource"]  = src
   plan["realSeconds"] = totalSeconds + (secs or 0)
   plan["isLive"]      = (src == "即時")
        ↓
④ ranked = sorted(plans, key=realSeconds)
   reordered = ranked[0] is not plans[0]
        ↓
⑤ 回傳 {queryTime, plans: ranked, googleOrder, reordered}
```

### 三個凍結的函式簽章

```python
# ---- google_client.py（P1 擁有）----
async def get_routes(origin: str, destination: str) -> list[dict]:
    """呼叫 Google Routes API 並正規化。

    回傳 list[plan]，每個 plan 含且僅含：
        totalSeconds, transferCount, steps, polyline
    等待相關欄位由 main.py 負責補上，這裡不要碰。

    失敗時回傳空 list []，不要拋例外。
    """


# ---- tdx_client.py（P2 擁有）----
async def get_eta(route_name: str, stop_name: str) -> tuple[int | None, str]:
    """查某條公車在某站牌的即時到站。

    回傳 (等待秒數, 來源說明)：
        查到即時資料      -> (整數秒數, "即時")
        末班已過或未營運  -> (None, "末班已過")
        其他任何情況      -> (None, "班表推估")

    ★ 這個函式絕對不能拋例外。任何錯誤（網路、認證、解析）
      都要 catch 起來並回傳 (None, "班表推估")。
    """
```

> **`get_eta` 不拋例外是刻意設計。** TDX 是系統最不穩定的一環，若它會拋例外，P4 的組裝層就得寫一堆 try/except，兩人就得討論錯誤處理。改成「查不到回 None」，P4 完全不用管，兩人零溝通。

### main.py 骨架（P4 在第 1 小時就要讓它能跑）

```python
import asyncio, time
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import google_client, tdx_client

app = FastAPI(title="大台北即時轉乘")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.get("/api/plans")
async def plans(origin: str = Query(...), destination: str = Query(...)):
    ...   # 見上方資料流五個步驟
```

---

## 5. P1｜Google 路線層

**你擁有**：`google_client.py`、`fixtures/`
**你禁止修改**：`main.py`、`tdx_client.py`、`web/`
**你的依賴**：只有 Google API key。不依賴任何隊友。

> 這是四條線中工作量最大的一條，因為 Google 的回傳結構很深，而且台鐵／高鐵／捷運的 `vehicle.type` 實際值必須實測才知道。

### 技術規格

**端點**：`POST https://routes.googleapis.com/directions/v2:computeRoutes`

**必要 Headers**：
```
X-Goog-Api-Key: {你的 key}
X-Goog-FieldMask: {見下}
Content-Type: application/json
```

**FieldMask**（沒有這個會回 400，Routes API 強制要求）：
```
routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline,
routes.legs.steps.travelMode,routes.legs.steps.staticDuration,
routes.legs.steps.distanceMeters,routes.legs.steps.transitDetails
```

**Request body**：
```json
{
  "origin": {"address": "台北車站"},
  "destination": {"address": "淡水捷運站"},
  "travelMode": "TRANSIT",
  "computeAlternativeRoutes": true,
  "languageCode": "zh-TW",
  "regionCode": "TW"
}
```

**兩個必知的解析陷阱**：
1. 時間欄位是字串格式 `"900s"`，不是數字。要寫一個 `_secs()` 把 `"900s"` 轉成 `900`，並處理 `"900.5s"` 與 `None`。
2. 步驟藏在 `routes[].legs[].steps[]`，是**兩層巢狀**。要用雙層迴圈攤平。

**vehicle type 映射表**（放在 `google_client.py` 頂端）：

| Google 的 `transitLine.vehicle.type` | 我們的 `mode` |
|---|---|
| `BUS` | `BUS` |
| `SUBWAY`、`METRO_RAIL` | `METRO` |
| `HEAVY_RAIL`、`RAIL`、`COMMUTER_TRAIN` | `TRAIN` |
| `HIGH_SPEED_TRAIN`、`LONG_DISTANCE_TRAIN` | `HSR` |
| 其他 | `BUS`（預設） |

**取值路徑**：
- 路線名稱：`step.transitDetails.transitLine.nameShort` 優先，沒有則用 `.name`
- 上車站名：`step.transitDetails.stopDetails.departureStop.name`
- 下車站名：`step.transitDetails.stopDetails.arrivalStop.name`
- 站數：`step.transitDetails.stopCount`
- `transferCount` = RIDE 步驟數 − 1（最小值 0）

### 執行步驟

| # | 步驟 | 產出物 | 驗收條件 | 卡住的降級方案 |
|---|---|---|---|---|
| 1.1 | 用 `curl` 或 Python 直接打一次 Routes API，把原始回傳存成 `fixtures/google_raw.json` | fixture 檔 | 檔案內有 `routes` 陣列 | 若回 400，讀錯誤訊息刪掉它指出的不合法 FieldMask 欄位，**不要用猜的** |
| 1.2 | 實作 `_secs()` 轉換函式 | `google_client.py` | `_secs("900s") == 900`、`_secs(None) == 0` | — |
| 1.3 | 實作 `parse_route(route: dict) -> dict`，把單一 route 攤平成 plan | 同上 | 對 fixture 執行後印出的 plan 含四個欄位 | — |
| 1.4 | 實作 `get_routes()`，加上 `computeAlternativeRoutes` 並回傳 list | 同上 | 「台北車站 → 淡水捷運站」回傳 ≥ 2 個 plan | 若只回 1 條，換一組較遠的起訖點 |
| 1.5 | **實測跨模式**：「台北車站 → 新竹高鐵站」 | `fixtures/hsr_raw.json` | `steps` 中出現 `mode` 為 `HSR` 或 `TRAIN` | 若映射不到，印出實際的 `vehicle.type` 值並補進映射表 |
| 1.6 | **實測捷運**：「台北 101 → 士林夜市」 | — | 出現 `mode` 為 `METRO` 的步驟 | 同上 |
| 1.7 | 加上 try/except，任何失敗回傳 `[]` | 同上 | 故意把 API key 改錯，函式回傳 `[]` 而不是拋例外 | — |
| 1.8 | 加 20 秒的行程內快取（同一組起訖點不重複打） | 同上 | 連續呼叫兩次，第二次不產生外部請求 | 時間不夠可跳過 |

### 完成定義

- [ ] `get_routes("台北車站", "淡水捷運站")` 回傳 ≥ 2 個 plan
- [ ] 四種 `mode` 值（BUS/METRO/TRAIN/HSR）各至少在一組實測中出現過
- [ ] 所有欄位一律存在，即使值為 0 或空字串
- [ ] API key 錯誤時回傳 `[]`，不拋例外
- [ ] `fixtures/` 內至少有兩個原始回傳存檔（改程式時不用重打 API）

### 完成後

立刻去支援 P2 的站名比對問題——那是全案最可能卡住的地方。

---

## 6. P2｜TDX 即時層

**你擁有**：`tdx_client.py`
**你禁止修改**：`main.py`、`google_client.py`、`web/`
**你的依賴**：只有 TDX 金鑰。不依賴任何隊友。

> 這條線工作量最小但**風險最高**：站名對不上是必然會遇到的問題。

### 技術規格

**認證**（OAuth2 client_credentials）：
```
POST https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token
form data: grant_type=client_credentials, client_id=..., client_secret=...
回傳: {"access_token": "...", "expires_in": 86400}
```

Token 有效期約 24 小時，**必須快取**，過期前 60 秒才重新申請。每次呼叫都重取會被限流。

**即時到站**：
```
GET https://tdx.transportdata.tw/api/basic/v2/Bus/EstimatedTimeOfArrival/City/{City}/{RouteName}
Header: authorization: Bearer {token}
Query:  $format=JSON
```

大台北要查兩個 city 並合併結果：`Taipei` 與 `NewTaipei`。

**回傳中要用的欄位**：

| 欄位 | 說明 |
|---|---|
| `StopName.Zh_tw` | 站牌中文名，用來與 Google 的站名比對 |
| `EstimateTime` | 預估到站秒數。**可能為 null**（無即時資料） |
| `StopStatus` | 0 正常／1 尚未發車／2 交管不停靠／3 末班已過／4 今日未營運 |

**`StopStatus` 對應回傳值**：

| StopStatus | 回傳 |
|---|---|
| 3 或 4 | `(None, "末班已過")` |
| 0 且 `EstimateTime` 不為 null | `(EstimateTime, "即時")` |
| 其他所有情況 | `(None, "班表推估")` |

### ★ 站名比對是本條線的核心難題

Google 說「台北車站」，TDX 可能是「臺北車站」（異體字）、「台北車站(忠孝)」（帶括號）、或「北車」。

**比對策略（依序嘗試，成功即停）**：
1. 完全相同
2. 去掉「站」字後完全相同
3. 雙向包含關係：`clean in tdx_name` 或 `tdx_name in google_name`
4. 全形轉半形、去除所有括號內容後再比一次

**★ 硬性上限：站名比對最多花 30 分鐘。** 超過就停手，接受回傳「班表推估」。這不是失敗——系統設計本來就允許降級，而 Demo 只需要找到一條對得上的路線即可。

### 執行步驟

| # | 步驟 | 產出物 | 驗收條件 | 卡住的降級方案 |
|---|---|---|---|---|
| 2.1 | 實作 token 取得與快取 | `tdx_client.py` | 連續呼叫兩次，第二次不產生 HTTP 請求 | 401 時檢查 secret 有無多餘空白 |
| 2.2 | 查一條熟悉的台北公車（例如 `307`），把原始回傳印出來 | — | 看到含 `StopName` 的陣列 | 換一條路線試 |
| 2.3 | **記錄 `EstimateTime` 為 null 的比例** | 寫在 commit message | 有一個百分比數字 | — |
| 2.4 | 實作 `StopStatus` 判斷邏輯 | 同上 | 三種回傳值都能觸發 | — |
| 2.5 | 實作站名比對（四層策略） | 同上 | 至少一組 Google 站名能對上 TDX | 見上方 30 分鐘上限 |
| 2.6 | 加 20 秒快取，key 用 `route_name` | 同上 | 連續呼叫兩次，第二次不打 TDX | — |
| 2.7 | **包上 try/except，確保永不拋例外** | 同上 | 故意把 secret 改錯，函式回傳 `(None, "班表推估")` | — |
| 2.8 | 查兩個城市（Taipei + NewTaipei）並合併 | 同上 | 新北的路線也查得到 | 時間不夠只查 Taipei |

### 完成定義

- [ ] `get_eta("307", "台北車站")` 回傳一個 tuple
- [ ] 三種來源說明（即時／班表推估／末班已過）都能產生
- [ ] **任何錯誤情境下都不拋例外**（這是最重要的一項）
- [ ] 已記錄無即時資料的路線比例（簡報要用）

### 2.3 的數字很重要

「大台北有 X% 的公車路線有即時資料」是簡報上誠實呈現系統覆蓋率的關鍵數據，也是評審會問的問題。

---

## 7. P3｜網頁前端

**你擁有**：`web/index.html`、`web/app.js`
**你禁止修改**：所有 `.py` 檔
**你的依賴**：只有 `mock.json`（P4 在第 1 小時交付）。**全程不需要後端跑起來。**

### 技術規格

原生 HTML + JavaScript，**不使用任何框架或建置工具**。用 `python -m http.server 5500` 起靜態伺服器即可。

**開發期資料來源切換**（寫在 `app.js` 最上方）：
```javascript
const USE_MOCK = true;                        // 整合時改成 false
const API_BASE = 'http://localhost:8080';
const url = USE_MOCK ? './mock.json'
          : `${API_BASE}/api/plans?origin=${encodeURIComponent(from)}&destination=${encodeURIComponent(to)}`;
```

### 畫面規格

**查詢區**：起點輸入框（預設「台北車站」）、終點輸入框（預設「淡水捷運站」）、查詢按鈕。

**`reordered` 提示條**：`reordered` 為 true 時，在列表上方顯示黃底提示：「依即時到站重新排序後，最快方案與原始建議不同」。**這是簡報的視覺重點，樣式要明顯。**

**方案卡片**（依 `plans` 順序）：
- 排名數字（1、2、3）
- 主標：`realSeconds / 60` 取整，顯示「N 分鐘」
- **「即時」徽章**：`isLive` 為 true 時顯示綠色徽章
- 副標：`轉乘 N 次 · 等待 N 分 · {waitSource}`
- 展開後顯示 RIDE 步驟：圖示 + `routeName` + `fromStop → toStop` + 分鐘數

**四種交通工具的圖示**（用 emoji 或 Unicode 即可，不要引入圖示套件）：

| mode | 建議符號 |
|---|---|
| `BUS` | 🚌 |
| `METRO` | 🚇 |
| `TRAIN` | 🚆 |
| `HSR` | 🚄 |

**等待倒數**：`waitSeconds` 不為 null 時，用 `setInterval` 每秒遞減顯示。倒數到 0 以下顯示「已過站」。

**三種狀態**：載入中（按鈕變「查詢中…」並停用）、錯誤（紅字顯示訊息）、無結果（顯示「找不到路線」）。

### 執行步驟

| # | 步驟 | 驗收條件 |
|---|---|---|
| 3.1 | 建立 `index.html` 骨架與查詢表單 | 瀏覽器看到兩個輸入框與按鈕 |
| 3.2 | 讀取 `mock.json` 並在 console 印出 plans | Console 有陣列 |
| 3.3 | 渲染方案卡片列表 | 卡片數量與 mock 資料筆數相同 |
| 3.4 | 實作四種圖示映射 | 手動改 mock 的 mode 值，圖示跟著變 |
| 3.5 | 實作「即時」徽章 | 手動改 `isLive`，徽章出現與消失 |
| 3.6 | 實作 `reordered` 提示條 | 手動改 `reordered`，黃條出現與消失 |
| 3.7 | 實作展開顯示步驟明細 | 點擊卡片展開 |
| 3.8 | 實作等待倒數 | 觀察 60 秒，數字持續遞減 |
| 3.9 | 實作載入中與錯誤狀態 | 把 URL 改成不存在的路徑，畫面顯示錯誤而非空白 |
| 3.10 | 把 `USE_MOCK` 改成 `false` 測試真實後端 | **等第 7 小時合併後再做** |

### 完成定義

- [ ] 全程不啟動後端就能操作完整介面
- [ ] 四種圖示、即時徽章、reordered 提示條、倒數、載入中、錯誤共七種狀態都有畫面
- [ ] 切換到真實後端只需改 `USE_MOCK` 一個變數

### 你是階段二的主力

階段二把這份 UI 邏輯用 Dart 再寫一次。所以**現在把渲染邏輯寫得清楚一點**，階段二會省很多時間。

---

## 8. P4｜組裝、部署與交付

**你擁有**：`main.py`、`mock.json`、`Dockerfile`、`.dockerignore`、`requirements.txt`、`check_contract.py`、簡報
**你禁止修改**：`google_client.py`、`tdx_client.py`、`web/`

> 你不寫難的邏輯，但你負責讓東西能交出去。在 24 小時的專案裡，「有人專職負責交付」比多一個人寫程式重要得多。

### ★ 第 1 小時最優先：交出 mock.json

**這是解鎖 P3 的關鍵，其他事都往後排。** 內容必須涵蓋所有邊界情況：

- 至少 3 個 plan
- 其中一個 `isLive` 為 true、一個為 false、一個 `waitSource` 為 `"末班已過"`
- `reordered` 設為 `true`
- 四種 `mode` 值至少各出現一次
- 至少一個 plan 含 WALK 步驟
- **每個 plan 的所有欄位都存在**，包括值為 null 的 `waitSeconds`

### 執行步驟

| # | 步驟 | 時間 | 驗收條件 | 卡住的降級方案 |
|---|---|---|---|---|
| 4.1 | **產出 `mock.json` 並交給 P3** | 第 1 小時 | P3 能載入並渲染 | — |
| 4.2 | 建立 `main.py` 骨架、CORS、`/healthz` | 1–2h | `uvicorn main:app --port 8080` 啟動成功 | — |
| 4.3 | 實作第 4 節的五步驟組裝邏輯 | 2–4h | 用 P1/P2 的假回傳跑通流程 | — |
| 4.4 | 實作 `asyncio.gather` 併發查詢 | 4–5h | 3 個 plan 的 ETA 併發查，不是序列 | 時間不夠改序列 |
| 4.5 | 寫 `Dockerfile` 並本機 build 成功 | 5–6h | `docker run` 起得來 | — |
| 4.6 | 撰寫簡報骨架（見下方大綱） | 6–7h | 5 頁投影片有標題 | — |
| 4.7 | **主持第 7 小時的合併** | 7–8h | 見第 9 節 | — |
| 4.8 | Cloud Run 部署 | 8–10h | `curl https://xxx.run.app/healthz` 回 `{"ok":true}` | 卡住就跳過，改用區網 IP Demo |
| 4.9 | **錄製成功操作影片** | 10–11h | 影片檔存在且能播放 | — |
| 4.10 | 完成簡報與對照數據表 | 11–12h | 有 3–5 組數據 | — |

### Dockerfile 三個必知重點

```dockerfile
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
```

1. **host 必須是 `0.0.0.0`**。用 `127.0.0.1` 會讓容器啟動成功但 Cloud Run 完全連不進來，而且錯誤訊息很不直覺。
2. **port 讀 `$PORT`**。Cloud Run 注入 8080 並期待你監聽它。
3. **`exec`** 讓 uvicorn 成為 PID 1，才收得到 SIGTERM 能優雅關閉。

### Cloud Run 部署

```bash
gcloud run deploy transit-api \
  --source . \
  --region asia-east1 \
  --allow-unauthenticated \
  --set-secrets TDX_CLIENT_ID=tdx-id:latest,TDX_CLIENT_SECRET=tdx-secret:latest,GOOGLE_MAPS_API_KEY=gmaps-key:latest
```

- 金鑰用 Secret Manager，**不要把 `.env` 打進 image**
- 冷啟動要 5–10 秒，**Demo 前先打一次 API 預熱**
- Mac M 系列若自行 build 而非用 `--source .`，必須加 `--platform linux/amd64`

### 簡報大綱（5 頁）

1. **問題**：Google 用靜態班表，不知道車現在在哪（舉一個等 15 分鐘的具體例子）
2. **做法**：Google 找候選 → TDX 補即時 → 重新排序（放第 4 節的資料流圖）
3. **系統展示**：Demo 或影片
4. **成果**：`reordered` 的對照數據表 + P2 記錄的即時資料覆蓋率
5. **限制與未來**：目前只疊第一段、只有公車有即時資料、未來可自建圖跑時間相依最短路徑

---

## 9. 第 7–8 小時：合併程序

**這是全案唯一的高風險時刻。** 因為每人只改自己的檔案，Git 衝突機率極低，但**實際欄位可能與 mock.json 有落差**（例如某欄位是 null 而不是 0）。

由 P4 主持，依序執行：

| # | 動作 | 驗收 |
|---|---|---|
| 9.1 | P1、P2 先各自合併到 main | `git merge` 無衝突 |
| 9.2 | P4 合併並移除假回傳，接上真實函式 | `uvicorn` 啟動成功 |
| 9.3 | `curl "localhost:8080/api/plans?origin=台北車站&destination=淡水捷運站"` | 回傳含 `plans` 的 JSON |
| 9.4 | **逐欄位比對真實回傳與 `mock.json`** | 欄位名稱與型別完全一致 |
| 9.5 | P3 把 `USE_MOCK` 改成 `false` 測試 | 網頁顯示真實資料 |
| 9.6 | 全員一起找出一組 `reordered` 為 true 的起訖點 | 網頁出現黃色提示條 |

### ★ 9.6 是整個專案最重要的一步

`reordered` 為 true 就是「我們贏了 Google 一次」的證據。**那組起訖點就是上台要 Demo 的那組，把它記在便條紙上。**

尋找技巧：挑**尖峰時段、以公車起始**的路線，公車班距越長越容易出現差異。

---

## 10. 階段二：Flutter Android（10–22h）

### ★ 後端完全不用改

同一個 `/api/plans`，同一份 JSON。階段二等於「照著 `app.js` 用 Dart 再寫一次 UI」。

| 項目 | 是否需改後端 | 說明 |
|---|---|---|
| CORS | **否** | Flutter 原生 App 不受 CORS 限制（那是瀏覽器機制） |
| 中文參數編碼 | **否** | Dart 的 `Uri.replace(queryParameters:)` 自動處理 |
| 回傳格式 | **否** | 同一份 JSON |
| null 欄位 | **否，但要守紀律** | 第 3 節的硬性規則已保證，Dart 欄位宣告成 `int?` |
| HTTPS | **部署層面** | Android 9+ 預設擋明文 HTTP。Cloud Run 自動有 HTTPS，所以**先部署再開始階段二** |

### 分工

| 人 | 階段二工作 |
|---|---|
| P3 | Flutter UI 主力（把 `app.js` 邏輯搬成 Dart） |
| P1 | 協助 Flutter（此時 Google 層已完成） |
| P2 | 支援站名比對、多測幾組路線 |
| P4 | 簡報、錄影、彩排 |

### 執行步驟

| # | 步驟 | 驗收條件 |
|---|---|---|
| 10.1 | `flutter create transit_app`，`pubspec.yaml` 加 `http: ^1.2.0` | `flutter run` 看到預設畫面 |
| 10.2 | `AndroidManifest.xml` 加 `<uses-permission android:name="android.permission.INTERNET"/>` | 編譯通過 |
| 10.3 | 設定 `apiBase` 為 **Cloud Run 網址**（HTTPS） | — |
| 10.4 | 實作查詢表單與 HTTP 請求 | 按下查詢後 console 印出 plans |
| 10.5 | 實作方案卡片與四種圖示 | 列表正常顯示 |
| 10.6 | 實作「即時」徽章與 `reordered` 提示條 | 兩者都會出現 |
| 10.7 | 實作 `Timer.periodic` 每秒倒數 | 數字跳動 |
| 10.8 | 實機或模擬器測試 | 完整操作一次 |

### Android 三個地雷

1. **模擬器連本機要用 `10.0.2.2`**，不是 `localhost`。（若已用 Cloud Run 網址則無此問題）
2. **`INTERNET` 權限**忘了加會直接連線失敗。
3. **明文 HTTP 被擋**：若後端還在 HTTP，要在 `AndroidManifest.xml` 的 `<application>` 加 `android:usesCleartextTraffic="true"`。**先部署 Cloud Run 就能完全避開這個坑。**

---

## 11. 風險與降級

| 風險 | 影響 | 降級方案 |
|---|---|---|
| TDX 完全接不上 | 失去即時優勢 | `get_eta` 保證回 `(None, "班表推估")`，系統照常運作，**至少有一個能跑的多模式轉乘 App** |
| 站名對不上 | 部分路線無即時 | 30 分鐘上限，接受「班表推估」，Demo 挑對得上的路線 |
| Routes API 回 400 | 後端無法運作 | 讀錯誤訊息刪掉不合法的 FieldMask 欄位，不要用猜的 |
| Cloud Run 部署失敗 | 無法遠端存取 | 用區網 IP 現場 Demo |
| 找不到 `reordered` 為 true | 沒有成果證據 | 挑尖峰時段、公車起始、班距長的路線；最差情況用 P2 記錄的覆蓋率數據代替 |
| Demo 當天網路異常 | 無法展示 | 播 4.9 錄的影片 |
| 階段二做不完 | 沒有 App | **階段一的網頁版就是完整交付物**，階段二本來就是加分項 |

---

## 12. 完成定義

### 階段一（必須達成）

- [ ] 網頁可輸入起訖點並取得 ≥ 2 個轉乘方案
- [ ] 方案涵蓋台鐵／高鐵／捷運／公車，各有對應圖示
- [ ] 至少一組查詢的 `isLive` 為 true，顯示「即時」徽章
- [ ] **找到並記下一組 `reordered` 為 true 的起訖點**
- [ ] TDX 失敗時系統仍可運作，不會崩潰
- [ ] 已錄製成功操作影片
- [ ] 簡報完成

**達成以上就可以上台。** 沒部署、沒 App 都不影響。

### 階段二（加分）

- [ ] Android App 可完成同樣的查詢流程
- [ ] 「即時」徽章與 `reordered` 提示在 App 上正常顯示
- [ ] 後端**零改動**（這件事本身就是簡報上可講的架構設計成果）

---

## 附錄：時程總表

| 時段 | P1 | P2 | P3 | P4 |
|---|---|---|---|---|
| 0–1h | 全員：申請金鑰、建骨架、開分支 | | | |
| 1–7h | Google 路線層 | TDX 即時層 | 網頁前端（對 mock） | mock.json → main.py → Dockerfile |
| 7–8h | **全員合併** | | | |
| 8–10h | 找 reordered 案例 | 修站名比對 | 接真實後端 | Cloud Run 部署 |
| 10–12h | 支援 Flutter | 多測路線 | Flutter 起手 | 錄影 + 簡報 |
| 12–18h | **全員睡覺**（隔天要上台） | | | |
| 18–22h | Flutter 收尾、修 bug、彩排 | | | |