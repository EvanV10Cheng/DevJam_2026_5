# DevJam_2026_5
# 大台北即時轉乘系統 — 開發規格與執行流程

> **文件結構**
> - **Phase 1（第 1～6 節）**：24 小時內必須交付的可運作系統。**現在只做這個。**
> - **Phase 2（第 7～10 節）**：時間充裕時的完整架構。現在只當參考，不要動手。
>
> 每個工作項都附「產出物」與「驗收條件」，做完就能自我檢查，不需等人回覆。

---

## 0. 給 AI Agent 的執行規則

1. **只執行 Phase 1**。除非使用者明確說「進入 Phase 2」，否則不要建立第 7 節以後提到的任何檔案。
2. **不要重構、不要加抽象層**。Phase 1 刻意用單檔架構（`main.py` + `main.dart`），這是為了 24 小時期限做的取捨，不是疏漏。
3. **每步驟都要驗收**。驗收條件是可執行的指令或可觀察的現象，通過才進下一步。
4. **卡超過 30 分鐘就走降級路徑**。每個高風險步驟都寫了降級方案，走降級不算失敗。
5. **不確定時停下來問**，不要自行擴充範圍。

---

## 1. 專案目標與範圍

### 系統要做什麼

輸入起點與終點，輸出**依實際搭乘總時間排序**的轉乘方案，涵蓋大台北地區的**台鐵、高鐵、捷運、公車**。

### 核心價值主張（也是簡報唯一要講的一句話）

> Google Maps 用**靜態班表**算路線，不知道車現在在哪裡。我們用 Google 找候選、用 TDX 補**即時到站**，重新排序後最快的方案常常不是 Google 排第一的那個。

### 關鍵架構決策

**多模式轉乘不自己算。** Google Routes API 的 `TRANSIT` 模式在大台北已經涵蓋台鐵、高鐵、捷運、公車，而且轉乘組合已經算好。自己建圖跑 Dijkstra 在 24 小時內做不完，而且做出來也不會比 Google 好。

**唯一要自己做的是疊上即時資料。** 這是 Google 沒有的資訊，也是本系統存在的理由。

### 範圍界定

| Phase 1 包含 | Phase 1 不包含 |
|---|---|
| 大台北：台鐵、高鐵、捷運、公車 | 其他縣市 |
| 第一段搭乘的即時到站疊加 | 全程每一段的即時資料 |
| 依實際總時間重新排序 | 自建圖與最短路徑演算法 |
| Flutter App（方案列表） | 地圖繪製（時間充裕才加） |
| Cloud Run 部署 | Firebase、Redis、使用者帳號 |

### 已明確砍掉的項目

自建 Dijkstra、Firebase 全套、Redis、mock server、契約測試、CI、`contracts.py` 的 Pydantic 契約層、四人分工的介面隔離。**這些都是為兩週專案設計的，24 小時內全是負擔。**

---

## 2. Phase 1 系統架構

```
[Flutter App]  ← 輸入起訖點，顯示方案列表與即時徽章
      │  HTTP GET /api/plans?origin=&destination=
      ↓
[FastAPI｜單檔 main.py]
      ├─→ Google Routes API (TRANSIT, 多候選)  → 多模式轉乘骨架
      └─→ TDX 公車即時到站 (第一段)             → 真實等待時間
      ↓
   重新排序：realSeconds = Google 行程時間 + 真實等待
      ↓
[Cloud Run]  ← 最後 2 小時才部署
```

### 檔案清單（全部就這五個）

```
transit/
├── main.py              # 後端全部：Google + TDX + 排序
├── requirements.txt     # fastapi / uvicorn / httpx
├── Dockerfile           # Cloud Run 用
└── transit_app/
    └── lib/main.dart    # Flutter 全部：輸入、列表、倒數
```

### 技術選型理由

| 元件 | 選擇 | 理由 |
|---|---|---|
| 後端 | FastAPI 單檔 | 自動產生 `/docs`，前端不用問欄位；單檔省掉所有 import 路徑問題 |
| HTTP | httpx（async） | 多條候選路線要併發查 TDX，序列查會超過 10 秒 |
| 快取 | 行程內 dict | 即時資料 TTL 只有 20 秒，不值得裝 Redis |
| 前端 | Flutter 單檔 | 不引入狀態管理套件，`setState` 足夠 |
| 部署 | Cloud Run | `gcloud run deploy --source .` 一行完成 |

---

## 3. API 契約（Phase 1 簡化版）

只有一個端點。不使用 Pydantic model，直接回傳 dict，前端用 `jsonDecode` 讀。

### `GET /api/plans?origin={地址或地標}&destination={地址或地標}`

