import os

bind = f"0.0.0.0:{os.getenv('PORT', '10000')}"
workers = int(os.getenv("WEB_CONCURRENCY", "2"))   # free tier has 512 MB RAM
threads = 2
timeout = 60            # Neon can take a few seconds to wake from idle
graceful_timeout = 30
keepalive = 5
accesslog = "-"
errorlog = "-"
forwarded_allow_ips = "*"   # Render terminates TLS in front of the app
