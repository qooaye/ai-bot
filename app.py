from flask import Flask, request, abort, jsonify
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
import logging
import gspread
from google.auth.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from datetime import datetime
import json

# 設定日誌記錄
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Line Bot 設定
try:
    line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))
    handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))
    logger.info("Line Bot API 初始化成功")
except Exception as e:
    logger.error(f"Line Bot API 初始化失敗: {e}")
    raise

# Google Sheets 設定
GOOGLE_SHEETS_ID = os.getenv('GOOGLE_SHEETS_ID')
GOOGLE_CREDENTIALS_BASE64 = os.getenv('GOOGLE_CREDENTIALS_BASE64')
GOOGLE_SERVICE_ACCOUNT_EMAIL = os.getenv('GOOGLE_SERVICE_ACCOUNT_EMAIL')
GOOGLE_PRIVATE_KEY = os.getenv('GOOGLE_PRIVATE_KEY', '').replace('\\n', '\n')

def initialize_google_sheets():
    """初始化 Google Sheets 連接 - 支援多種憑證設定方式"""
    try:
        if not GOOGLE_SHEETS_ID:
            logger.error("缺少 GOOGLE_SHEETS_ID 環境變數")
            return None
        
        credentials = None
        
        # 方法1: 使用 Base64 編碼的完整憑證檔案（推薦）
        if GOOGLE_CREDENTIALS_BASE64:
            try:
                import base64
                credentials_json = base64.b64decode(GOOGLE_CREDENTIALS_BASE64).decode('utf-8')
                credentials_info = json.loads(credentials_json)
                
                credentials = ServiceAccountCredentials.from_service_account_info(
                    credentials_info,
                    scopes=[
                        "https://www.googleapis.com/auth/spreadsheets",
                        "https://www.googleapis.com/auth/drive"
                    ]
                )
                logger.info("使用 Base64 憑證初始化 Google Sheets 連接成功")
                
            except Exception as e:
                logger.error(f"Base64 憑證解析失敗: {e}")
                credentials = None
        
        # 方法2: 使用分離的環境變數（備用方法）
        if not credentials and GOOGLE_SERVICE_ACCOUNT_EMAIL and GOOGLE_PRIVATE_KEY:
            try:
                # 建立服務帳戶憑證
                credentials_info = {
                    "type": "service_account",
                    "project_id": "linebot001-466022",
                    "private_key_id": "a0301f6ea64f12f2ffdbfdb0eabc0c4745858df5",
                    "private_key": GOOGLE_PRIVATE_KEY,
                    "client_email": GOOGLE_SERVICE_ACCOUNT_EMAIL,
                    "client_id": "113724152426372985072",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                    "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{GOOGLE_SERVICE_ACCOUNT_EMAIL.replace('@', '%40')}",
                    "universe_domain": "googleapis.com"
                }
                
                credentials = ServiceAccountCredentials.from_service_account_info(
                    credentials_info,
                    scopes=[
                        "https://www.googleapis.com/auth/spreadsheets",
                        "https://www.googleapis.com/auth/drive"
                    ]
                )
                logger.info("使用分離環境變數初始化 Google Sheets 連接成功")
                
            except Exception as e:
                logger.error(f"分離環境變數憑證初始化失敗: {e}")
                credentials = None
        
        if not credentials:
            logger.error("無法建立 Google Sheets 憑證 - 請檢查環境變數設定")
            return None
        
        client = gspread.authorize(credentials)
        logger.info("Google Sheets 連接初始化成功")
        return client
        
    except Exception as e:
        logger.error(f"Google Sheets 初始化失敗: {e}")
        return None


def get_user_display_name(user_id):
    """取得用戶顯示名稱"""
    try:
        profile = line_bot_api.get_profile(user_id)
        return profile.display_name
    except Exception as e:
        logger.warning(f"無法取得用戶 {user_id} 的顯示名稱: {e}")
        return "未知用戶"


