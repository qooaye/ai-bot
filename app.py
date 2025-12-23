from flask import Flask, request, abort, jsonify
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, AudioMessage, ImageMessage, TextSendMessage
import os
import logging
from dotenv import load_dotenv

# 設定日誌記錄
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 載入環境變數
load_dotenv()

import gspread
from google.auth.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from datetime import datetime
import json
import tempfile
from openai import OpenAI
from groq import Groq
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import base64
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as UserCredentials

try:
    import whisper
    import torch
    HAS_LOCAL_WHISPER = True
except ImportError:
    HAS_LOCAL_WHISPER = False
    # 這裡現在可以使用 logger 了
    logger.warning("未偵測到本地 Whisper 或 Torch，將僅使用 OpenAI/Groq API 進行轉錄")

from pydub import AudioSegment
import io

# 修正 google-api-python-client 在 Python 3.9 下的相容性問題
try:
    from importlib import metadata
except ImportError:
    import importlib_metadata as metadata

if not hasattr(metadata, 'packages_distributions'):
    import importlib_metadata
    metadata.packages_distributions = importlib_metadata.packages_distributions

app = Flask(__name__)

# Line Bot 設定
line_bot_api = None
handler = None

try:
    line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))
    handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))
    logger.info("Line Bot API 初始化成功")
except Exception as e:
    logger.error(f"Line Bot API 初始化失敗: {e}")
    logger.warning("應用程式將在沒有 LINE Bot 功能的情況下啟動")

# OpenAI 客戶端初始化
openai_client = None
if os.getenv('OPENAI_API_KEY'):
    try:
        openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        logger.info("OpenAI 客戶端初始化成功")
    except Exception as e:
        logger.error(f"OpenAI 客戶端初始化失敗: {e}")

# Groq 客戶端初始化
groq_client = None
if os.getenv('GROQ_API_KEY'):
    try:
        groq_client = Groq(api_key=os.getenv('GROQ_API_KEY'))
        logger.info("Groq 客戶端初始化成功")
    except Exception as e:
        logger.error(f"Groq 客戶端初始化失敗: {e}")
else:
    logger.warning("未偵測到 GROQ_API_KEY，將無法使用 Groq Whisper API")

# 本地 Whisper 模型設定 (自動選擇適合的模型大小)
# 優先使用小模型以適應雲端部署環境
whisper_model = None
WHISPER_MODEL_SIZE = os.getenv('WHISPER_MODEL_SIZE', 'tiny')  # 預設使用 tiny 模型(適合雲端部署)

def load_whisper_model():
    """延遲加載 Whisper 模型以優化啟動時間"""
    global whisper_model
    
    if not HAS_LOCAL_WHISPER:
        logger.error("系統未安裝本地 Whisper 套件，無法加載模型")
        return None

    if whisper_model is not None:
        return whisper_model
    
    try:
        logger.info(f"正在加載 Whisper {WHISPER_MODEL_SIZE} 模型...")
        whisper_model = whisper.load_model(WHISPER_MODEL_SIZE)
        logger.info(f"Whisper {WHISPER_MODEL_SIZE} 模型加載成功")
        return whisper_model
    except Exception as e:
        logger.error(f"Whisper 模型加載失敗: {e}")
        try:
            logger.info("嘗試加載 tiny 模型作為備用...")
            whisper_model = whisper.load_model("tiny")
            logger.info("Whisper tiny 模型加載成功")
            return whisper_model
        except Exception as e2:
            logger.error(f"備用模型也加載失敗: {e2}")
            whisper_model = None
            return None

# 在應用啟動時不立即加載模型，等到需要時再加載
logger.info("應用啟動成功，將在首次語音轉錄時加載 Whisper 模型")

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