起訖點**直接傳字串**給 Google Routes API 的 `address` 欄位，不需要 Places Autocomplete，省下一大塊工。

**回傳**

| 欄位 | 說明 |
|---|---|
| `queryTime` | 查詢時刻（epoch 秒） |
| `plans` | 依 `realSeconds` 排序的方案陣列 |
| `googleOrder` | Google 原始順序的秒數，用於對照 |
| `reordered` | **布林值。true 代表我們的第一名與 Google 不同——這就是專案成功的證據** |

**plan 物件**

| 欄位 | 說明 |
|---|---|
| `totalSeconds` | Google 估的行程時間 |
| `waitSeconds` | TDX 查到的真實等待秒數，查不到為 null |
| `waitSource` | `"即時"` / `"班表推估"` / `"末班已過"` |
| `realSeconds` | `totalSeconds + waitSeconds`，**排序依據** |
| `isLive` | `waitSource == "即時"`，前端顯示徽章用 |
| `transferCount` | 轉乘次數 |
| `steps` | 步驟陣列，`type` 為 `WALK` 或 `RIDE` |

**RIDE step 的 `mode`**：`BUS` / `METRO` / `TRAIN` / `HSR`，由 Google 的 `transitLine.vehicle.type` 映射而來，前端用它決定顯示哪個圖示。

---

## 4. Phase 1 執行步驟

### 階段 0：取得金鑰（0–1h）★ 不可跳過、不可延後

| # | 步驟 | 驗收條件 |
|---|---|---|
| 0.1 | 註冊 TDX（tdx.transportdata.tw）→ 會員專區 → 建立應用程式 → 取得 client id / secret | 手上有兩串字 |
| 0.2 | Google Cloud 建專案 → 啟用 **Routes API** → 建立 API key | Console 顯示 Routes API 已啟用 |
| 0.3 | **設定 API 每日用量上限 1000 次** | Console 的配額頁面顯示上限 |
| 0.4 | 建立 `.env` 並加入 `.gitignore` | `git status` 看不到 `.env` |

> 這一小時什麼程式都不要寫。金鑰申請是唯一可能卡住而且**無法靠寫程式解決**的環節，必須最先排除。

### 階段 1：後端跑通（1–3h）

| # | 步驟 | 產出物 | 驗收條件 | 卡住的降級方案 |
|---|---|---|---|---|
| 1.1 | 放入 `main.py`、`requirements.txt`，`pip install -r requirements.txt` | — | `uvicorn main:app --port 8080` 啟動無錯誤 | — |
| 1.2 | `curl "localhost:8080/api/plans?origin=台北車站&destination=淡水捷運站"` | — | 回傳含 `plans` 的 JSON | 若回 400，讀錯誤訊息刪掉不合法的 FieldMask 欄位，**不要用猜的** |
| 1.3 | 測試跨模式路線（例如「台北車站 → 新竹高鐵站」） | — | `steps` 中出現 `mode` 為 `HSR` 或 `TRAIN` 的項目 | — |
| 1.4 | 確認 `/docs` 頁面可用 | — | 瀏覽器開得起來並可試打 | — |

### 階段 2：Flutter 接上（3–6h）

| # | 步驟 | 產出物 | 驗收條件 | 卡住的降級方案 |
|---|---|---|---|---|
| 2.1 | `flutter create transit_app`，`pubspec.yaml` 加 `http: ^1.2.0` | 專案骨架 | `flutter run` 看到預設畫面 | — |
| 2.2 | 用 `main.dart` 覆蓋 `lib/main.dart` | — | 編譯通過 | — |
| 2.3 | 設定 `apiBase`：**Android 模擬器必須用 `10.0.2.2:8080`**，iOS 模擬器用 `localhost:8080` | — | 按下查詢後列表出現方案 | 若連不上，先用瀏覽器確認後端正常，再檢查 IP |
| 2.4 | 確認四種交通工具圖示都會出現 | — | 查一組含高鐵的路線，看到鐵路圖示 | — |
| 2.5 | 確認等待秒數每秒跳動 | — | 觀察 60 秒，數字持續變化 | — |

### 階段 3：即時資料疊加（6–8h）★ 這是專案的價值所在

| # | 步驟 | 驗收條件 | 卡住的降級方案 |
|---|---|---|---|
| 3.1 | 確認 TDX token 拿得到 | 後端 log 無 401 錯誤 | 檢查 client secret 有無多餘空白 |
| 3.2 | 查一組**以公車起始**的路線 | 至少一個方案的 `isLive` 為 true，App 上出現「即時」徽章 | 見 3.3 |
| 3.3 | 站名比對失敗時（Google 說「台北車站」，TDX 說「臺北車站」或「台北車站(忠孝)」） | — | **不要花時間修比對邏輯。** 接受顯示「班表推估」，改挑一條對得上的路線做 Demo |
| 3.4 | 找出一組讓 `reordered` 為 true 的起訖點 | App 上出現黃色提示條 | 多試幾組尖峰時段、公車起始的路線 |

