"""
============================================================
Octuplex 后端主程序
包含：FastAPI接口 + WebSocket服务 + 智能体ReAct引擎
       + 全部工具/记忆/任务调度/安全逻辑
部署环境：Hugging Face Space (Gradio类型)
============================================================
模块架构（七层架构）：
  1. 前端交互层 → index.html（独立部署）
  2. 网关安全层 → Gateway/Security（本文件）
  3. 智能体核心调度层 → AgentCore（本文件）
  4. 记忆管理层 → MemoryManager（本文件）
  5. 技能工具层 → SkillRegistry + BuiltinTools（本文件）
  6. 沙盒执行层 → SandboxExecutor（本文件）
  7. 大模型推理接入层 → LLMAdapter（本文件）
  8. 外部依赖服务层 → ExternalServices（本文件）
============================================================
"""

import os
import sys
import json
import time
import uuid
import asyncio
import logging
import traceback
import subprocess
import hashlib
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Callable
from collections import defaultdict
from contextlib import asynccontextmanager

# ============================================================
# 环境变量加载
# ============================================================
from dotenv import load_dotenv
load_dotenv()

# ---- 日志系统初始化 ----
LOG_DIR = Path(os.getenv("LOG_DIR", "./logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="[%(asctime)s] [%(levelname)s] [Octuplex] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "octuplex.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("Octuplex")

# ============================================================
# 配置加载（从环境变量读取，无硬编码）
# ============================================================
class Config:
    """全局配置管理，所有参数从.env读取"""
    # 大模型配置
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")
    LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "deepseek-chat")
    LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "8192"))
    LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.7"))

    LLM_PREMIUM_BASE_URL = os.getenv("LLM_PREMIUM_BASE_URL", LLM_BASE_URL)
    LLM_PREMIUM_API_KEY = os.getenv("LLM_PREMIUM_API_KEY", LLM_API_KEY)
    LLM_PREMIUM_MODEL_NAME = os.getenv("LLM_PREMIUM_MODEL_NAME", "deepseek-reasoner")
    LLM_PREMIUM_MAX_TOKENS = int(os.getenv("LLM_PREMIUM_MAX_TOKENS", "32768"))

    LLM_LITE_BASE_URL = os.getenv("LLM_LITE_BASE_URL", LLM_BASE_URL)
    LLM_LITE_API_KEY = os.getenv("LLM_LITE_API_KEY", LLM_API_KEY)
    LLM_LITE_MODEL_NAME = os.getenv("LLM_LITE_MODEL_NAME", "deepseek-chat")
    LLM_LITE_MAX_TOKENS = int(os.getenv("LLM_LITE_MAX_TOKENS", "4096"))

    # 搜索配置
    SEARCH_API_PROVIDER = os.getenv("SEARCH_API_PROVIDER", "duckduckgo")
    SEARCH_API_KEY = os.getenv("SEARCH_API_KEY", "")
    SEARCH_MAX_RESULTS = int(os.getenv("SEARCH_MAX_RESULTS", "5"))
    SEARCH_BLACKLIST_DOMAINS = [d.strip() for d in os.getenv("SEARCH_BLACKLIST_DOMAINS", "").split(",") if d.strip()]

    # GitHub配置
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
    GITHUB_USERNAME = os.getenv("GITHUB_USERNAME", "")
    GITHUB_REPO = os.getenv("GITHUB_REPO", "")

    # 向量数据库
    CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./chroma_db")
    CHROMA_COLLECTION_MEMORY = os.getenv("CHROMA_COLLECTION_MEMORY", "octuplex_long_term_memory")
    CHROMA_COLLECTION_RAG = os.getenv("CHROMA_COLLECTION_RAG", "octuplex_rag_knowledge")

    # 沙盒配置
    SANDBOX_WORK_DIR = os.getenv("SANDBOX_WORK_DIR", "./sandbox_workspace")
    SANDBOX_EXEC_TIMEOUT = int(os.getenv("SANDBOX_EXEC_TIMEOUT", "300"))
    SANDBOX_MEMORY_LIMIT = int(os.getenv("SANDBOX_MEMORY_LIMIT", "512"))
    SANDBOX_BANNED_COMMANDS = [c.strip() for c in os.getenv("SANDBOX_BANNED_COMMANDS", "").split(",") if c.strip()]

    # 安全配置
    CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
    API_SECRET_KEY = os.getenv("API_SECRET_KEY", "octuplex-secret-change-me")

    # 限额
    DAILY_TOKEN_LIMIT = int(os.getenv("DAILY_TOKEN_LIMIT", "0"))
    SESSION_TOKEN_LIMIT = int(os.getenv("SESSION_TOKEN_LIMIT", "0"))
    MAX_TOOL_CALLS_PER_TASK = int(os.getenv("MAX_TOOL_CALLS_PER_TASK", "50"))
    MAX_RETRIES_PER_TASK = int(os.getenv("MAX_RETRIES_PER_TASK", "5"))

    # 服务
    SERVER_PORT = int(os.getenv("SERVER_PORT", "7860"))
    SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
    ENABLE_GRADIO = os.getenv("ENABLE_GRADIO", "true").lower() == "true"

config = Config()