def save_token_to_sheets(token_json):
    """將 OAuth Token 存入 Google Sheets 以便跨部署維持登入"""
    try:
        client = initialize_google_sheets()
        if not client: return
        
        spreadsheet = client.open_by_key(os.getenv('GOOGLE_SHEETS_ID'))
        try:
            worksheet = spreadsheet.worksheet("OAuthToken")
        except gspread.exceptions.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(title="OAuthToken", rows=10, cols=2)
            worksheet.update('A1', [['TokenContent']])
            
        worksheet.update('A2', [[json.dumps(token_json)]])
        logger.info("OAuth Token 已成功存入 Google Sheets")
    except Exception as e:
        logger.error(f"儲存 Token 至 Google Sheets 失敗: {e}")

def load_token_from_sheets():
    """從 Google Sheets 讀取 OAuth Token"""
    try:
        client = initialize_google_sheets()
        if not client: return None
        
        spreadsheet = client.open_by_key(os.getenv('GOOGLE_SHEETS_ID'))
        try:
            worksheet = spreadsheet.worksheet("OAuthToken")
            val = worksheet.acell('A2').value
            if val:
                return json.loads(val)
        except Exception:
            pass
        return None
    except Exception as e:
        logger.error(f"從 Google Sheets 讀取 Token 失敗: {e}")
        return None

def get_google_drive_service():
    """獲取 Google Drive 服務 (使用 OAuth 2.0)"""
    scopes = ["https://www.googleapis.com/auth/drive"]
    creds = None
    
    # 1. 優先嘗試讀取本地 token.json (適合本機測試)
    if os.path.exists('token.json'):
        try:
            creds = UserCredentials.from_authorized_user_file('token.json', scopes)
            logger.info("已從本地 token.json 載入憑證")
        except Exception as e:
            logger.error(f"從本地 token.json 載入失敗: {e}")

    # 2. 嘗試從單獨的環境變數讀取 (轉移自截圖中的設定)
    if not creds or not creds.valid:
        refresh_token = os.getenv('GOOGLE_REFRESH_TOKEN')
        client_id = os.getenv('GOOGLE_CLIENT_ID')
        client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
        
        if refresh_token and client_id and client_secret:
            try:
                creds = UserCredentials(
                    token=None,
                    refresh_token=refresh_token,
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=client_id,
                    client_secret=client_secret,
                    scopes=scopes
                )
                logger.info("已從單獨環境變數載入憑證")
            except Exception as e:
                logger.error(f"從單獨環境變數載入失敗: {e}")

    # 3. 從 Google Sheets 讀取 (適合雲端部署持久化)
    if not creds or not creds.valid:
        token_info = load_token_from_sheets()
        if token_info:
            creds = UserCredentials.from_authorized_user_info(token_info, scopes)
            logger.info("已從 Google Sheets 載入憑證")
        
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                save_token_to_sheets(json.loads(creds.to_json()))
                if os.access('.', os.W_OK): # 如果環境允許寫入，更新本地檔
                    with open('token.json', 'w') as token:
                        token.write(creds.to_json())
            except Exception as e:
                logger.error(f"Token 刷新失敗: {e}")
                creds = None
        else:
            logger.warning("需要 Google Drive 重新授權")
            return "NEEDS_AUTH"
            
    if creds:
        return build('drive', 'v3', credentials=creds, static_discovery=False)
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


def transcribe_audio_with_groq(audio_data):
    """
    使用 Groq Whisper API 轉錄音檔
    速度極快，目前提供免費額度
    """
    if not groq_client:
        logger.error("Groq 客戶端未初始化，無法使用 Groq 轉錄")
        return None

    try:
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_file:
            temp_file.write(audio_data)
            temp_file_path = temp_file.name
        
        try:
            with open(temp_file_path, "rb") as audio_file:
                # 使用 whisper-large-v3 模型
                transcription = groq_client.audio.transcriptions.create(
                    model="whisper-large-v3", 
                    file=audio_file,
                    language="zh",  # 指定中文
                    response_format="text"
                )
            
            result_text = transcription.strip()
            logger.info(f"Groq 轉錄成功: {result_text[:50]}...")
            return result_text
            
        except Exception as e:
            logger.error(f"Groq API 呼叫失敗: {e}")
            return None
        finally:
            try:
                os.unlink(temp_file_path)
            except:
                pass
                
    except Exception as e:
        logger.error(f"Groq 轉錄過程發生錯誤: {e}")
        return None


