# LINE Bot Google Sheets 整合專案設定指南

## 專案概述

這是一個完整的 LINE Bot 專案，使用 Python Flask 開發，主要功能是將用戶的文字訊息自動儲存到 Google Sheets，並部署到 Zeabur 平台。

### 核心功能
- ✅ 接收用戶文字訊息
- ✅ 自動儲存到 Google Sheets（時間戳記、用戶ID、用戶名稱、訊息內容）
- ✅ 回覆確認訊息給用戶
- ✅ 忽略非文字訊息（圖片、貼圖等）
- ✅ 完整的錯誤處理和日誌記錄
- ✅ 健康檢查端點
- ✅ Webhook 簽名驗證

## 1. Google API 設定步驟

### 1.1 建立 Google Cloud 專案

1. 前往 [Google Cloud Console](https://console.cloud.google.com/)
2. 點擊「新增專案」或選擇現有專案
3. 記下專案 ID

### 1.2 啟用必要的 API

1. 在 Google Cloud Console 中，前往「API 和服務」>「程式庫」
2. 搜尋並啟用以下 API：
   - Google Sheets API
   - Google Drive API

### 1.3 建立服務帳戶

1. 前往「API 和服務」>「憑證」
2. 點擊「建立憑證」>「服務帳戶」
3. 填入服務帳戶詳細資料：
   - 服務帳戶名稱：例如 `linebot-sheets-service`
   - 服務帳戶 ID：會自動產生
   - 服務帳戶說明：例如 `LINE Bot Google Sheets 整合服務`
4. 點擊「建立並繼續」
5. 授予角色（可選）：可以跳過此步驟
6. 點擊「完成」

### 1.4 建立服務帳戶金鑰

1. 在憑證頁面找到剛建立的服務帳戶
2. 點擊服務帳戶電子郵件地址
3. 前往「金鑰」分頁
4. 點擊「新增金鑰」>「建立新金鑰」
5. 選擇「JSON」格式
6. 點擊「建立」，會自動下載 JSON 檔案
7. **重要：保存這個檔案，記錄其中的 `client_email` 和 `private_key` 資訊**

### 1.5 建立 Google Sheets 試算表

1. 前往 [Google Sheets](https://sheets.google.com/)
2. 建立新的試算表
3. 從網址列複製試算表 ID（例如：`1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms`）
4. 點擊「共用」按鈕
5. 將剛才建立的服務帳戶電子郵件地址加入共用清單，權限設為「編輯者」

## 2. LINE Developer Console 設定步驟

### 2.1 建立 LINE Bot

1. 前往 [LINE Developers Console](https://developers.line.biz/console/)
2. 使用 LINE 帳號登入
3. 建立新的 Provider（如果還沒有）
4. 點擊「Create a new channel」
5. 選擇「Messaging API」
6. 填入 Channel 資訊：
   - Channel name：你的 Bot 名稱
   - Channel description：Bot 描述
   - Category：選擇適當的類別
   - Subcategory：選擇適當的子類別
7. 同意條款並建立

### 2.2 取得 Channel Access Token 和 Channel Secret

1. 在 Channel 設定頁面，前往「Basic settings」分頁
2. 複製 **Channel secret**
3. 前往「Messaging API」分頁
4. 在「Channel access token」區域，點擊「Issue」產生 token
5. 複製 **Channel access token**

### 2.3 設定 Webhook

1. 在「Messaging API」分頁中
2. 啟用「Use webhook」
3. 在「Webhook URL」欄位輸入：`https://your-zeabur-domain.zeabur.app/callback`
   （部署完成後再更新此 URL）
4. 啟用「Verify webhook」進行測試（部署完成後）

### 2.4 其他重要設定

1. 關閉「Auto-reply messages」（自動回覆訊息）
2. 關閉「Greeting messages」（歡迎訊息）
3. 啟用「Webhooks」

## 3. 環境變數設定說明

### 3.1 本地開發環境

1. 複製 `.env.example` 為 `.env`：
```bash
cp .env.example .env
```

2. 編輯 `.env` 檔案，填入以下資訊：

```env
# LINE Bot 設定
CHANNEL_ACCESS_TOKEN=你的_channel_access_token
CHANNEL_SECRET=你的_channel_secret

# Google Sheets 設定
GOOGLE_SHEETS_ID=你的_google_sheets_id
GOOGLE_SERVICE_ACCOUNT_EMAIL=your-service-account@your-project.iam.gserviceaccount.com
GOOGLE_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC...
...你的完整私鑰內容...
-----END PRIVATE KEY-----"

# 伺服器設定
PORT=5000
```

### 3.2 重要注意事項：Google Private Key 處理

**Google Private Key 的格式非常重要**，必須正確處理換行符：

1. **正確格式**：私鑰應該包含 `\n` 來表示換行
2. **在環境變數中**：整個私鑰用雙引號包圍
3. **實際的私鑰內容**：從下載的 JSON 檔案中複製完整的 `private_key` 值

範例：
```json
{
  "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC...\n...更多內容...\n-----END PRIVATE KEY-----\n"
}
```

## 4. Zeabur 部署步驟

### 4.1 準備程式碼

1. 確保所有檔案都已正確設定：
   - `app.py`（主程式）
   - `requirements.txt`（依賴套件）
   - `Procfile`（啟動指令）
   - `gunicorn.conf.py`（WSGI 設定）
   - `zbpack.json`（Zeabur 建置設定）

### 4.2 部署到 Zeabur

1. 前往 [Zeabur](https://zeabur.com/)
2. 使用 GitHub 帳號登入
3. 建立新的專案
4. 連接你的 GitHub repository
5. 選擇要部署的分支（通常是 `main` 或 `master`）

### 4.3 設定環境變數

在 Zeabur 專案設定中新增以下環境變數：

```
CHANNEL_ACCESS_TOKEN=你的_channel_access_token
CHANNEL_SECRET=你的_channel_secret
GOOGLE_SHEETS_ID=你的_google_sheets_id
GOOGLE_SERVICE_ACCOUNT_EMAIL=your-service-account@your-project.iam.gserviceaccount.com
GOOGLE_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC...\n...你的完整私鑰內容...\n-----END PRIVATE KEY-----"
```

### 4.4 部署完成後的設定

1. 記錄 Zeabur 提供的域名（例如：`your-app.zeabur.app`）
2. 回到 LINE Developers Console
3. 更新 Webhook URL：`https://your-app.zeabur.app/callback`
4. 測試 Webhook 連接

## 5. 本地開發測試步驟

### 5.1 環境準備

```bash
# 建立虛擬環境
python3 -m venv venv

# 啟動虛擬環境
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows

# 安裝依賴套件
pip install -r requirements.txt
```

### 5.2 設定環境變數

```bash
# 載入環境變數
export $(cat .env | xargs)

# 或使用 python-dotenv（已包含在程式中）
```

### 5.3 本地測試

```bash
# 啟動開發伺服器
python app.py

# 或使用 gunicorn
gunicorn app:app --config gunicorn.conf.py
```

### 5.4 健康檢查

```bash
# 測試健康檢查端點
curl http://localhost:5000/health
```

### 5.5 使用 ngrok 進行本地 Webhook 測試

```bash
# 安裝 ngrok
# 然後執行
ngrok http 5000

# 複製 ngrok 提供的 HTTPS URL
# 在 LINE Developers Console 中設定 Webhook URL：
# https://your-ngrok-url.ngrok.io/callback
```

## 6. 故障排除指南

### 6.1 常見問題

#### 問題：Google Sheets 連接失敗

**可能原因和解決方法：**

1. **服務帳戶權限不足**
   - 確認服務帳戶已加入 Google Sheets 的共用清單
   - 權限設定為「編輯者」

2. **私鑰格式錯誤**
   - 檢查 `GOOGLE_PRIVATE_KEY` 環境變數格式
   - 確保包含完整的 `-----BEGIN PRIVATE KEY-----` 和 `-----END PRIVATE KEY-----`
   - 檢查換行符是否正確（應該是 `\n`）

3. **環境變數缺失**
   - 確認所有必要的環境變數都已設定
   - 檢查變數名稱是否正確

#### 問題：LINE Bot 無法接收訊息

**可能原因和解決方法：**

1. **Webhook URL 設定錯誤**
   - 確認 URL 格式：`https://your-domain/callback`
   - 確認 URL 可以從外部存取

2. **Channel Access Token 或 Secret 錯誤**
   - 重新檢查並複製正確的 token 和 secret
   - 確認沒有多餘的空格或字元

3. **簽名驗證失敗**
   - 檢查 `CHANNEL_SECRET` 是否正確
   - 確認請求來源是 LINE 平台

#### 問題：部署到 Zeabur 後無法正常運作

**可能原因和解決方法：**

1. **環境變數設定問題**
   - 確認所有環境變數都已在 Zeabur 中正確設定
   - 特別注意私鑰的換行符處理

2. **PORT 設定問題**
   - 確認程式使用 `os.environ.get('PORT', 5000)`
   - Zeabur 會自動設定 PORT 環境變數

3. **依賴套件問題**
   - 檢查 `requirements.txt` 是否包含所有必要套件
   - 確認套件版本相容性

### 6.2 偵錯步驟

1. **檢查日誌**
   ```bash
   # 本地開發
   python app.py
   
   # 在 Zeabur 中查看應用程式日誌
   ```

2. **測試健康檢查端點**
   ```bash
   curl https://your-domain/health
   ```

3. **測試 Google Sheets 連接**
   - 確認可以手動在試算表中新增資料
   - 檢查服務帳戶權限

4. **測試 LINE Webhook**
   - 在 LINE Developers Console 中使用「Verify webhook」功能
   - 檢查回應狀態碼和訊息

### 6.3 監控和維護

1. **定期檢查日誌**
   - 監控錯誤訊息和異常狀況
   - 注意 API 使用量和配額

2. **備份重要資料**
   - 定期備份 Google Sheets 資料
   - 保存環境變數設定

3. **更新依賴套件**
   - 定期檢查套件更新
   - 測試相容性

## 7. 專案結構說明

```
ai-line-bot/
├── app.py                 # 主要應用程式檔案
├── requirements.txt       # Python 依賴套件清單
├── Procfile              # Zeabur/Heroku 啟動設定
├── gunicorn.conf.py      # Gunicorn WSGI 伺服器設定
├── zbpack.json           # Zeabur 建置設定
├── .env.example          # 環境變數範例檔案
├── .env                  # 實際環境變數檔案（不應提交到版本控制）
├── SETUP_GUIDE.md        # 詳細設定指南（本檔案）
└── README.md             # 專案說明文件
```

## 8. 安全注意事項

1. **永不提交敏感資訊**
   - `.env` 檔案應加入 `.gitignore`
   - 服務帳戶私鑰不應出現在程式碼中

2. **定期更新憑證**
   - 定期輪換 API 金鑰和 token
   - 監控異常存取

3. **存取控制**
   - 限制服務帳戶權限
   - 定期檢查 Google Sheets 共用設定

## 9. 性能優化建議

1. **快取機制**
   - 考慮實作 Google Sheets 連接快取
   - 減少重複的 API 呼叫

2. **錯誤重試**
   - 實作指數退避重試機制
   - 處理暫時性網路錯誤

3. **監控和告警**
   - 設定應用程式監控
   - 建立錯誤告警機制

---

如果在設定過程中遇到任何問題，請檢查日誌輸出並參考故障排除指南。如需進一步協助，請檢查相關 API 文件或聯絡技術支援。