# Gunicorn 設定檔
import os

# 伺服器 socket
bind = f"0.0.0.0:{os.environ.get('PORT', 5000)}"

# Worker 進程設定
workers = 1
worker_class = "sync"
worker_connections = 1000
timeout = 120
keepalive = 60

# 日誌設定
loglevel = "info"
accesslog = "-"
errorlog = "-"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# 進程命名
proc_name = "linebot_app"

# 重新啟動設定
max_requests = 1000
max_requests_jitter = 100

# 安全設定
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190