def transcribe_audio_with_openai(audio_data):
    """
    使用 OpenAI Whisper API 轉錄音檔
    準確度極高，支援多種語言
    """
    if not openai_client:
        logger.error("OpenAI 客戶端未初始化，無法使用線上轉錄")
        return None

    try:
        # OpenAI API 對單個檔案有限制（25MB），但 LINE 語音訊息通常很小
        # 如果需要處理超大檔案，這裡可以再加入分割邏輯
        
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_file:
            temp_file.write(audio_data)
            temp_file_path = temp_file.name
        
        try:
            with open(temp_file_path, "rb") as audio_file:
                transcription = openai_client.audio.transcriptions.create(
                    model="whisper-1", 
                    file=audio_file,
                    language="zh",  # 指定中文
                    response_format="text"
                )
            
            result_text = transcription.strip()
            logger.info(f"OpenAI 轉錄成功: {result_text[:50]}...")
            return result_text
            
        except Exception as e:
            logger.error(f"OpenAI API 呼叫失敗: {e}")
            return None
        finally:
            try:
                os.unlink(temp_file_path)
            except:
                pass
                
    except Exception as e:
        logger.error(f"OpenAI 轉錄過程發生錯誤: {e}")
        return None


def generate_ai_summary(text):
    """
    使用 Groq Llama-3 模型生成一段簡短的摘要 (約 50 字以內)
    """
    if not groq_client:
        logger.warning("未偵測到 Groq 客戶端，跳過摘要生成")
        return text[:50] + "..." if len(text) > 50 else text

    try:
        prompt = f"請將以下這段筆記內容歸納成一段精簡的摘要（大約 30-50 字），並以第一人稱或重點條列方式呈現。只需回覆摘要文字，不要有額外的問候語：\n\n內容：{text}"
        
        completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "你是一個專業的筆記秘書，擅長精簡歸納重點。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=200
        )
        
        summary = completion.choices[0].message.content.strip()
        logger.info(f"AI 摘要生成成功: {summary[:50]}...")
        return summary
    except Exception as e:
        logger.error(f"AI 摘要生成失敗: {e}")
        return text[:50] + "..." if len(text) > 50 else text