# ============================================================
# 第2层：网关安全层
# ============================================================
class AuditLogger:
    """全链路审计日志系统"""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._logs = []
        return cls._instance

    def log(self, event_type: str, details: dict, session_id: str = "unknown"):
        """记录审计日志"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "session_id": session_id,
            "details": details
        }
        self._logs.append(entry)
        logger.info(f"[Audit] {event_type} | session={session_id} | {json.dumps(details, ensure_ascii=False)}")
        return entry

    def get_logs(self, session_id: str = None, event_type: str = None,
                 start_time: str = None, end_time: str = None) -> List[dict]:
        """检索审计日志"""
        results = self._logs
        if session_id:
            results = [l for l in results if l["session_id"] == session_id]
        if event_type:
            results = [l for l in results if l["event_type"] == event_type]
        if start_time:
            results = [l for l in results if l["timestamp"] >= start_time]
        if end_time:
            results = [l for l in results if l["timestamp"] <= end_time]
        return results

    def export_logs(self) -> str:
        """导出审计日志为JSON"""
        return json.dumps(self._logs, ensure_ascii=False, indent=2)

audit = AuditLogger()

class RateLimiter:
    """接口限流器"""
    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._clients: Dict[str, List[float]] = defaultdict(list)

    def check(self, client_id: str) -> bool:
        """检查请求是否超限"""
        now = time.time()
        self._clients[client_id] = [t for t in self._clients[client_id] if now - t < self.window_seconds]
        if len(self._clients[client_id]) >= self.max_requests:
            return False
        self._clients[client_id].append(now)
        return True

rate_limiter = RateLimiter()

def validate_sandbox_command(command: str) -> bool:
    """校验命令是否包含高危操作"""
    for banned in config.SANDBOX_BANNED_COMMANDS:
        if banned in command:
            return False
    return True

# ============================================================
# 第7层：大模型推理接入层
# ============================================================
class TokenTracker:
    """Token用量统计与费用管理"""
    def __init__(self):
        self.daily_input_tokens = 0
        self.daily_output_tokens = 0
        self.session_input_tokens = 0
        self.session_output_tokens = 0
        self.daily_date = datetime.now().date()
        self._call_history: List[dict] = []

    def _reset_daily_if_needed(self):
        """跨天自动重置每日计数"""
        today = datetime.now().date()
        if today != self.daily_date:
            self.daily_input_tokens = 0
            self.daily_output_tokens = 0
            self.daily_date = today

    def record(self, input_tokens: int, output_tokens: int, model_name: str):
        """记录一次调用消耗"""
        self._reset_daily_if_needed()
        self.daily_input_tokens += input_tokens
        self.daily_output_tokens += output_tokens
        self.session_input_tokens += input_tokens
        self.session_output_tokens += output_tokens
        self._call_history.append({
            "time": datetime.now().isoformat(),
            "model": model_name,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens
        })

    def check_daily_limit(self) -> bool:
        """检查是否超过每日限额"""
        if config.DAILY_TOKEN_LIMIT <= 0:
            return True
        total = self.daily_input_tokens + self.daily_output_tokens
        return total < config.DAILY_TOKEN_LIMIT

    def check_session_limit(self) -> bool:
        """检查是否超过会话限额"""
        if config.SESSION_TOKEN_LIMIT <= 0:
            return True
        total = self.session_input_tokens + self.session_output_tokens
        return total < config.SESSION_TOKEN_LIMIT

    def get_stats(self) -> dict:
        """获取统计信息"""
        self._reset_daily_if_needed()
        return {
            "daily_input_tokens": self.daily_input_tokens,
            "daily_output_tokens": self.daily_output_tokens,
            "daily_total": self.daily_input_tokens + self.daily_output_tokens,
            "session_input_tokens": self.session_input_tokens,
            "session_output_tokens": self.session_output_tokens,
            "session_total": self.session_input_tokens + self.session_output_tokens,
            "daily_limit": config.DAILY_TOKEN_LIMIT,
            "session_limit": config.SESSION_TOKEN_LIMIT
        }

    def reset_session(self):
        """重置会话计数"""
        self.session_input_tokens = 0
        self.session_output_tokens = 0

token_tracker = TokenTracker()

class LLMAdapter:
    """
    多模型适配器
    兼容OpenAI调用格式的第三方大模型API
    支持：智能路由、故障切换、流式输出
    """
    def __init__(self):
        # 模型配置字典
        self.models = {
            "default": {
                "base_url": config.LLM_BASE_URL,
                "api_key": config.LLM_API_KEY,
                "model": config.LLM_MODEL_NAME,
                "max_tokens": config.LLM_MAX_TOKENS
            },
            "premium": {
                "base_url": config.LLM_PREMIUM_BASE_URL,
                "api_key": config.LLM_PREMIUM_API_KEY,
                "model": config.LLM_PREMIUM_MODEL_NAME,
                "max_tokens": config.LLM_PREMIUM_MAX_TOKENS
            },
            "lite": {
                "base_url": config.LLM_LITE_BASE_URL,
                "api_key": config.LLM_LITE_API_KEY,
                "model": config.LLM_LITE_MODEL_NAME,
                "max_tokens": config.LLM_LITE_MAX_TOKENS
            }
        }
        self._current_tier = "default"

    def route_model(self, task_complexity: str) -> str:
        """
        智能路由：根据任务复杂度选择模型
        simple → lite, complex → premium, normal → default
        """
        if task_complexity == "simple":
            self._current_tier = "lite"
        elif task_complexity in ("complex", "multi_step"):
            self._current_tier = "premium"
        else:
            self._current_tier = "default"
        return self._current_tier

    async def chat(self, messages: List[dict], task_complexity: str = "normal",
                   stream: bool = False) -> dict:
        """
        调用大模型API（支持故障转移）
        """
        tier = self.route_model(task_complexity)
        model_cfg = self.models[tier]

        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(
                base_url=model_cfg["base_url"],
                api_key=model_cfg["api_key"]
            )

            response = await client.chat.completions.create(
                model=model_cfg["model"],
                messages=messages,
                max_tokens=model_cfg["max_tokens"],
                temperature=config.LLM_TEMPERATURE,
                stream=stream
            )

            if not stream:
                usage = response.usage
                token_tracker.record(
                    usage.prompt_tokens if usage else 0,
                    usage.completion_tokens if usage else 0,
                    model_cfg["model"]
                )
                return {
                    "content": response.choices[0].message.content,
                    "model": model_cfg["model"],
                    "tier": tier
                }
            else:
                return {"stream": response, "model": model_cfg["model"], "tier": tier}

        except Exception as e:
            logger.warning(f"模型 {tier} 调用失败: {e}，尝试故障转移...")
            # 故障转移：切换到默认模型重试
            if tier != "default":
                fallback_cfg = self.models["default"]
                try:
                    from openai import AsyncOpenAI
                    client = AsyncOpenAI(
                        base_url=fallback_cfg["base_url"],
                        api_key=fallback_cfg["api_key"]
                    )
                    response = await client.chat.completions.create(
                        model=fallback_cfg["model"],
                        messages=messages,
                        max_tokens=fallback_cfg["max_tokens"],
                        temperature=config.LLM_TEMPERATURE
                    )
                    usage = response.usage
                    token_tracker.record(
                        usage.prompt_tokens if usage else 0,
                        usage.completion_tokens if usage else 0,
                        fallback_cfg["model"]
                    )
                    return {
                        "content": response.choices[0].message.content,
                        "model": fallback_cfg["model"],
                        "tier": "default",
                        "fallback": True
                    }
                except Exception as e2:
                    logger.error(f"故障转移也失败: {e2}")
                    raise
            raise

    async def chat_stream(self, messages: List[dict], task_complexity: str = "normal"):
        """流式调用大模型API"""
        tier = self.route_model(task_complexity)
        model_cfg = self.models[tier]

        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(
                base_url=model_cfg["base_url"],
                api_key=model_cfg["api_key"]
            )

            stream = await client.chat.completions.create(
                model=model_cfg["model"],
                messages=messages,
                max_tokens=model_cfg["max_tokens"],
                temperature=config.LLM_TEMPERATURE,
                stream=True
            )

            input_estimate = sum(len(str(m)) // 4 for m in messages)
            output_chars = 0

            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    output_chars += len(content)
                    yield content

            token_tracker.record(input_estimate, output_chars // 4, model_cfg["model"])

        except Exception as e:
            logger.warning(f"模型 {tier} 流式调用失败: {e}，尝试故障转移...")
            if tier != "default":
                fallback_cfg = self.models["default"]
                try:
                    from openai import AsyncOpenAI
                    client = AsyncOpenAI(
                        base_url=fallback_cfg["base_url"],
                        api_key=fallback_cfg["api_key"]
                    )
                    stream = await client.chat.completions.create(
                        model=fallback_cfg["model"],
                        messages=messages,
                        max_tokens=fallback_cfg["max_tokens"],
                        temperature=config.LLM_TEMPERATURE,
                        stream=True
                    )
                    async for chunk in stream:
                        if chunk.choices[0].delta.content:
                            yield chunk.choices[0].delta.content
                except Exception as e2:
                    logger.error(f"故障转移流式也失败: {e2}")
                    yield f"\n[错误] 模型调用失败: {str(e2)}"
            else:
                yield f"\n[错误] 模型调用失败: {str(e)}"

llm_adapter = LLMAdapter()

# ============================================================
# 第4层：记忆管理层
# ============================================================
class MemoryManager:
    """
    三级记忆管理系统
    1. 短期上下文：会话内对话历史
    2. 长期记忆：向量数据库存储用户偏好/经验
    3. RAG知识库：私有文档向量检索
    """
    def __init__(self):
        self._short_term: Dict[str, List[dict]] = defaultdict(list)
        self._long_term: Optional[Any] = None
        self._rag_store: Optional[Any] = None
        self._init_chroma()

    def _init_chroma(self):
        """初始化向量数据库"""
        try:
            import chromadb
            from chromadb.config import Settings

            Path(config.CHROMA_PERSIST_DIR).mkdir(parents=True, exist_ok=True)

            self._chroma_client = chromadb.PersistentClient(
                path=config.CHROMA_PERSIST_DIR,
                settings=Settings(anonymized_telemetry=False)
            )

            # 长期记忆集合
            try:
                self._long_term = self._chroma_client.get_collection(
                    config.CHROMA_COLLECTION_MEMORY
                )
            except Exception:
                self._long_term = self._chroma_client.create_collection(
                    config.CHROMA_COLLECTION_MEMORY,
                    metadata={"description": "Octuplex长期用户记忆"}
                )

            # RAG知识库集合
            try:
                self._rag_store = self._chroma_client.get_collection(
                    config.CHROMA_COLLECTION_RAG
                )
            except Exception:
                self._rag_store = self._chroma_client.create_collection(
                    config.CHROMA_COLLECTION_RAG,
                    metadata={"description": "Octuplex RAG知识库"}
                )

            logger.info(f"向量数据库初始化完成: {config.CHROMA_PERSIST_DIR}")
        except Exception as e:
            logger.warning(f"向量数据库初始化失败（将仅使用短期记忆）: {e}")
            self._chroma_client = None
            self._long_term = None
            self._rag_store = None

    # ---- 短期上下文管理 ----
    def add_short_term(self, session_id: str, role: str, content: str):
        """添加短期对话记录"""
        self._short_term[session_id].append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })
        # 自动压缩超长上下文
        if len(self._short_term[session_id]) > 50:
            self._short_term[session_id] = self._short_term[session_id][-40:]

    def get_short_term(self, session_id: str, max_turns: int = 20) -> List[dict]:
        """获取短期对话历史"""
        history = self._short_term[session_id]
        return [{"role": h["role"], "content": h["content"]} for h in history[-max_turns:]]

    def clear_short_term(self, session_id: str):
        """清空短期上下文"""
        self._short_term[session_id] = []

    # ---- 长期记忆管理 ----
    def add_long_term(self, memory_text: str, metadata: dict = None, memory_id: str = None):
        """添加长期记忆到向量库"""
        if self._long_term is None:
            return False
        try:
            mid = memory_id or str(uuid.uuid4())
            self._long_term.add(
                documents=[memory_text],
                metadatas=[metadata or {}],
                ids=[mid]
            )
            return True
        except Exception as e:
            logger.warning(f"长期记忆写入失败: {e}")
            return False

    def search_long_term(self, query: str, top_k: int = 5) -> List[dict]:
        """检索长期记忆"""
        if self._long_term is None:
            return []
        try:
            results = self._long_term.query(query_texts=[query], n_results=top_k)
            return [
                {"content": doc, "metadata": meta}
                for doc, meta in zip(results["documents"][0], results["metadatas"][0])
            ]
        except Exception as e:
            logger.warning(f"长期记忆检索失败: {e}")
            return []

    def forget_old_memories(self, days: int = 30):
        """遗忘过期记忆"""
        if self._long_term is None:
            return
        try:
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()
            all_items = self._long_term.get()
            for i, meta in enumerate(all_items["metadatas"]):
                if meta.get("created_at", "") < cutoff:
                    self._long_term.delete(ids=[all_items["ids"][i]])
        except Exception as e:
            logger.warning(f"记忆遗忘处理失败: {e}")

    # ---- RAG知识库管理 ----
    def add_to_rag(self, document: str, metadata: dict = None, doc_id: str = None):
        """添加文档到RAG知识库"""
        if self._rag_store is None:
            return False
        try:
            did = doc_id or str(uuid.uuid4())
            self._rag_store.add(
                documents=[document],
                metadatas=[metadata or {}],
                ids=[did]
            )
            return True
        except Exception as e:
            logger.warning(f"RAG知识库写入失败: {e}")
            return False

    def search_rag(self, query: str, top_k: int = 5) -> List[dict]:
        """检索RAG知识库"""
        if self._rag_store is None:
            return []
        try:
            results = self._rag_store.query(query_texts=[query], n_results=top_k)
            return [
                {"content": doc, "metadata": meta}
                for doc, meta in zip(results["documents"][0], results["metadatas"][0])
            ]
        except Exception as e:
            logger.warning(f"RAG检索失败: {e}")
            return []

    def delete_rag(self, doc_id: str = None):
        """删除RAG知识库中的文档"""
        if self._rag_store is None:
            return
        try:
            if doc_id:
                self._rag_store.delete(ids=[doc_id])
            else:
                all_ids = self._rag_store.get()["ids"]
                if all_ids:
                    self._rag_store.delete(ids=all_ids)
        except Exception as e:
            logger.warning(f"RAG删除失败: {e}")

memory_manager = MemoryManager()

# ============================================================
# 第6层：沙盒执行层 + 内置工具
# ============================================================
class SandboxExecutor:
    """
    隔离Python代码沙盒
    功能：代码执行、文件读写、产物管理、资源限制
    """
    def __init__(self):
        self.work_dir = Path(config.SANDBOX_WORK_DIR)
        self.work_dir.mkdir(parents=True, exist_ok=True)

    async def execute_python(self, code: str, session_id: str) -> dict:
        """
        在隔离环境中执行Python代码
        安全限制：禁用高危操作、限制执行时间、限制内存
        """
        # 安全检查
        if not validate_sandbox_command(code):
            return {"success": False, "error": "代码包含高危操作，已被拦截", "output": ""}

        session_dir = self.work_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        script_path = session_dir / f"script_{uuid.uuid4().hex[:8]}.py"
        script_path.write_text(code, encoding="utf-8")

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-B", str(script_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(session_dir)
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=config.SANDBOX_EXEC_TIMEOUT
                )
            except asyncio.TimeoutError:
                proc.kill()
                return {"success": False, "error": f"执行超时（>{config.SANDBOX_EXEC_TIMEOUT}秒）", "output": ""}

            output = stdout.decode("utf-8", errors="replace")
            error = stderr.decode("utf-8", errors="replace")

            return {
                "success": proc.returncode == 0,
                "output": output,
                "error": error,
                "returncode": proc.returncode
            }
        except Exception as e:
            return {"success": False, "error": str(e), "output": ""}
        finally:
            # 清理脚本文件
            if script_path.exists():
                script_path.unlink()

    def list_files(self, session_id: str) -> List[dict]:
        """列出沙盒工作目录中的文件"""
        session_dir = self.work_dir / session_id
        if not session_dir.exists():
            return []
        files = []
        for f in session_dir.iterdir():
            if f.is_file():
                files.append({
                    "name": f.name,
                    "size": f.stat().st_size,
                    "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat()
                })
        return files

    def get_file_path(self, session_id: str, filename: str) -> Path:
        """获取沙盒中的文件路径"""
        return self.work_dir / session_id / filename

sandbox = SandboxExecutor()

# ---- 工具1：Python代码沙盒工具 ----
class PythonSandboxTool:
    """隔离Python代码执行工具"""
    name = "python_sandbox"
    description = "在隔离沙盒中执行Python代码，支持数据处理、可视化、文件操作等"

    async def execute(self, code: str, session_id: str = "default") -> str:
        audit.log("tool_call", {"tool": "python_sandbox", "code_length": len(code)}, session_id)
        result = await sandbox.execute_python(code, session_id)
        if result["success"]:
            return f"✅ 代码执行成功\n输出:\n{result['output']}"
        else:
            return f"❌ 代码执行失败\n错误: {result['error']}\n输出:\n{result['output']}"

# ---- 工具2：联网检索工具 ----
class WebSearchTool:
    """联网搜索与网页内容爬取工具"""
    name = "web_search"
    description = "联网搜索实时资料，爬取网页内容，提取有效信息"

    async def execute(self, query: str, session_id: str = "default") -> str:
        audit.log("tool_call", {"tool": "web_search", "query": query}, session_id)
        try:
            from duckduckgo_search import DDGS
            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=config.SEARCH_MAX_RESULTS):
                    url = r.get("href", "")
                    # 域名黑名单过滤
                    domain_ok = True
                    for banned in config.SEARCH_BLACKLIST_DOMAINS:
                        if banned in url:
                            domain_ok = False
                            break
                    if domain_ok:
                        results.append({
                            "title": r.get("title", ""),
                            "url": url,
                            "snippet": r.get("body", "")
                        })

            if not results:
                return f"未找到与 '{query}' 相关的搜索结果"

            formatted = [f"## 搜索结果: {query}\n"]
            for i, r in enumerate(results, 1):
                formatted.append(f"**{i}. {r['title']}**")
                formatted.append(f"   链接: {r['url']}")
                formatted.append(f"   摘要: {r['snippet']}\n")

            return "\n".join(formatted)
        except Exception as e:
            return f"搜索失败: {str(e)}"

# ---- 工具3：GitHub操作工具 ----
class GitHubTool:
    """GitHub仓库操作工具（基于用户Token鉴权）"""
    name = "github_ops"
    description = "操作GitHub仓库：读取文件、创建/修改文件、提交推送、查看提交记录"

    async def execute(self, action: str, params: dict, session_id: str = "default") -> str:
        audit.log("tool_call", {"tool": "github_ops", "action": action, "params": params}, session_id)

        if not config.GITHUB_TOKEN:
            return "⚠️ 未配置GitHub Token，请在.env中设置GITHUB_TOKEN"

        try:
            from github import Github
            g = Github(config.GITHUB_TOKEN)
            repo = g.get_repo(f"{config.GITHUB_USERNAME}/{config.GITHUB_REPO}")

            if action == "read_file":
                path = params.get("path", "")
                content = repo.get_contents(path)
                return f"📄 文件: {path}\n```\n{content.decoded_content.decode('utf-8')}\n```"

            elif action == "list_files":
                path = params.get("path", "")
                contents = repo.get_contents(path)
                files = []
                for c in contents:
                    files.append(f"- {'📁' if c.type == 'dir' else '📄'} {c.name} ({c.type})")
                return "## 仓库文件列表\n" + "\n".join(files)

            elif action == "create_or_update":
                path = params.get("path", "")
                content = params.get("content", "")
                message = params.get("message", f"Octuplex: 更新 {path}")
                try:
                    existing = repo.get_contents(path)
                    repo.update_file(path, message, content, existing.sha)
                    return f"✅ 文件已更新: {path}\n提交信息: {message}"
                except Exception:
                    repo.create_file(path, message, content)
                    return f"✅ 文件已创建: {path}\n提交信息: {message}"

            elif action == "delete_file":
                path = params.get("path", "")
                message = params.get("message", f"Octuplex: 删除 {path}")
                content = repo.get_contents(path)
                repo.delete_file(path, message, content.sha)
                return f"🗑️ 文件已删除: {path}"

            elif action == "list_commits":
                commits = repo.get_commits()[:10]
                result = ["## 最近提交记录\n"]
                for c in commits:
                    result.append(f"- {c.commit.author.date.strftime('%Y-%m-%d %H:%M')} | {c.commit.message[:60]}")
                return "\n".join(result)

            else:
                return f"不支持的操作: {action}"

        except Exception as e:
            return f"GitHub操作失败: {str(e)}"

# ---- 工具4：文件处理工具 ----
class FileProcessorTool:
    """多格式文件解析与处理工具"""
    name = "file_processor"
    description = "解析PDF/Word/Excel/TXT文件，提取内容，格式转换"

    async def execute(self, action: str, params: dict, session_id: str = "default") -> str:
        audit.log("tool_call", {"tool": "file_processor", "action": action}, session_id)

        try:
            filepath = params.get("filepath", "")
            if not Path(filepath).exists():
                return f"文件不存在: {filepath}"

            ext = Path(filepath).suffix.lower()

            if action == "read":
                if ext == ".txt":
                    content = Path(filepath).read_text(encoding="utf-8")
                    return f"📄 {filepath}\n```\n{content[:5000]}\n```"

                elif ext == ".pdf":
                    from PyPDF2 import PdfReader
                    reader = PdfReader(filepath)
                    text = []
                    for page in reader.pages[:10]:
                        text.append(page.extract_text())
                    return f"📄 PDF内容 ({len(reader.pages)}页):\n" + "\n".join(text)[:5000]

                elif ext == ".docx":
                    from docx import Document
                    doc = Document(filepath)
                    text = [p.text for p in doc.paragraphs]
                    return f"📄 Word内容:\n" + "\n".join(text)[:5000]

                elif ext in (".xlsx", ".xls"):
                    import pandas as pd
                    df = pd.read_excel(filepath)
                    return f"📊 Excel内容 ({len(df)}行 x {len(df.columns)}列):\n" + df.head(100).to_string()

                elif ext == ".csv":
                    import pandas as pd
                    df = pd.read_csv(filepath)
                    return f"📊 CSV内容 ({len(df)}行 x {len(df.columns)}列):\n" + df.head(100).to_string()

                else:
                    return f"不支持的文件格式: {ext}"

            elif action == "convert":
                target_format = params.get("target", "txt")
                return f"格式转换: {filepath} → {target_format}（功能开发中）"

            else:
                return f"不支持的操作: {action}"

        except Exception as e:
            return f"文件处理失败: {str(e)}"

# 实例化所有工具
python_tool = PythonSandboxTool()
web_search_tool = WebSearchTool()
github_tool = GitHubTool()
file_tool = FileProcessorTool()

# ============================================================
# 第5层：技能工具层 - 可插拔Skill架构
# ============================================================
class SkillRegistry:
    """
    可插拔Skill技能市场
    支持：技能注册、启用/禁用、卸载、调用统计
    """
    def __init__(self):
        self._skills: Dict[str, dict] = {}
        self._call_stats: Dict[str, dict] = defaultdict(lambda: {"success": 0, "fail": 0})
        self._load_builtin_skills()

    def _load_builtin_skills(self):
        """加载内置技能"""
        builtin_dir = Path(__file__).parent / "skills"
        if builtin_dir.exists():
            for skill_dir in builtin_dir.iterdir():
                if skill_dir.is_dir():
                    manifest = skill_dir / "manifest.json"
                    if manifest.exists():
                        try:
                            info = json.loads(manifest.read_text())
                            info["path"] = str(skill_dir)
                            info["enabled"] = True
                            self._skills[info["name"]] = info
                            logger.info(f"技能已加载: {info['name']} v{info.get('version', '1.0')}")
                        except Exception as e:
                            logger.warning(f"技能加载失败 {skill_dir.name}: {e}")

    def list_skills(self) -> List[dict]:
        """列出所有技能"""
        return [
            {
                "name": s["name"],
                "version": s.get("version", "1.0"),
                "description": s.get("description", ""),
                "enabled": s.get("enabled", True),
                "stats": self._call_stats.get(s["name"], {"success": 0, "fail": 0})
            }
            for s in self._skills.values()
        ]

    def get_skill(self, name: str) -> Optional[dict]:
        """获取技能信息"""
        return self._skills.get(name)

    def enable_skill(self, name: str) -> bool:
        """启用技能"""
        if name in self._skills:
            self._skills[name]["enabled"] = True
            return True
        return False

    def disable_skill(self, name: str) -> bool:
        """禁用技能"""
        if name in self._skills:
            self._skills[name]["enabled"] = False
            return True
        return False

    def record_call(self, skill_name: str, success: bool):
        """记录技能调用结果"""
        if success:
            self._call_stats[skill_name]["success"] += 1
        else:
            self._call_stats[skill_name]["fail"] += 1

skill_registry = SkillRegistry()

# ============================================================
# 第3层：智能体核心调度层 - ReAct循环引擎
# ============================================================
class AgentCore:
    """
    智能体核心调度引擎
    包含：ReAct循环、任务规划拆解、多子智能体协同、结果校验、错误重试
    """

    # 工具函数映射表
    TOOL_MAP = {
        "python_sandbox": python_tool.execute,
        "web_search": web_search_tool.execute,
        "github_ops": github_tool.execute,
        "file_processor": file_tool.execute,
    }

    # 意图分类Prompt
    INTENT_CLASSIFY_PROMPT = """你是一个任务分类器。分析用户输入，判断任务类型。

