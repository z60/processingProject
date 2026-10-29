"""环境变量与静态配置（conf/、prompts/）加载。"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

PROMPT_VERSION_RE = re.compile(r"version:\s*([A-Za-z0-9._-]+)")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _int_env(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    env: str
    host: str
    port: int

    mysql_host: str
    mysql_port: int
    mysql_user: str
    mysql_password: str
    mysql_db: str
    mysql_connect_timeout: int

    qdrant_url: str
    qdrant_collection: str
    qdrant_dim: int
    qdrant_timeout: int

    embedding_base_url: str
    embedding_model: str
    embedding_dim: int
    embedding_batch: int
    embedding_timeout: int

    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_temperature: float
    llm_timeout: int

    prompts_dir: Path
    conf_dir: Path
    seed_dir: Path
    data_dir: Path

    @property
    def llm_enabled(self) -> bool:
        """未配置 Key 时走离线脚本模型，保证链路可演示/可回归。"""
        return bool(self.llm_api_key and self.llm_model)


@lru_cache(maxsize=1)
def settings() -> Settings:
    data_dir = ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        env=_env("APP_ENV", "dev"),
        host=_env("APP_HOST", "0.0.0.0"),
        port=_int_env("APP_PORT", 8000),
        mysql_host=_env("MYSQL_HOST", "127.0.0.1"),
        mysql_port=_int_env("MYSQL_PORT", 3306),
        mysql_user=_env("MYSQL_USER", "root"),
        mysql_password=_env("MYSQL_PASSWORD", ""),
        mysql_db=_env("MYSQL_DB", "project1028"),
        mysql_connect_timeout=_int_env("MYSQL_CONNECT_TIMEOUT", 4),
        qdrant_url=_env("QDRANT_URL", "http://127.0.0.1:6333").rstrip("/"),
        qdrant_collection=_env("QDRANT_COLLECTION", "knowledge_chunks"),
        qdrant_dim=_int_env("QDRANT_DIM", 1024),
        qdrant_timeout=_int_env("QDRANT_TIMEOUT", 15),
        embedding_base_url=_env("EMBEDDING_BASE_URL", "http://127.0.0.1:8081/v1").rstrip("/"),
        embedding_model=_env("EMBEDDING_MODEL", "bge-m3"),
        embedding_dim=_int_env("EMBEDDING_DIM", 1024),
        embedding_batch=_int_env("EMBEDDING_BATCH", 16),
        embedding_timeout=_int_env("EMBEDDING_TIMEOUT", 60),
        llm_base_url=_env("LLM_BASE_URL", "").rstrip("/"),
        llm_api_key=_env("LLM_API_KEY", ""),
        llm_model=_env("LLM_MODEL", ""),
        llm_temperature=_float_env("LLM_TEMPERATURE", 0.0),
        llm_timeout=_int_env("LLM_TIMEOUT", 60),
        prompts_dir=ROOT / "prompts",
        conf_dir=ROOT / "conf",
        seed_dir=ROOT / "conf" / "seed",
        data_dir=data_dir,
    )


@lru_cache(maxsize=32)
def conf(name: str) -> dict:
    """读取 conf/<name>.json。"""
    path = settings().conf_dir / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"缺少配置文件: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=32)
def read_jsonl(path: Path) -> tuple[dict, ...]:
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    return tuple(json.loads(line) for line in lines if line)


def load_prompt(name: str) -> tuple[str, str]:
    """读取 prompts/<name>.md，返回 (正文, 版本号)。"""
    path = settings().prompts_dir / f"{name}.md"
    text = path.read_text(encoding="utf-8")
    match = PROMPT_VERSION_RE.search(text)
    return text, (match.group(1) if match else "unversioned")
