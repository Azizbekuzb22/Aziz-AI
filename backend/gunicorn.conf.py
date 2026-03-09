# Gunicorn configuration file for Render deployment
import multiprocessing
import os

# Worker settings
workers = 1 # Free serverlar uchun 1 ta worker yetarli
threads = 4

# Eng asosiysi: Timeout kiritamiz
timeout = 160 

# Portni avtomatik topish va ulash (Render uchun)
port = os.getenv("PORT", "10000")
bind = f"0.0.0.0:{port}"

# Logging info
accesslog = "-"
errorlog = "-"
loglevel = "info"