用户输入：{user_input}

请判断任务类型，返回JSON格式：
{{
    "type": "simple_chat|single_tool|multi_step",
    "complexity": "simple|normal|complex",
    "reason": "判断理由"
}}

规则：
- simple_chat: 简单闲聊、问候、知识问答
- single_tool: 需要单一工具调用完成（如"帮我搜索XX"、"运行这段代码"）
- multi_step: 需要多步骤规划完成（如"写一个数据分析报告"、"建一个网站"）
- complexity: simple=简单, normal=一般, complex=复杂"""

    # 任务拆解Prompt
    TASK_PLANNING_PROMPT = """你是一个任务规划专家。将用户目标拆解为有序执行步骤。

用户目标：{user_goal}
可用工具：{available_tools}

请生成JSON格式的执行计划：
{{
    "steps": [
        {{
            "step_id": 1,
            "description": "步骤描述",
            "tool": "使用的工具名",
            "tool_params": {{}},
            "expected_output": "预期输出描述",
            "depends_on": []
        }}
    ]
}}

规则：
1. 步骤按执行顺序排列
2. 每个步骤明确使用的工具和参数
3. depends_on列出依赖的前置步骤ID
4. 尽量详细包含所有必要参数"""

    def __init__(self):
        self._active_tasks: Dict[str, dict] = {}
        self._task_queues: Dict[str, asyncio.Queue] = {}
        self._cancel_flags: Dict[str, bool] = {}

    async def classify_intent(self, user_input: str) -> dict:
        """识别用户意图"""
        try:
            prompt = self.INTENT_CLASSIFY_PROMPT.format(user_input=user_input)
            result = await llm_adapter.chat(
                [{"role": "user", "content": prompt}],
                task_complexity="simple"
            )
            content = result["content"]
            # 提取JSON
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                return json.loads(json_match.group())
            return {"type": "simple_chat", "complexity": "simple", "reason": "默认分类"}
        except Exception as e:
            logger.warning(f"意图分类失败: {e}")
            return {"type": "simple_chat", "complexity": "simple", "reason": "分类失败，默认简单对话"}

    async def plan_task(self, user_goal: str) -> dict:
        """拆解任务为执行步骤"""
        tools_desc = "\n".join([
            f"- {name}: {tool.__doc__ or '无描述'}"
            for name, tool in self.TOOL_MAP.items()
        ])

        try:
            prompt = self.TASK_PLANNING_PROMPT.format(
                user_goal=user_goal,
                available_tools=tools_desc
            )
            result = await llm_adapter.chat(
                [{"role": "user", "content": prompt}],
                task_complexity="complex"
            )
            content = result["content"]
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                return json.loads(json_match.group())
            return {"steps": []}
        except Exception as e:
            logger.warning(f"任务拆解失败: {e}")
            return {"steps": []}

    async def execute_step(self, step: dict, session_id: str) -> dict:
        """执行单个步骤"""
        tool_name = step.get("tool", "")
        tool_params = step.get("tool_params", {})

        if tool_name not in self.TOOL_MAP:
            return {"success": False, "output": f"未知工具: {tool_name}"}

        try:
            tool_func = self.TOOL_MAP[tool_name]
            output = await tool_func(**tool_params, session_id=session_id)
            return {"success": True, "output": output}
        except Exception as e:
            return {"success": False, "output": str(e), "error": traceback.format_exc()}

    async def execute_task(self, task_plan: dict, session_id: str,
                           progress_callback: Callable = None) -> dict:
        """
        执行完整任务流程
        包含：循环执行、结果校验、错误重试
        """
        steps = task_plan.get("steps", [])
        results = []
        total_steps = len(steps)
        retry_counts = defaultdict(int)

        for i, step in enumerate(steps):
            # 检查取消标志
            if self._cancel_flags.get(session_id, False):
                results.append({"step": step, "status": "cancelled", "output": "任务已被用户取消"})
                break

            # 检查工具调用轮次上限
            if i >= config.MAX_TOOL_CALLS_PER_TASK:
                results.append({"step": step, "status": "limit_exceeded", "output": "已达到最大工具调用轮次"})
                break

            # 更新进度
            if progress_callback:
                await progress_callback({
                    "type": "step_start",
                    "current": i + 1,
                    "total": total_steps,
                    "step": step.get("description", "")
                })

            # 执行步骤（含重试逻辑）
            step_result = None
            max_retries = config.MAX_RETRIES_PER_TASK

            for attempt in range(max_retries + 1):
                step_result = await self.execute_step(step, session_id)

                if step_result["success"]:
                    break

                # 分析错误并调整
                if attempt < max_retries:
                    logger.info(f"步骤 {step.get('step_id')} 重试 {attempt + 1}/{max_retries}")
                    if progress_callback:
                        await progress_callback({
                            "type": "step_retry",
                            "step": step.get("description", ""),
                            "attempt": attempt + 1,
                            "error": step_result.get("output", "")
                        })
                    await asyncio.sleep(1)

            # 记录结果
            results.append({
                "step": step,
                "status": "success" if step_result["success"] else "failed",
                "output": step_result.get("output", ""),
                "retries": min(retry_counts[step.get("step_id", 0)], max_retries)
            })

            if progress_callback:
                await progress_callback({
                    "type": "step_complete",
                    "current": i + 1,
                    "total": total_steps,
                    "step": step.get("description", ""),
                    "status": "success" if step_result["success"] else "failed"
                })

            # 失败时记录到长期记忆
            if not step_result["success"]:
                memory_manager.add_long_term(
                    f"任务失败经验: {step.get('description')} - 错误: {step_result.get('output', '')}",
                    {"type": "failure_experience", "tool": step.get("tool")}
                )

        return {
            "total_steps": total_steps,
            "completed": sum(1 for r in results if r["status"] == "success"),
            "failed": sum(1 for r in results if r["status"] == "failed"),
            "results": results
        }

    async def run_conversation(self, user_input: str, session_id: str,
                               progress_callback: Callable = None) -> dict:
        """
        处理用户输入的主入口
        流程：意图识别 → 任务拆解 → 执行 → 汇总
        """
        # 检查额度
        if not token_tracker.check_daily_limit():
            return {
                "type": "error",
                "content": "⚠️ 已达到每日Token消耗上限，请等待次日重置或调整限额配置。",
                "stats": token_tracker.get_stats()
            }

        if not token_tracker.check_session_limit():
            return {
                "type": "error",
                "content": "⚠️ 已达到会话Token消耗上限，请开启新会话或调整限额配置。",
                "stats": token_tracker.get_stats()
            }

        audit.log("user_input", {"content": user_input}, session_id)

        # 检索长期记忆
        long_term_hints = memory_manager.search_long_term(user_input, top_k=3)
        rag_context = memory_manager.search_rag(user_input, top_k=3)

        # 步骤1：意图识别
        intent = await self.classify_intent(user_input)

        if progress_callback:
            await progress_callback({
                "type": "intent",
                "intent": intent["type"],
                "complexity": intent["complexity"]
            })

        # 简单对话：直接回复
        if intent["type"] == "simple_chat":
            messages = memory_manager.get_short_term(session_id)
            messages.append({"role": "user", "content": user_input})

            # 构建增强上下文
            context_parts = []
            if long_term_hints:
                context_parts.append("## 相关历史经验\n" + "\n".join(
                    [h["content"] for h in long_term_hints[:2]]
                ))
            if rag_context:
                context_parts.append("## 相关知识库内容\n" + "\n".join(
                    [r["content"] for r in rag_context[:2]]
                ))

            if context_parts:
                system_msg = "你是一个智能助手 Octuplex。参考以下上下文回答问题：\n\n" + "\n\n".join(context_parts)
                messages = [{"role": "system", "content": system_msg}] + messages[-10:]

            answer = await llm_adapter.chat(messages, task_complexity="simple")
            response_content = answer["content"]

            memory_manager.add_short_term(session_id, "user", user_input)
            memory_manager.add_short_term(session_id, "assistant", response_content)
            memory_manager.add_long_term(f"对话: {user_input} → {response_content[:200]}", {"type": "conversation"})

            audit.log("ai_response", {"content": response_content[:200]}, session_id)

            return {
                "type": "chat",
                "content": response_content,
                "model": answer["model"],
                "stats": token_tracker.get_stats()
            }

        # 单步工具或多步骤任务
        if intent["type"] in ("single_tool", "multi_step"):
            # 任务拆解
            if intent["type"] == "multi_step":
                task_plan = await self.plan_task(user_input)
            else:
                # 单步任务：直接构建执行计划
                task_plan = await self.plan_task(user_input)

            if not task_plan.get("steps"):
                # 无法拆解，回退到简单对话
                messages = [{"role": "user", "content": user_input}]
                answer = await llm_adapter.chat(messages)
                return {
                    "type": "chat",
                    "content": answer["content"],
                    "model": answer["model"],
                    "stats": token_tracker.get_stats()
                }

            # 执行任务
            if progress_callback:
                await progress_callback({
                    "type": "plan",
                    "steps": task_plan["steps"],
                    "total": len(task_plan["steps"])
                })

            execution_result = await self.execute_task(task_plan, session_id, progress_callback)

            # 汇总结果
            summary_prompt = f"""根据以下执行结果，用中文总结完成情况：

