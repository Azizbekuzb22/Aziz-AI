# Gunicorn configuration file for Render deployment
import multiprocessing

# Worker settings
workers = 1 # Free serverlar uchun 1 ta worker yetarli
threads = 4

# Eng asosiysi: Timeout kiritamiz. Gemini uzoq o'ylasa 30 soniyada o'chib qolmasligi uchun (Default: 30s)
timeout = 160 

# Logging info
accesslog = "-"
errorlog = "-"
loglevel = "info"
