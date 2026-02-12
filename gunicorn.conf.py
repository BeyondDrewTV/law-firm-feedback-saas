import os

bind = f"0.0.0.0:{os.getenv('PORT', '10000')}"
workers = int(os.getenv('GUNICORN_WORKERS', '3'))
threads = int(os.getenv('GUNICORN_THREADS', '2'))
worker_class = os.getenv('GUNICORN_WORKER_CLASS', 'gthread')
timeout = int(os.getenv('GUNICORN_TIMEOUT', '120'))
graceful_timeout = 30
keepalive = 5
max_requests = 1000
max_requests_jitter = 50
accesslog = '-'
errorlog = '-'
loglevel = os.getenv('GUNICORN_LOG_LEVEL', 'info')
