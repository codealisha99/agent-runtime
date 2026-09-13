import os
import tempfile

os.environ["CACHE_BACKEND"] = "memory"
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["WORKSPACE_DIR"] = tempfile.mkdtemp(prefix="agent-runtime-")
os.environ["SANDBOX_TIMEOUT"] = "1"
os.environ["TOOL_TIMEOUT"] = "2"
os.environ["TOOL_RETRIES"] = "2"
os.environ.pop("REDIS_URL", None)