> **3.4 是整個專案最重要的一步。** `reordered` 為 true 就是「我們贏了 Google 一次」的證據，那組起訖點就是上台要 Demo 的那組。**把它記在便條紙上。**

### 階段 4：部署（8–10h）

| # | 步驟 | 驗收條件 | 卡住的降級方案 |
|---|---|---|---|
| 4.1 | `gcloud run deploy transit-api --source . --region asia-east1 --allow-unauthenticated` | 回傳一個 `.run.app` 網址 | 卡住就跳過整個階段 4，改用區網 IP 現場 Demo |
| 4.2 | 用 Secret Manager 設定金鑰，**不要把 `.env` 打進 image** | `curl https://xxx.run.app/healthz` 回 `{"ok":true}` | — |
| 4.3 | Flutter 的 `apiBase` 改成雲端網址 | 手機實機可查詢 | — |

**Cloud Run 三個必知差異**：
- Port 必須讀 `$PORT` 且 host 為 `0.0.0.0`，寫死 `127.0.0.1` 會啟動成功但連不進來
- 冷啟動要 5～10 秒，**Demo 前先打一次 API 預熱**
- Mac M 系列若自行 build，必須加 `--platform linux/amd64`

### 階段 5：簡報與備援（10–12h）

| # | 步驟 | 驗收條件 |
|---|---|---|
| 5.1 | **錄一段成功操作的影片**（含 `reordered` 為 true 的那組查詢） | 影片檔存在且能播放 |
| 5.2 | 製作簡報，5 頁以內 | 見下方大綱 |
| 5.3 | 記錄 3～5 組對照數據：我們的第一名 vs Google 的第一名 | 有一張數據表 |

**簡報大綱（5 頁）**
1. 問題：Google 用靜態班表，不知道車現在在哪（舉一個等 15 分鐘的例子）
2. 做法：Google 找候選 → TDX 補即時 → 重新排序（放第 2 節的架構圖）
3. 系統展示：Demo 或影片
4. 成果：`reordered` 的對照數據表
5. 限制與未來：目前只疊第一段、只有公車有即時資料、Phase 2 規劃

### 階段 6：睡覺（12–18h）★ 不可跳過

隔天要上台。

### 階段 7：加分項（18–22h）

依序加，做不完就停：
1. 修 bug、多測幾組起訖點
2. 彩排
3. 加地圖（`google_maps_flutter`）——**這是最後才做的**，因為要設定 Android 與 iOS 兩邊的原生金鑰，順利也要一小時，卡住就是三小時

---

## 5. Phase 1 風險與降級

| 風險 | 降級方案 |
|---|---|
| TDX 完全接不上 | 後端已寫成自動退回純 Google 結果，App 照常運作，徽章顯示「班表推估」。**至少有一個能跑的多模式轉乘 App** |
| 站名對不上 | 接受「班表推估」，Demo 挑對得上的路線 |
| Cloud Run 部署失敗 | 用區網 IP 現場 Demo |
| Demo 當天網路異常 | 播 5.1 錄的影片 |
| Google API 額度用完 | 階段 0.3 已設上限，若真的用完換一組 API key |

---

## 6. Phase 1 完成定義

- [ ] App 可輸入起訖點並取得至少 2 個轉乘方案
- [ ] 方案涵蓋台鐵／高鐵／捷運／公車，各有對應圖示
- [ ] 至少一組查詢的 `isLive` 為 true，顯示「即時」徽章
- [ ] 找到並記下一組 `reordered` 為 true 的起訖點
- [ ] TDX 失敗時系統仍可運作，不會整個崩潰
- [ ] 已錄製成功操作的影片
- [ ] 簡報完成

**達成以上就可以上台。** 沒部署、沒地圖都不影響。

---

---

# Phase 2：完整架構（時間充裕時才做）

> 以下內容在 Phase 1 完成前**不要動手**。這裡保留完整設計是為了讓簡報的「未來規劃」有東西可講。

## 7. 為什麼 Phase 2 要自己建圖

Phase 1 直接用 Google 的候選路線，代表演算法只能在 3 條成品之間「挑一個」，沒有優化空間。