def save_to_notion(content, summary, note_type):
    """
    將內容儲存到 Notion 資料庫
    """
    notion_token = os.getenv('NOTION_TOKEN')
    database_id = os.getenv('NOTION_DATABASE_ID')
    
    if not notion_token or not database_id:
        logger.warning("缺少 Notion 設定，跳過儲存功能")
        return False

    try:
        import requests
        url = "https://api.notion.com/v1/pages"
        headers = {
            "Authorization": "Bearer " + notion_token,
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28"
        }
        
        data = {
            "parent": { "database_id": database_id },
            "properties": {
                "名稱": {
                    "title": [{ "text": { "content": content[:2000] } }]  # Notion Title 上限約 2000 字
                },
                "摘要": {
                    "rich_text": [{ "text": { "content": summary } }]
                },
                "類型": {
                    "select": { "name": note_type }
                }
            }
        }
        
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            logger.info(f"Notion 儲存成功：{note_type}")
            return True
        else:
            logger.error(f"Notion 儲存失敗 (狀態碼: {response.status_code}): {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"Notion 儲存過程出錯 (Exception): {e}")
        return False


def upload_to_google_drive(file_data, file_name):
    """
    將檔案上傳到 Google Drive 並取得公開分享連結 (使用 OAuth 2.0)
    """
    service = get_google_drive_service()
    
    if service == "NEEDS_AUTH":
        logger.error("Google Drive 需要授權，請使用 /auth_url 獲取連結")
        return "NEEDS_AUTH"
    
    if not service:
        logger.error("無法取得 Google Drive 服務")
        return None

    try:
        folder_id = os.getenv('GOOGLE_DRIVE_FOLDER_ID')
        file_metadata = {'name': file_name}
        if folder_id:
            file_metadata['parents'] = [folder_id]
            
        media = MediaIoBaseUpload(io.BytesIO(file_data), mimetype='image/jpeg', resumable=True)
        file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        file_id = file.get('id')
        
        # 設定為公開讀取
        service.permissions().create(
            fileId=file_id,
            body={'type': 'anyone', 'role': 'viewer'}
        ).execute()
        
        # 取得直接下載連結
        return f"https://drive.google.com/uc?id={file_id}"
        
    except Exception as e:
        logger.error(f"Google Drive OAuth 上傳失敗: {e}")
        return None

def get_google_auth_url():
    """產生 Google OAuth 授權連結"""
    try:
        base64_data = os.getenv('GOOGLE_OAUTH_CREDENTIALS_BASE64')
        if not base64_data:
            return "缺少 GOOGLE_OAUTH_CREDENTIALS_BASE64 環境變數"
            
        missing_padding = len(base64_data) % 4
        if missing_padding:
            base64_data += '=' * (4 - missing_padding)
        
        credentials_json = base64.b64decode(base64_data).decode('utf-8')
        credentials_info = json.loads(credentials_json)
        
        flow = InstalledAppFlow.from_client_config(
            credentials_info,
            scopes=["https://www.googleapis.com/auth/drive"]
        )
        flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
        auth_url, _ = flow.authorization_url(prompt='consent')
        return auth_url
    except Exception as e:
        return f"產生授權網址失敗: {e}"

def complete_google_auth(code):
    """使用授權碼完成授權過程"""
    try:
        base64_data = os.getenv('GOOGLE_OAUTH_CREDENTIALS_BASE64')
        if not base64_data:
            return "缺少 GOOGLE_OAUTH_CREDENTIALS_BASE64"
            
        missing_padding = len(base64_data) % 4
        if missing_padding:
            base64_data += '=' * (4 - missing_padding)
        
        credentials_json = base64.b64decode(base64_data).decode('utf-8')
        credentials_info = json.loads(credentials_json)
        
        flow = InstalledAppFlow.from_client_config(
            credentials_info,
            scopes=["https://www.googleapis.com/auth/drive"]
        )
        flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
        flow.fetch_token(code=code)
        
        creds = flow.credentials
        save_token_to_sheets(json.loads(creds.to_json()))
        return "✅ 授權成功！圖片助手已就緒。"
    except Exception as e:
        return f"❌ 授權失敗: {e}"


def analyze_image_with_ai(image_data):
    """
    使用 Groq Vision 模型或 OpenAI GPT-4o 讀取圖片
    """
    if not groq_client:
        logger.warning("未偵測到 Groq 客戶端，無法進行圖片分析")
        return "圖片筆記", "無法分析圖片內容 (缺少 API Key)"

    try:
        # 將圖片轉換為 Base64
        base64_image = base64.b64encode(image_data).decode('utf-8')
        
        # 嘗試模型列表 (依序嘗試)
        # 使用 Groq 支援的視覺模型
        models_to_try = [
            "llama-3.2-11b-vision-preview",
            "llama-3.2-90b-vision-preview"
        ]
        
        last_error = None
        for model_name in models_to_try:
            try:
                logger.info(f"嘗試使用模型分析圖片: {model_name}")
                completion = groq_client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "請幫我分析這張圖片內容。請回覆一個簡單的 json 格式，包含兩個欄位：'title' (適合作為筆記標題，15字以內) 與 'summary' (一段詳細的內容摘要，約 100 字以內)。請只回覆 JSON 字串，不要有其他文字。"},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{base64_image}",
                                    },
                                },
                            ],
                        }
                    ],
                    temperature=0.1,
                )
                
                response_text = completion.choices[0].message.content.strip()
                # 清除 Markdown code block 標記
                if "```json" in response_text:
                    response_text = response_text.split("```json")[1].split("```")[0].strip()
                elif "```" in response_text:
                    response_text = response_text.split("```")[1].split("```")[0].strip()
                    
                data = json.loads(response_text)
                return data.get('title', '新圖片筆記'), data.get('summary', '無摘要')
            except Exception as model_err:
                logger.warning(f"模型 {model_name} 分析失敗: {model_err}")
                last_error = model_err
                continue
        
        raise last_error if last_error else Exception("所有視覺模型均失效")
        
    except Exception as e:
        logger.error(f"AI 圖片分析最終失敗: {e}")
        return "圖片筆記", f"圖片分析發生錯誤: {str(e)[:100]}"


