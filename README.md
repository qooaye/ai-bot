# LINE Bot Google Sheets 整合專案

這是一個完整的 LINE Bot 專案，使用 Python Flask 開發，主要功能是將用戶的文字訊息自動儲存到 Google Sheets，並部署到 Zeabur 平台。

> 使用 AI Claude 和 Vibe Coding 技術建立的智慧聊天機器人專案

## 🚀 功能特色

- ✅ **即時文字訊息處理**：接收並立即處理用戶文字訊息
- 📊 **自動 Google Sheets 儲存**：將訊息內容、用戶資訊、時間戳記自動儲存
- 🔒 **完整的安全機制**：Webhook 簽名驗證、錯誤處理
- 📝 **詳細日誌記錄**：完整的操作日誌和錯誤追蹤
- 🏥 **健康檢查端點**：提供服務狀態監控
- ⚡ **高性能部署**：使用 Gunicorn WSGI 伺服器
- 🌐 **雲端部署就緒**：針對 Zeabur 平台優化

## 📋 Google Sheets 資料格式

每筆訊息記錄包含以下欄位：

| 欄位 | 說明 | 範例 |
|------|------|------|
| 時間戳記 | 訊息接收時間 | 2024-01-15 14:30:25 |
| 用戶ID | LINE 用戶唯一識別碼 | U1234567890abcdef |
| 用戶顯示名稱 | 用戶在 LINE 上的顯示名稱 | 張小明 |
| 訊息內容 | 用戶發送的文字內容 | 你好，這是測試訊息 |

## 🛠️ 技術架構

- **後端框架**：Flask 2.3.3
- **LINE SDK**：line-bot-sdk 3.5.0
- **Google API**：gspread 5.12.0 + google-auth 2.23.4
- **WSGI 伺服器**：Gunicorn 21.2.0
- **部署平台**：Zeabur
- **Python 版本**：3.8+

## 🚀 快速開始

### 1. 環境準備

```bash
# 複製專案
git clone https://github.com/qooaye/ai-bot.git
cd ai-bot

# 建立虛擬環境
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows

# 安裝依賴套件
pip install -r requirements.txt
```

### 2. 環境變數設定

```bash
# 複製環境變數範例檔案
cp .env.example .env

# 編輯 .env 檔案，填入實際的設定值
```

### 3. 本地測試

```bash
# 啟動開發伺服器
python app.py

# 或使用 Gunicorn
gunicorn app:app --config gunicorn.conf.py
```

### 4. 健康檢查

```bash
# 測試服務狀態
curl http://localhost:5000/health
```

## 📚 詳細設定指南

完整的設定步驟請參考 **[SETUP_GUIDE.md](./SETUP_GUIDE.md)**，包含：

- 🔧 Google API 設定步驟
- 🤖 LINE Developer Console 設定
- 🌐 Zeabur 部署指南
- 🔐 環境變數詳細說明
- 🐛 故障排除指南

## 📁 專案結構

```
ai-line-bot/
├── app.py                 # 主要應用程式檔案
├── requirements.txt       # Python 依賴套件清單
├── Procfile              # Zeabur/Heroku 啟動設定
├── gunicorn.conf.py      # Gunicorn WSGI 伺服器設定
├── zbpack.json           # Zeabur 建置設定
├── .env.example          # 環境變數範例檔案
├── SETUP_GUIDE.md        # 詳細設定指南
└── README.md             # 專案說明文件（本檔案）
```

## 🔧 主要端點

| 端點 | 方法 | 說明 |
|------|------|------|
| `/callback` | POST | LINE Bot Webhook 接收端點 |
| `/health` | GET | 健康檢查端點 |

## 📊 使用流程

1. **用戶發送文字訊息** → LINE Bot 接收
2. **系統處理訊息** → 取得用戶資訊、驗證訊息
3. **儲存到 Google Sheets** → 自動記錄時間戳記、用戶資訊、訊息內容
4. **回覆確認訊息** → 告知用戶訊息已成功儲存
5. **非文字訊息處理** → 自動忽略圖片、貼圖等，回覆提示訊息

## 🔒 安全特色

- ✅ **Webhook 簽名驗證**：確保請求來源的真實性
- ✅ **環境變數管理**：敏感資訊不硬編碼在程式中
- ✅ **Google Service Account**：使用服務帳戶進行安全的 API 存取
- ✅ **錯誤處理機制**：完整的 try-catch 錯誤處理
- ✅ **詳細日誌記錄**：所有操作都有完整的日誌追蹤

## 📈 監控和維護

### 健康檢查
```bash
curl https://your-domain.zeabur.app/health
```

### 日誌監控
- 應用程式會輸出詳細的操作日誌
- 在 Zeabur 控制台中可以即時查看日誌
- 包含錯誤追蹤和效能監控資訊

## 🤝 貢獻指南

1. Fork 此專案
2. 建立功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交變更 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 開啟 Pull Request

## 📝 授權條款

此專案採用 MIT 授權條款 - 詳見 [LICENSE](LICENSE) 檔案

## 🆘 支援

如果遇到問題，請參考：

1. **[SETUP_GUIDE.md](./SETUP_GUIDE.md)** - 詳細設定和故障排除指南
2. **專案 Issues** - 在 GitHub 上提交問題報告
3. **日誌檢查** - 查看應用程式日誌以獲取詳細錯誤資訊

---

**🎉 現在你已經準備好建立一個功能完整的 LINE Bot 了！**

馬上開始使用 **[SETUP_GUIDE.md](./SETUP_GUIDE.md)** 來完成完整的設定流程。
