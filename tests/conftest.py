import os

os.environ["CACHE_BACKEND"] = "memory"
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ.pop("REDIS_URL", None)