def save_to_notion(content, summary, note_type, url=None):
    """
    將內容儲存到 Notion 資料庫，支援 URL
    """
    notion_token = os.getenv('NOTION_TOKEN')
    database_id = os.getenv('NOTION_DATABASE_ID')
    
    if not notion_token or not database_id:
        logger.warning("缺少 Notion 設定，跳過儲存功能")
        return False

    try:
        import requests
        api_url = "https://api.notion.com/v1/pages"
        headers = {
            "Authorization": "Bearer " + notion_token,
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28"
        }
        
        properties = {
            "名稱": {
                "title": [{ "text": { "content": content[:2000] } }]
            },
            "摘要": {
                "rich_text": [{ "text": { "content": summary } }]
            },
            "類型": {
                "select": { "name": note_type }
            }
        }
        
        if url:
            properties["URL"] = {
                "url": url
            }
        
        data = {
            "parent": { "database_id": database_id },
            "properties": properties
        }
        
        response = requests.post(api_url, headers=headers, json=data)
        if response.status_code == 200:
            logger.info(f"Notion 儲存成功：{note_type}")
            return True
        else:
            logger.error(f"Notion 儲存失敗 (狀態碼: {response.status_code}): {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"Notion 儲存過程出錯 (Exception): {e}")
        return False


def transcribe_audio_with_local_whisper(audio_data):
    """
    使用本地 Whisper 模型轉錄音檔
    自動選擇適合的模型大小，完全免費
    """
    try:
        # 延遲加載模型
        model = load_whisper_model()
        if not model:
            logger.error("Whisper 模型加載失敗")
            return None
        
        # 根據模型大小調整分割策略(雲端部署優化)
        chunk_size = 15 if WHISPER_MODEL_SIZE == 'tiny' else 20
        audio_chunks = split_audio_for_whisper(audio_data, chunk_size_mb=chunk_size)
        
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
                    result = model.transcribe(
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
    if not handler or not line_bot_api:
        logger.error("LINE Bot 未正確初始化")
        abort(500)
        
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


def handle_text_message(event):
    """處理文字訊息事件"""
    try:
        user_id = event.source.user_id
        message_text = event.message.text.strip()
        
        logger.info(f"收到文字訊息 - 用戶: {user_id}, 訊息: {message_text[:100]}...")
        
        # 處理用戶會話和顯示名稱
        session = get_user_session(user_id)
        user_name = get_user_display_name(user_id)
        
        # 處理 OAuth 授權指令 (最高優先權)
        if message_text.startswith("/auth "):
            code = message_text.split("/auth ")[1].strip()
            result = complete_google_auth(code)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=result))
            return

        if message_text == "/auth_url":
            url = get_google_auth_url()
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"🔑 請點擊連結進行 Google Drive 授權：\n\n{url}\n\n授權完成後，請回覆：\n/auth 您的授權碼"))
            return

        # 處理會議記錄指令
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
🖼️ 傳送圖片 - AI 分析、產生摘要並存入 Notion
🔑 /auth_url - 重新取得 Google Drive 授權連結
📖 /help - 顯示此說明