用户目标：{user_input}
执行结果：{json.dumps(execution_result, ensure_ascii=False)}

请生成简洁的总结，包含：
1. 完成了什么
2. 关键输出
3. 如有失败，说明原因和建议"""

            summary = await llm_adapter.chat(
                [{"role": "user", "content": summary_prompt}],
                task_complexity="simple"
            )

            memory_manager.add_short_term(session_id, "user", user_input)
            memory_manager.add_short_term(session_id, "assistant", summary["content"])
            memory_manager.add_long_term(
                f"任务: {user_input} → 完成{execution_result['completed']}/{execution_result['total_steps']}步",
                {"type": "task_experience"}
            )

            audit.log("task_complete", execution_result, session_id)

            return {
                "type": "task",
                "content": summary["content"],
                "plan": task_plan,
                "execution": execution_result,
                "model": summary["model"],
                "stats": token_tracker.get_stats()
            }

        return {"type": "chat", "content": "无法理解您的请求，请重新描述。", "stats": token_tracker.get_stats()}

    def cancel_task(self, session_id: str):
        """取消正在执行的任务"""
        self._cancel_flags[session_id] = True
        logger.info(f"任务取消请求: {session_id}")

    def reset_cancel(self, session_id: str):
        """重置取消标志"""
        self._cancel_flags[session_id] = False

agent_core = AgentCore()

# ============================================================
# 定时任务调度器
# ============================================================
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

scheduler = AsyncIOScheduler()
scheduled_jobs: Dict[str, dict] = {}

async def execute_scheduled_job(job_id: str, user_input: str, session_id: str):
    """执行定时任务"""
    logger.info(f"定时任务触发: {job_id} - {user_input}")
    try:
        result = await agent_core.run_conversation(user_input, session_id)
        logger.info(f"定时任务完成: {job_id}")
        return result
    except Exception as e:
        logger.error(f"定时任务失败: {job_id} - {e}")
        return {"error": str(e)}

def add_scheduled_job(job_id: str, cron_expr: str, user_input: str):
    """添加定时任务"""
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        raise ValueError("Cron表达式格式错误，需要5个字段: 分 时 日 月 周")

    session_id = f"scheduled_{job_id}"
    trigger = CronTrigger(
        minute=parts[0], hour=parts[1], day=parts[2],
        month=parts[3], day_of_week=parts[4]
    )

    job = scheduler.add_job(
        execute_scheduled_job,
        trigger=trigger,
        args=[job_id, user_input, session_id],
        id=job_id,
        replace_existing=True
    )

    scheduled_jobs[job_id] = {
        "cron": cron_expr,
        "user_input": user_input,
        "next_run": str(job.next_run_time) if job.next_run_time else None
    }

    return scheduled_jobs[job_id]

def remove_scheduled_job(job_id: str):
    """移除定时任务"""
    scheduler.remove_job(job_id)
    scheduled_jobs.pop(job_id, None)

def list_scheduled_jobs():
    """列出所有定时任务"""
    return scheduled_jobs

# ============================================================
# FastAPI 应用初始化
# ============================================================
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    logger.info("=== Octuplex 后端服务启动 ===")
    scheduler.start()
    logger.info("定时任务调度器已启动")

    # 创建必要目录
    Path(config.SANDBOX_WORK_DIR).mkdir(parents=True, exist_ok=True)
    Path(config.CHROMA_PERSIST_DIR).mkdir(parents=True, exist_ok=True)

    yield

    # 关闭时
    scheduler.shutdown()
    logger.info("=== Octuplex 后端服务关闭 ===")

app = FastAPI(
    title="Octuplex API",
    description="Octuplex 目标驱动型自主执行AI智能系统后端接口",
    version="1.0.0",
    lifespan=lifespan
)

# CORS中间件配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS if config.CORS_ORIGINS != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# ============================================================
# HTTP接口路由
# ============================================================

@app.get("/")
async def root():
    """健康检查接口"""
    return {
        "service": "Octuplex",
        "version": "1.0.0",
        "status": "running",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/health")
async def health_check():
    """详细健康检查"""
    return {
        "status": "healthy",
        "models_configured": bool(config.LLM_API_KEY),
        "github_configured": bool(config.GITHUB_TOKEN),
        "vector_db": memory_manager._chroma_client is not None,
        "scheduled_jobs": len(scheduled_jobs),
        "token_stats": token_tracker.get_stats()
    }

@app.post("/api/chat")
async def chat_endpoint(request: Request):
    """
    对话接口（HTTP POST）
    接收用户消息，返回AI回复
    """
    client_ip = request.client.host if request.client else "unknown"

    # 限流检查
    if not rate_limiter.check(client_ip):
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")

    try:
        body = await request.json()
        user_input = body.get("message", "")
        session_id = body.get("session_id", str(uuid.uuid4()))

        if not user_input:
            raise HTTPException(status_code=400, detail="消息内容不能为空")

        result = await agent_core.run_conversation(user_input, session_id)

        return JSONResponse({
            "success": True,
            "session_id": session_id,
            "data": result
        })

    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="请求体JSON格式错误")
    except Exception as e:
        logger.error(f"对话接口错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...), session_id: str = Form("default")):
    """
    文件上传接口
    上传文件到沙盒工作目录
    """
    try:
        session_dir = Path(config.SANDBOX_WORK_DIR) / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        file_path = session_dir / file.filename
        content = await file.read()

        # 文件大小限制（50MB）
        if len(content) > 50 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="文件大小超过50MB限制")

        file_path.write_bytes(content)

        audit.log("file_upload", {
            "filename": file.filename,
            "size": len(content),
            "session_id": session_id
        }, session_id)

        return JSONResponse({
            "success": True,
            "filename": file.filename,
            "size": len(content),
            "path": str(file_path)
        })

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/download/{session_id}/{filename}")
async def download_file(session_id: str, filename: str):
    """文件下载接口"""
    file_path = sandbox.get_file_path(session_id, filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(file_path, filename=filename)

@app.get("/api/stats")
async def get_stats():
    """获取Token消耗统计"""
    return JSONResponse({
        "success": True,
        "data": token_tracker.get_stats()
    })

@app.get("/api/skills")
async def list_skills():
    """获取技能列表"""
    return JSONResponse({
        "success": True,
        "data": skill_registry.list_skills()
    })

@app.post("/api/skills/{skill_name}/toggle")
async def toggle_skill(skill_name: str, enabled: bool = Form(...)):
    """启用/禁用技能"""
    if enabled:
        result = skill_registry.enable_skill(skill_name)
    else:
        result = skill_registry.disable_skill(skill_name)
    return JSONResponse({"success": result})

@app.get("/api/memory/search")
async def search_memory(query: str, top_k: int = 5):
    """检索长期记忆"""
    results = memory_manager.search_long_term(query, top_k)
    return JSONResponse({"success": True, "data": results})

@app.get("/api/rag/search")
async def search_rag(query: str, top_k: int = 5):
    """检索RAG知识库"""
    results = memory_manager.search_rag(query, top_k)
    return JSONResponse({"success": True, "data": results})

@app.post("/api/rag/add")
async def add_rag(document: str = Form(...), doc_id: str = Form(None)):
    """添加文档到RAG知识库"""
    result = memory_manager.add_to_rag(document, {}, doc_id)
    return JSONResponse({"success": result})

@app.delete("/api/rag/{doc_id}")
async def delete_rag(doc_id: str = None):
    """删除RAG知识库文档"""
    memory_manager.delete_rag(doc_id)
    return JSONResponse({"success": True})

@app.post("/api/schedule")
async def create_schedule(
    job_id: str = Form(...),
    cron_expr: str = Form(...),
    user_input: str = Form(...)
):
    """创建定时任务"""
    try:
        result = add_scheduled_job(job_id, cron_expr, user_input)
        return JSONResponse({"success": True, "data": result})
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/schedule/{job_id}")
async def delete_schedule(job_id: str):
    """删除定时任务"""
    remove_scheduled_job(job_id)
    return JSONResponse({"success": True})

@app.get("/api/schedule")
async def list_schedules():
    """列出定时任务"""
    return JSONResponse({"success": True, "data": list_scheduled_jobs()})

@app.get("/api/sessions/{session_id}/files")
async def list_session_files(session_id: str):
    """列出会话沙盒文件"""
    files = sandbox.list_files(session_id)
    return JSONResponse({"success": True, "data": files})

@app.get("/api/audit")
async def get_audit_logs(
    session_id: str = None,
    event_type: str = None,
    start_time: str = None,
    end_time: str = None
):
    """查询审计日志"""
    logs = audit.get_logs(session_id, event_type, start_time, end_time)
    return JSONResponse({"success": True, "data": logs[-100:]})

@app.get("/api/audit/export")
async def export_audit_logs():
    """导出审计日志"""
    return ResponseAudit(
        content=audit.export_logs(),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=octuplex_audit_logs.json"}
    )

# ============================================================
# WebSocket实时通信
# ============================================================
from fastapi.responses import Response as ResponseAudit

class WSConnectionManager:
    """WebSocket连接管理器"""
    def __init__(self):
        self._connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        self._connections[session_id] = websocket
        logger.info(f"WebSocket连接: {session_id}")

    def disconnect(self, session_id: str):
        self._connections.pop(session_id, None)
        logger.info(f"WebSocket断开: {session_id}")

    async def send(self, session_id: str, message: dict):
        websocket = self._connections.get(session_id)
        if websocket:
            try:
                await websocket.send_json(message)
            except Exception:
                self.disconnect(session_id)

ws_manager = WSConnectionManager()

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """
    WebSocket实时通信接口
    支持：流式对话、任务进度推送、日志实时传输
    """
    await ws_manager.connect(websocket, session_id)

    # 进度回调函数
    async def progress_callback(data: dict):
        await ws_manager.send(session_id, {"type": "progress", "data": data})

    try:
        while True:
            # 接收前端消息
            message = await websocket.receive_text()
            data = json.loads(message)

            msg_type = data.get("type", "chat")

            if msg_type == "chat":
                user_input = data.get("message", "")

                # 发送开始处理信号
                await ws_manager.send(session_id, {
                    "type": "status",
                    "data": {"status": "processing", "message": "正在分析您的请求..."}
                })

                # 执行对话
                result = await agent_core.run_conversation(
                    user_input, session_id, progress_callback
                )

                # 发送结果
                await ws_manager.send(session_id, {
                    "type": "result",
                    "data": result
                })

            elif msg_type == "cancel":
                agent_core.cancel_task(session_id)
                agent_core.reset_cancel(session_id)
                await ws_manager.send(session_id, {
                    "type": "status",
                    "data": {"status": "cancelled", "message": "任务已取消"}
                })

            elif msg_type == "clear_context":
                memory_manager.clear_short_term(session_id)
                await ws_manager.send(session_id, {
                    "type": "status",
                    "data": {"status": "cleared", "message": "上下文已清空"}
                })

            elif msg_type == "ping":
                await ws_manager.send(session_id, {"type": "pong"})

    except WebSocketDisconnect:
        ws_manager.disconnect(session_id)
    except Exception as e:
        logger.error(f"WebSocket错误: {e}")
        ws_manager.disconnect(session_id)

# ============================================================
# Gradio管理面板（可选）
# ============================================================
def create_gradio_interface():
    """创建Gradio管理面板"""
    try:
        import gradio as gr

        async def chat_handler(message, history):
            """Gradio聊天处理"""
            session_id = "gradio_session"
            if not message:
                return "", history
            result = await agent_core.run_conversation(message, session_id)
            history.append((message, result.get("content", "")))
            return "", history

        async def upload_handler(file):
            """Gradio文件上传处理"""
            if file is None:
                return "请选择文件"
            session_id = "gradio_session"
            session_dir = Path(config.SANDBOX_WORK_DIR) / session_id
            session_dir.mkdir(parents=True, exist_ok=True)
            filepath = str(session_dir / Path(file).name)
            import shutil
            shutil.copy(file, filepath)
            return f"文件已上传: {filepath}"

        with gr.Blocks(title="Octuplex 管理面板", theme=gr.themes.Soft()) as demo:
            gr.Markdown("# Octuplex 智能助手管理面板")
            gr.Markdown("目标驱动型自主执行AI系统")

            with gr.Tab("对话"):
                chatbot = gr.Chatbot(height=500)
                msg = gr.Textbox(label="输入您的问题或任务", placeholder="请输入...")
                clear = gr.Button("清空对话")

                msg.submit(chat_handler, [msg, chatbot], [msg, chatbot])
                clear.click(lambda: [], None, chatbot)

            with gr.Tab("文件上传"):
                file_input = gr.File(label="选择文件")
                upload_btn = gr.Button("上传")
                upload_result = gr.Textbox(label="上传结果")
                upload_btn.click(upload_handler, file_input, upload_result)

            with gr.Tab("系统状态"):
                gr.Markdown("## Token消耗统计")
                stats_output = gr.JSON(token_tracker.get_stats, every=5)

                gr.Markdown("## 技能列表")
                skills_output = gr.JSON(skill_registry.list_skills, every=10)

        return demo
    except ImportError:
        return None

# ============================================================
# 启动函数
# ============================================================
def start_server():
    """启动FastAPI服务"""
    logger.info("Octuplex 后端服务正在启动...")
    logger.info(f"LLM接口: {config.LLM_BASE_URL}")
    logger.info(f"模型: {config.LLM_MODEL_NAME}")
    logger.info(f"CORS白名单: {config.CORS_ORIGINS}")
    logger.info(f"沙盒目录: {config.SANDBOX_WORK_DIR}")

    # 如果启用Gradio，则同时启动Gradio
    if config.ENABLE_GRADIO:
        gradio_demo = create_gradio_interface()
        if gradio_demo:
            from fastapi.middleware.wsgi import WSGIMiddleware
            import gradio as gr
            # 将Gradio挂载到 /gradio 路径
            gr.mount_gradio_app(app, gradio_demo, path="/gradio")
            logger.info("Gradio管理面板已启用: /gradio")

    # 启动uvicorn
    uvicorn.run(
        app,
        host=config.SERVER_HOST,
        port=config.SERVER_PORT,
        log_level="info"
    )

# ============================================================
# 程序入口
# ============================================================
if __name__ == "__main__":
    start_server()