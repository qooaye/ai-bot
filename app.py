from flask import Flask, request, abort, jsonify
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, AudioMessage, TextSendMessage
import os
import logging
import gspread
from google.auth.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from datetime import datetime
import json
import tempfile
import whisper
from pydub import AudioSegment
import io

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

# 本地 Whisper 模型設定
# 加載 Whisper Large v2 模型 (免費開源)
try:
    whisper_model = whisper.load_model("large-v2")
    logger.info("本地 Whisper Large v2 模型加載成功")
except Exception as e:
    logger.error(f"Whisper 模型加載失敗: {e}")
    whisper_model = None憑證

# 用戶狀態管理
user_sessions = {}
user_conversations = {}

class UserSession:
    def __init__(self, user_id):
        self.user_id = user_id
        self.is_recording = False  # 是否正在錄音模式
        self.conversation_buffer = []  # 對話緩衝區
        self.created_at = datetime.now()
    
    def start_recording(self):
        self.is_recording = True
        self.conversation_buffer = []
        logger.info(f"用戶 {self.user_id} 開始錄音模式")
    
    def stop_recording(self):
        self.is_recording = False
        logger.info(f"用戶 {self.user_id} 停止錄音模式")
    
    def add_message(self, message):
        self.conversation_buffer.append({
            'timestamp': datetime.now(),
            'content': message
        })
    
    def get_conversation_text(self):
        return '\n'.join([msg['content'] for msg in self.conversation_buffer])

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
                # 修正 Base64 padding 問題
                base64_data = GOOGLE_CREDENTIALS_BASE64
                # 確保 Base64 字串有正確的 padding
                missing_padding = len(base64_data) % 4
                if missing_padding:
                    base64_data += '=' * (4 - missing_padding)
                
                credentials_json = base64.b64decode(base64_data).decode('utf-8')
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
                # 處理私鑰格式 - 確保正確的換行符
                private_key = GOOGLE_PRIVATE_KEY.strip()
                
                # 如果私鑰沒有正確的開始和結束標記，添加它們
                if not private_key.startswith('-----BEGIN PRIVATE KEY-----'):
                    private_key = '-----BEGIN PRIVATE KEY-----\n' + private_key
                if not private_key.endswith('-----END PRIVATE KEY-----'):
                    private_key = private_key + '\n-----END PRIVATE KEY-----'
                
                # 確保私鑰格式正確
                lines = private_key.split('\n')
                formatted_lines = []
                for line in lines:
                    line = line.strip()
                    if line:
                        formatted_lines.append(line)
                
                # 重新組裝私鑰，確保每64個字符一行（除了標記行）
                formatted_key = formatted_lines[0] + '\n'  # BEGIN 行
                key_content = ''.join(formatted_lines[1:-1])  # 移除 BEGIN 和 END 行
                
                # 將密鑰內容分成64字符一行
                for i in range(0, len(key_content), 64):
                    formatted_key += key_content[i:i+64] + '\n'
                
                formatted_key += formatted_lines[-1]  # END 行
                
                # 建立服務帳戶憑證
                credentials_info = {
                    "type": "service_account",
                    "project_id": "linebot001-466022",
                    "private_key_id": "a0301f6ea64f12f2ffdbfdb0eabc0c4745858df5",
                    "private_key": formatted_key,
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
                logger.error(f"私鑰長度: {len(GOOGLE_PRIVATE_KEY) if GOOGLE_PRIVATE_KEY else 0}")
                logger.error(f"私鑰前50字符: {GOOGLE_PRIVATE_KEY[:50] if GOOGLE_PRIVATE_KEY else 'None'}")
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


def get_user_session(user_id):
    """取得或建立用戶會話"""
    if user_id not in user_sessions:
        user_sessions[user_id] = UserSession(user_id)
    return user_sessions[user_id]


def get_user_display_name(user_id):
    """取得用戶顯示名稱"""
    try:
        profile = line_bot_api.get_profile(user_id)
        return profile.display_name
    except Exception as e:
        logger.warning(f"無法取得用戶 {user_id} 的顯示名稱: {e}")
        return "未知用戶"


def split_audio_for_whisper(audio_data, chunk_size_mb=50):
    """
    將音檔分割成適合本地 Whisper 處理的大小
    本地處理可以處理更大的檔案，預設 50MB
    """
    try:
        # 將音檔載入 AudioSegment
        audio = AudioSegment.from_file(io.BytesIO(audio_data))
        
        # 估算每個 chunk 的長度（毫秒）
        file_size_mb = len(audio_data) / (1024 * 1024)
        if file_size_mb <= chunk_size_mb:
            return [audio_data]  # 檔案夠小，不需要分割
        
        # 計算需要分割的數量
        num_chunks = int(file_size_mb / chunk_size_mb) + 1
        chunk_duration = len(audio) // num_chunks
        
        chunks = []
        for i in range(num_chunks):
            start = i * chunk_duration
            end = start + chunk_duration if i < num_chunks - 1 else len(audio)
            
            chunk = audio[start:end]
            
            # 將 chunk 轉換為 bytes
            with io.BytesIO() as buffer:
                chunk.export(buffer, format="mp3")
                chunks.append(buffer.getvalue())
        
        logger.info(f"音檔分割為 {len(chunks)} 個片段")
        return chunks
        
    except Exception as e:
        logger.error(f"音檔分割失敗: {e}")
        return [audio_data]  # 分割失敗，返回原檔案


def transcribe_audio_with_local_whisper(audio_data):
    """
    使用本地 Whisper Large v2 模型轉錄音檔
    完全免費，無需 API 金鑰
    """
    try:
        if not whisper_model:
            logger.error("Whisper 模型未加載")
            return None
        
        # 分割音檔 (本地處理可以處理更大的檔案)
        audio_chunks = split_audio_for_whisper(audio_data, chunk_size_mb=50)
        
        transcriptions = []
        
        for i, chunk in enumerate(audio_chunks):
            logger.info(f"正在轉錄第 {i+1}/{len(audio_chunks)} 個音檔片段")
            
            try:
                # 建立臨時檔案
                with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_file:
                    temp_file.write(chunk)
                    temp_file_path = temp_file.name
                
                try:
                    # 使用本地 Whisper 模型轉錄
                    result = whisper_model.transcribe(
                        temp_file_path,
                        language="zh",  # 中文
                        task="transcribe",
                        fp16=False,  # 相容性更好
                        verbose=False
                    )
                    
                    transcription = result["text"].strip()
                    if transcription:
                        transcriptions.append(transcription)
                        logger.info(f"第 {i+1} 個片段轉錄成功: {transcription[:50]}...")
                    
                except Exception as e:
                    logger.error(f"第 {i+1} 個片段 Whisper 轉錄失敗: {e}")
                    continue
                
                finally:
                    # 清理臨時檔案
                    try:
                        os.unlink(temp_file_path)
                    except:
                        pass
                
            except Exception as e:
                logger.error(f"第 {i+1} 個片段處理失敗: {e}")
                continue
        
        # 合併所有轉錄結果
        full_transcription = ' '.join(transcriptions)
        logger.info(f"音檔轉錄完成，總長度: {len(full_transcription)} 字元")
        
        return full_transcription if full_transcription else None
        
    except Exception as e:
        logger.error(f"本地 Whisper 轉錄失敗: {e}")
        return None


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
        message_text = event.message.text.strip()
        
        logger.info(f"收到文字訊息 - 用戶: {user_id}, 訊息: {message_text[:100]}...")
        
        # 取得用戶會話和顯示名稱
        session = get_user_session(user_id)
        user_name = get_user_display_name(user_id)
        
        # 處理指令
        if message_text == '/save':
            session.start_recording()
            reply_text = "🎙️ 開始會議記錄模式！\n\n現在您可以：\n📝 發送文字訊息\n🎤 發送語音訊息\n\n所有內容都會累積顯示，輸入 /end 結束並儲存到 Google Sheets。"
        
        elif message_text == '/end':
            if session.is_recording and session.conversation_buffer:
                # 儲存到 Google Sheets
                conversation_text = session.get_conversation_text()
                save_success = save_message_to_sheets(user_id, user_name, conversation_text)
                
                if save_success:
                    reply_text = f"✅ 會議記錄已儲存到 Google Sheets！\n\n📄 總共記錄了 {len(session.conversation_buffer)} 條內容\n📊 總字數約 {len(conversation_text)} 字元"
                else:
                    reply_text = "❌ 儲存失敗，請稍後再試。"
                
                session.stop_recording()
            else:
                reply_text = "❌ 目前沒有進行中的會議記錄。\n\n請先輸入 /save 開始記錄模式。"
        
        elif message_text == '/status':
            if session.is_recording:
                conversation_text = session.get_conversation_text()
                reply_text = f"📊 會議記錄狀態：進行中\n\n📝 已記錄 {len(session.conversation_buffer)} 條內容\n📄 目前內容:\n\n{conversation_text[:500]}{'...' if len(conversation_text) > 500 else ''}\n\n輸入 /end 結束並儲存"
            else:
                reply_text = "📊 會議記錄狀態：未開始\n\n輸入 /save 開始記錄模式"
        
        elif message_text == '/help':
            reply_text = """📖 會議記錄小幫手使用說明：

🎙️ /save - 開始會議記錄模式
⏹️ /end - 結束記錄並儲存到 Google Sheets
📊 /status - 查看目前記錄狀態
📖 /help - 顯示此說明

💡 使用方式：
1. 輸入 /save 開始記錄
2. 發送語音或文字訊息
3. 所有內容會累積顯示
4. 輸入 /end 儲存到試算表

✨ 支援功能：
• 語音轉文字（使用本地 Whisper Large v2）
• 大音檔自動分割處理
• 即時對話累積
• Google Sheets 自動儲存"""
        
        else:
            # 一般文字訊息
            if session.is_recording:
                session.add_message(message_text)
                conversation_text = session.get_conversation_text()
                
                reply_text = f"📝 已記錄文字訊息\n\n💬 目前累積內容:\n\n{conversation_text}\n\n📊 共 {len(session.conversation_buffer)} 條記錄 | 輸入 /end 結束並儲存"
            else:
                reply_text = f"收到您的訊息：{message_text}\n\n💡 提示：輸入 /save 開始會議記錄模式，或輸入 /help 查看使用說明。"
        
        # 回覆訊息
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


@handler.add(MessageEvent, message=AudioMessage)
def handle_audio_message(event):
    """處理語音訊息事件"""
    try:
        user_id = event.source.user_id
        
        logger.info(f"收到語音訊息 - 用戶: {user_id}")
        
        # 取得用戶會話和顯示名稱
        session = get_user_session(user_id)
        user_name = get_user_display_name(user_id)
        
        if not session.is_recording:
            reply_text = "🎤 收到語音訊息！\n\n💡 提示：輸入 /save 開始會議記錄模式，語音將自動轉為文字並累積顯示。\n\n或輸入 /help 查看使用說明。"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=reply_text)
            )
            return
        
        # 下載音檔
        message_content = line_bot_api.get_message_content(event.message.id)
        audio_data = message_content.content
        
        # 先回覆處理中訊息
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="🎤 正在處理語音訊息，請稍候...\n\n⏳ 使用本地 Whisper AI 轉錄中...")
        )
        
        # 使用本地 Whisper 模型轉錄
        transcription = transcribe_audio_with_local_whisper(audio_data)
        
        if transcription:
            # 加入對話記錄
            session.add_message(f"[語音] {transcription}")
            conversation_text = session.get_conversation_text()
            
            # 推送結果訊息
            result_text = f"🎤 語音轉錄完成！\n\n📝 轉錄內容:\n{transcription}\n\n💬 目前累積內容:\n\n{conversation_text}\n\n📊 共 {len(session.conversation_buffer)} 條記錄 | 輸入 /end 結束並儲存"
        else:
            result_text = "❌ 語音轉錄失敗，請重新發送或檢查音檔格式。"
        
        # 推送結果（因為已經回覆過，這裡使用 push_message）
        line_bot_api.push_message(
            user_id,
            TextSendMessage(text=result_text)
        )
        
    except Exception as e:
        logger.error(f"處理語音訊息時發生錯誤: {e}")
        try:
            line_bot_api.push_message(
                user_id,
                TextSendMessage(text="❌ 語音處理失敗，請稍後再試。")
            )
        except:
            pass


@handler.add(MessageEvent)
def handle_other_message(event):
    """處理其他類型訊息（圖片、貼圖等）"""
    try:
        user_id = event.source.user_id
        user_name = get_user_display_name(user_id)
        
        logger.info(f"收到其他類型訊息 - 用戶: {user_name}, 訊息類型: {type(event.message).__name__}")
        
        reply_text = "📱 此會議記錄小幫手只處理文字和語音訊息。\n\n💡 支援功能：\n🎤 語音轉文字\n📝 文字記錄\n📊 Google Sheets 儲存\n\n輸入 /help 查看使用說明"
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )
        
    except Exception as e:
        logger.error(f"處理其他訊息時發生錯誤: {e}")


if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)