💡 本機器人支援：
1. **會議記錄**：自動彙整文字與語音
2. **AI 圖片助手**：自動讀取圖片內容、產生摘要，並上傳至 Google Drive 與 Notion 存檔

💡 使用方式：
1. 輸入 /save 開始記錄
2. 發送語音或文字訊息
3. 所有內容會累積顯示
4. 輸入 /end 儲存到試算表

✨ 支援功能：
• 語音助理（使用 Groq Whisper API）
• 圖片助手（AI 讀圖、上傳 Drive、同步 Notion）
• AI 自動摘要與 Notion 同步
• 自動記錄到 Google Sheets (會議模式)
• 支援語音轉文字並立即回傳"""
        
        else:
            # 一般文字訊息
            if session.is_recording:
                session.add_message(message_text)
                conversation_text = session.get_conversation_text()
                reply_text = f"📝 已記錄文字訊息\n\n💬 目前累積內容:\n\n{conversation_text}\n\n📊 共 {len(session.conversation_buffer)} 條記錄 | 輸入 /end 結束並儲存"
            else:
                # 非錄音模式：自動執行 AI 摘要並存入 Notion
                summary = generate_ai_summary(message_text)
                notion_saved = save_to_notion(message_text, summary, "文字筆記")
                
                notion_status = "✅ 已同步至 Notion" if notion_saved else "⚠️ Notion 同步失敗 (請檢查金鑰)"
                reply_text = f"📝 已收到筆記\n\n🔍 AI 摘要：\n{summary}\n\n{notion_status}"
        
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


def handle_audio_message(event):
    """處理語音訊息事件"""
    try:
        user_id = event.source.user_id
        logger.info(f"收到語音訊息 - 用戶: {user_id}")
        
        # 取得用戶會話
        session = get_user_session(user_id)
        
        # 1. 下載音檔
        message_content = line_bot_api.get_message_content(event.message.id)
        audio_data = message_content.content
        
        # 2. 先回覆處理中訊息（使用 reply_token）
        try:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="🎤 收到語音，正在辨識中...")
            )
        except Exception as e:
            logger.error(f"回覆處理中訊息失敗: {e}")

        # 3. 執行轉錄 (優先使用 Groq)
        transcription = None
        engine_name = ""
        
        if groq_client:
            logger.info("嘗試使用 Groq Whisper 進行轉錄...")
            transcription = transcribe_audio_with_groq(audio_data)
            engine_name = "Groq Whisper"
        
        # 如果 Groq 失敗或未設定，嘗試使用 OpenAI (需付費)
        if not transcription and openai_client:
            logger.info("嘗試使用 OpenAI Whisper 進行轉錄...")
            transcription = transcribe_audio_with_openai(audio_data)
            engine_name = "OpenAI Whisper"
        
        # 最後備援：嘗試本地轉錄
        if not transcription:
            logger.info("嘗試使用本地 Whisper 進行備援轉錄...")
            transcription = transcribe_audio_with_local_whisper(audio_data)
            engine_name = "本地 Whisper AI"

        # 4. 處理轉錄結果
        if transcription:
            if session.is_recording:
                # 錄音模式：累積內容
                session.add_message(f"[語音] {transcription}")
                conversation_text = session.get_conversation_text()
                result_text = f"✅ 【{engine_name}】辨識成功！\n\n📝 內容：\n{transcription}\n\n💬 目前累積完整內容：\n\n{conversation_text}\n\n📊 輸入 /end 結束並儲存"
            else:
                # 一般助理模式：AI 摘要並存入 Notion
                summary = generate_ai_summary(transcription)
                notion_saved = save_to_notion(transcription, summary, "語音筆記")
                
                notion_status = "✅ 已同步至 Notion" if notion_saved else "⚠️ Notion 同步失敗"
                result_text = f"🎤 語音助理辨識結果：\n\n{transcription}\n\n🔍 AI 摘要：\n{summary}\n\n{notion_status}\n\n💡 提示：輸入 /save 可開啟會議記錄模式。"
        else:
            result_text = "❌ 語音辨識失敗。原因可能是 API 額度用盡或伺服器繁忙，請稍後再試。"

        # 5. 推送結果（使用 push_message）
        line_bot_api.push_message(
            user_id,
            TextSendMessage(text=result_text)
        )
        
    except Exception as e:
        logger.error(f"處理語音訊息時發生錯誤: {e}")
        try:
            line_bot_api.push_message(
                user_id,
                TextSendMessage(text="❌ 語音處理發生伺服器錯誤，請檢查設定。")
            )
        except:
            pass


def handle_image_message(event):
    """處理圖片訊息事件"""
    try:
        user_id = event.source.user_id
        logger.info(f"收到圖片訊息 - 用戶: {user_id}")
        
        # 1. 回覆處理中
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="🖼️ 收到圖片，正在進行 AI 視覺分析與存檔...")
        )
        
        # 2. 下載圖片
        message_content = line_bot_api.get_message_content(event.message.id)
        image_data = message_content.content
        
        # 3. AI 視覺分析
        title, summary = analyze_image_with_ai(image_data)
        
        # 4. 上傳到 Google Drive
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"image_{timestamp}.jpg"
        drive_url = upload_to_google_drive(image_data, file_name)
        
        # 5. 儲存到 Notion
        notion_saved = save_to_notion(title, summary, "圖片筆記", drive_url)
        
        if drive_url == "NEEDS_AUTH":
            drive_status = "❌ 需要授權"
            auth_url = get_google_auth_url()
            result_text = f"🖼️ 圖片分析完成，但上傳失敗。\n\n📌 標題：{title}\n\n🔐 原因：Google Drive 需要重新授權。\n請點擊連結授權並回傳授權碼：\n{auth_url}\n\n回傳格式：/auth 您的授權碼"
        elif drive_url == "QUOTA_ERROR":
            drive_status = "❌ 雲端空間不足 (服務帳戶限制)"
            notion_status = "✅ 已同步至 Notion (無圖片連結)"
            result_text = f"🖼️ 圖片分析完成！\n\n📌 標題：{title}\n🔍 摘要：\n{summary}\n\n⚠️ {drive_status}\n{notion_status}\n💡 提示：請將雲端資料夾移動至『共用雲端硬碟』，或檢查空間。"
        else:
            drive_status = f"📂 [雲端連結]({drive_url})" if drive_url else "❌ 雲端上傳失敗"
            notion_status = "✅ 已同步至 Notion" if notion_saved else "⚠️ Notion 同步失敗"
            result_text = f"🖼️ 圖片分析完成！\n\n📌 標題：{title}\n🔍 摘要：\n{summary}\n\n🔗 {drive_status}\n{notion_status}"
        
        line_bot_api.push_message(
            user_id,
            TextSendMessage(text=result_text)
        )
        
    except Exception as e:
        logger.error(f"處理圖片訊息時發生錯誤: {e}")
        try:
            line_bot_api.push_message(
                user_id,
                TextSendMessage(text="❌ 圖片處理失敗，請稍後再試。")
            )
        except:
            pass


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


# 註冊事件處理器（只有在 handler 初始化成功時才註冊）
if handler:
    handler.add(MessageEvent, message=TextMessage)(handle_text_message)
    handler.add(MessageEvent, message=AudioMessage)(handle_audio_message)
    handler.add(MessageEvent, message=ImageMessage)(handle_image_message)
    handler.add(MessageEvent)(handle_other_message)
    logger.info("LINE Bot 事件處理器註冊成功")
else:
    logger.warning("LINE Bot handler 未初始化，跳過事件處理器註冊")


if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)