Phase 2 的做法是把 Google 的路線**拆回零件**：每一段「從某站搭某條線到某站」變成圖上的一條邊，再向 TDX 查詢「同一段路還有哪些其他路線也能走」，補成一張小型子圖。這樣才能搜尋出 **Google 沒想到的組合**——例如「Google 建議搭 307，但同一段路的藍 7 下一班馬上到」。

### 資料流

```
[Google Routes] [TDX]
        └───┬───┘
            ↓
   B 資料層：串接、ID 對齊、正規化、快取
            ↓ ① CandidateNetwork（圖）
   C 演算法：建子圖、時間相依 Dijkstra、評分
            ↓ ② PlanResponse（圖上的路徑）
   A 前端：Flutter
```

### 契約設計要點

契約定義在 `contracts.py`（Pydantic），Python 內部 `snake_case`、JSON 輸出 `camelCase`，所有 model 設 `extra="forbid"`。

**Leg 的 `upcomingDepartures` 必須是陣列，不能用單一 `etaSeconds`。** 等待時間會隨「你幾點抵達這一站」改變：第一段搭完到站是 14:20，第二段要等多久取決於 14:20 之後下一班幾點來。若只給純量，第二段以後的等待就無法計算，時間相依最短路會退化成假的。

**`reliability` 由 TDX 的 `StopStatus` 推導**：0＋有車輛回報 → 0.9；0＋僅班表 → 0.5；1 尚未發車 → 0.4；2 交管 → 0.3；3／4 末班已過或未營運 → **不要輸出這條 leg**。

**Step 要做成依 `type` 的聯合型別**，WAIT 必須獨立於 RIDE：RIDE 是地圖上一條線，WAIT 是倒數計時器，而且只有 WAIT 需要輪詢更新。分開後前端元件與 step 型別一對一對應。

## 8. 演算法：時間相依最短路徑

核心差異：**一般 Dijkstra 的邊成本是常數，這裡的等待成本是「抵達時刻」的函數。**

```
edge_cost(leg, arrive_at, is_transfer):
    depart = 第一個 >= arrive_at 的 upcomingDepartures   # bisect 二分搜尋
    若不存在或 reliability == 0 → 無限大

    cost = (depart - arrive_at) + leg.rideSeconds
    cost += (1 - reliability) * RELIABILITY_WEIGHT
    cost += TRANSFER_PENALTY 若 is_transfer
    回傳 (cost, depart + rideSeconds)
```

搜尋狀態必須是 `(累積成本, 實際時刻, 站點, 上一條路線, 路徑)`。**「上一條路線」必須進入狀態**，否則無法判斷下一步算不算轉乘。

三個必做的補充：**步行轉乘邊**（不同站點距離 < 400 公尺則建邊，時間 = 距離 ÷ 1.2 公尺/秒）、**方案去重**（路線序列相同者只留最佳一條，否則使用者看到三個一樣的方案）、**權重調校**（用真實案例試不同的 `TRANSFER_PENALTY`）。

## 9. Firebase 的取捨

| 服務 | 判斷 |
|---|---|
| FCM 到站推播 | **值得做**。手機版才有的功能。**推播前要重新查一次 TDX**，否則跟鬧鐘沒兩樣 |
| Remote Config 調演算法權重 | **值得做**。Demo 當場可調，不用重新部署 |
| Auth 匿名登入、Firestore 收藏 | 可以，但講不出亮點 |
| Firestore 當即時資料快取 | **不要**。TTL 只有 20 秒，寫進去馬上過期，還按讀寫計費 |
| Cloud Functions 包後端 | **不要**。無狀態導致每次冷啟動都要重取 token、快取全空。Cloud Run 才對 |

## 10. Phase 2 分工與時程

四條線可平行，前提是 **Day 0 先凍結契約、並交付 mock server**——A 與 C 對 mock 開發，完全不必等 B。

| 線 | 負責 |
|---|---|
| A | Flutter：地圖、方案卡、倒數、FCM 接收 |
| B | 資料層：TDX／Google 串接、**ID 對齊**、快取、Cloud Run 部署 |
| C | 演算法：建子圖、時間相依 Dijkstra、去重與調參 |
| D | Firebase 設定、mock server、契約測試、CI、對照實驗、簡報 |

**B 的 ID 對齊是最容易低估的工作**：Google 回傳的是給人看的字串（`"307"`、`"藍7"`），TDX 用內部 UID，兩者不會自動對上。三層降級：名稱正規化完全比對 → 起訖站座標距離＋模糊比對 → 仍失敗則保留 Google 靜態估算並把 reliability 設 0.3。

**跨語言契約同步**：從 FastAPI 的 `/openapi.json` 自動生成 Dart 型別，寫進 CI。後端欄位一改，Flutter 編譯不過——這比人工同步兩份定義可靠得多。
