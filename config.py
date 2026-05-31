"""配置管理模块。从 .env 文件和环境变量加载所有配置项。

模块在 import 时不会因缺少 .env 中的必需配置而报错（所有字段均有默认值）。
调用 validate_config() 可在启动时提前检查必需项是否已设置。
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件（优先从项目根目录）
BASE_DIR = Path(__file__).resolve().parent
env_path = BASE_DIR / ".env"
load_dotenv(dotenv_path=env_path)


def _get_env(key: str, default: str = "") -> str:
    """读取环境变量，若不存在返回默认值（默认空字符串）。"""
    return os.getenv(key, default)


def _get_env_int(key: str, default: int) -> int:
    """读取整数类型的环境变量。"""
    return int(os.getenv(key, str(default)))


def _get_env_float(key: str, default: float) -> float:
    """读取浮点类型的环境变量。"""
    return float(os.getenv(key, str(default)))


# ---- 邮件配置 ----
MAIL_HOST = _get_env("MAIL_HOST", "mail.ustc.edu.cn")
MAIL_PORT = _get_env_int("MAIL_PORT", 993)
MAIL_USERNAME = _get_env("MAIL_USERNAME")
MAIL_PASSWORD = _get_env("MAIL_PASSWORD")
MAIL_FOLDER = _get_env("MAIL_FOLDER", "INBOX")
MAIL_SEARCH_DAYS = _get_env_int("MAIL_SEARCH_DAYS", 7)

# ---- Anthropic API (支持第三方兼容 API) ----
ANTHROPIC_API_KEY = _get_env("ANTHROPIC_API_KEY")
ANTHROPIC_BASE_URL = _get_env("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
ANTHROPIC_MODEL = _get_env("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# ---- DDL 提取参数 ----
DDL_CONFIDENCE_THRESHOLD = _get_env_float("DDL_CONFIDENCE_THRESHOLD", 0.6)

# ---- 输出配置 ----
OUTPUT_DIR = Path(_get_env("OUTPUT_DIR", "./output"))
OUTPUT_FILENAME = _get_env("OUTPUT_FILENAME", "ddl_events_{date}.ics")

# ---- 数据库配置 ----
DB_PATH = _get_env("DB_PATH", "./data/mail_cache.db")

# ---- 日志 ----
LOG_LEVEL = _get_env("LOG_LEVEL", "INFO")


def validate_config() -> list[str]:
    """检查必需配置项是否已设置，返回缺失项列表。

    Returns:
        缺失的配置项描述列表。空列表表示所有必需项均已正确设置。
    """
    missing = []

    if not MAIL_USERNAME:
        missing.append("MAIL_USERNAME (USTC 邮箱用户名)")
    if not MAIL_PASSWORD:
        missing.append("MAIL_PASSWORD (USTC 邮箱密码)")
    if not ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY (Claude API 密钥)")

    return missing