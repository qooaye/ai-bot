import os
import json
import base64
import logging
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv

# 設定日誌
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

SCOPES = ['https://www.googleapis.com/auth/drive']

def get_credentials_info():
    """取得用戶端的憑證資訊"""
    # 優先從 credentials.json 讀取
    if os.path.exists('credentials.json'):
        with open('credentials.json', 'r') as f:
            return json.load(f)
    
    # 次之從環境變數讀取
    b64_creds = os.getenv('GOOGLE_OAUTH_CREDENTIALS_BASE64')
    if b64_creds:
        # 修正 padding
        missing_padding = len(b64_creds) % 4
        if missing_padding:
            b64_creds += '=' * (4 - missing_padding)
        return json.loads(base64.b64decode(b64_creds).decode('utf-8'))
    
    return None

def main():
    creds_info = get_credentials_info()
    if not creds_info:
        print("❌ 錯誤：找不到憑證資訊！")
        print("請確保目錄下有 'credentials.json' 或 .env 中有 'GOOGLE_OAUTH_CREDENTIALS_BASE64'。")
        return

    # 初始化 Flow
    # 注意：Google 已停用多數 OOB 流程，建議使用 run_local_server()
    # 但為了配合您的截圖需求，我們保留手動貼上授權碼的邏輯
    flow = InstalledAppFlow.from_client_config(
        creds_info, 
        scopes=SCOPES
    )
    
    # 嘗試在本機開啟瀏覽器
    print("\n🚀 正在啟動 Google 授權流程...")
    try:
        # 優先嘗試自動開啟瀏覽器 (適合本機環境)
        creds = flow.run_local_server(port=0)
    except Exception:
        # 若本機伺服器失敗，改試 OOB 流程（手動複製貼上）
        print("💡 無法自動開啟瀏覽器，請手動複製以下網址並貼到瀏覽器：")
        flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
        auth_url, _ = flow.authorization_url(prompt='consent')
        print(f"\n🔗 網址：\n{auth_url}\n")
        code = input("⌨️ 請貼入授權碼 (Code)：").strip()
        flow.fetch_token(code=code)
        creds = flow.credentials

    # 儲存 Token 到本地檔案
    with open('token.json', 'w') as token:
        token.write(creds.to_json())
    print("\n✅ 授權成功！'token.json' 已產生。")

    # 測試連結
    try:
        service = build('drive', 'v3', credentials=creds)
        results = service.files().list(pageSize=1, fields="files(id, name)").execute()
        files = results.get('files', [])
        print(f"📡 測試成功！偵測到雲端硬碟檔案：{files[0]['name'] if files else '空資料夾'}")
    except Exception as e:
        print(f"❌ 測試失敗：{e}")

    # 同步到 Google Sheets (如果您在 app.py 使用此機制)
    print("\n🔄 正在嘗試將 Token 同步至 Google Sheets (Persistent Store)...")
    try:
        import gspread
        from google.oauth2.service_account import Credentials as ServiceAccountCredentials
        
        b64_service = os.getenv('GOOGLE_CREDENTIALS_BASE64')
        sheet_id = os.getenv('GOOGLE_SHEETS_ID')
        
        if b64_service and sheet_id:
            missing_padding = len(b64_service) % 4
            if missing_padding: b64_service += '=' * (4 - missing_padding)
            service_info = json.loads(base64.b64decode(b64_service).decode('utf-8'))
            
            s_creds = ServiceAccountCredentials.from_service_account_info(
                service_info, 
                scopes=["https://www.googleapis.com/auth/spreadsheets"]
            )
            gc = gspread.authorize(s_creds)
            ss = gc.open_by_key(sheet_id)
            try:
                ws = ss.worksheet("OAuthToken")
            except:
                ws = ss.add_worksheet(title="OAuthToken", rows=10, cols=2)
                ws.update('A1', [['TokenContent']])
            
            ws.update('A2', [[creds.to_json()]])
            print("🚀 同步成功！即便部署到 Zeabur 也不需要重新授權了。")
        else:
            print("⚠️ 略過同步：環境變數缺少 GOOGLE_CREDENTIALS_BASE64 或 GOOGLE_SHEETS_ID。")
    except Exception as e:
        print(f"⚠️ 同步失敗 (不影響本地運作)：{e}")

    print("\n🎉 全部完成！您現在可以執行 `python3 app.py` 開始使用圖片助手。")

if __name__ == '__main__':
    main()