def save_message_to_sheets(user_id, user_name, message_text):
    """儲存訊息到 Google Sheets"""
    try:
        client = initialize_google_sheets()
        if not client:
            logger.error("無法連接 Google Sheets")
            return False
        
        # 開啟指定的試算表
        try:
            spreadsheet = client.open_by_key(GOOGLE_SHEETS_ID)
            sheet = spreadsheet.sheet1
        except gspread.SpreadsheetNotFound:
            logger.error(f"找不到 Google Sheets ID: {GOOGLE_SHEETS_ID}")
            return False
        except Exception as e:
            logger.error(f"開啟 Google Sheets 失敗: {e}")
            return False
        
        # 檢查是否有標題列，如果沒有則建立
        try:
            header = sheet.row_values(1)
            if not header or len(header) < 4:
                sheet.clear()
                sheet.append_row(["時間戳記", "用戶ID", "用戶顯示名稱", "訊息內容"])
                logger.info("建立 Google Sheets 標題列")
        except Exception as e:
            logger.warning(f"檢查標題列時發生錯誤: {e}")
        
        # 新增記錄
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row([timestamp, user_id, user_name, message_text])
        
        logger.info(f"成功儲存訊息到 Google Sheets - 用戶: {user_name}, 訊息: {message_text[:50]}...")
        return True
        
    except Exception as e:
        logger.error(f"儲存到 Google Sheets 失敗: {e}")
        return False


@app.route("/health", methods=['GET'])
def health_check():
    """健康檢查端點"""
    try:
        # 檢查 Google Sheets 連接
        client = initialize_google_sheets()
        sheets_status = "ok" if client else "error"
        
        return jsonify({
            "status": "healthy",
            "google_sheets": sheets_status,
            "timestamp": datetime.now().isoformat()
        }), 200
    except Exception as e:
        logger.error(f"健康檢查失敗: {e}")
        return jsonify({
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500


@app.route("/callback", methods=['POST'])
def callback():
    """LINE Bot webhook callback"""
    try:
        signature = request.headers.get('X-Line-Signature', '')
        body = request.get_data(as_text=True)
        
        if not signature:
            logger.warning("缺少 X-Line-Signature header")
            abort(400)
        
        logger.info(f"收到 webhook 請求，body 長度: {len(body)}")
        
        handler.handle(body, signature)
        return 'OK'
        
    except InvalidSignatureError:
        logger.error("無效的簽名驗證")
        abort(400)
    except Exception as e:
        logger.error(f"處理 webhook 時發生錯誤: {e}")
        abort(500)


@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    """處理文字訊息事件"""
    try:
        user_id = event.source.user_id
        message_text = event.message.text
        
        logger.info(f"收到文字訊息 - 用戶: {user_id}, 訊息: {message_text[:100]}...")
        
        # 取得用戶顯示名稱
        user_name = get_user_display_name(user_id)
        
        # 立即儲存訊息到 Google Sheets
        save_success = save_message_to_sheets(user_id, user_name, message_text)
        
        if save_success:
            reply_text = "✅ 您的訊息已成功儲存到 Google Sheets！"
            logger.info(f"成功處理用戶 {user_name} 的訊息")
        else:
            reply_text = "❌ 抱歉，訊息儲存失敗，請稍後再試。"
            logger.error(f"儲存用戶 {user_name} 的訊息失敗")
        
        # 回覆確認訊息
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )
        
    except Exception as e:
        logger.error(f"處理文字訊息時發生錯誤: {e}")
        try:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="❌ 系統發生錯誤，請稍後再試。")
            )
        except:
            pass


@handler.add(MessageEvent)
def handle_other_message(event):
    """處理非文字訊息（圖片、貼圖等）"""
    try:
        user_id = event.source.user_id
        user_name = get_user_display_name(user_id)
        
        logger.info(f"收到非文字訊息 - 用戶: {user_name}, 訊息類型: {type(event.message).__name__}")
        
        # 忽略非文字訊息，只回覆提示
        reply_text = "📝 此 Bot 只處理文字訊息，其他類型的訊息將被忽略。"
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )
        
    except Exception as e:
        logger.error(f"處理非文字訊息時發生錯誤: {e}")


if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)