"""pytest 配置。为测试环境注入必要的环境变量，避免因缺少 .env 文件而失败。"""

import os
import sys
from pathlib import Path

# 将项目根目录加入 Python 路径
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

# 设置测试所需的环境变量（值均为测试用假数据）
os.environ.setdefault("MAIL_USERNAME", "test@mail.ustc.edu.cn")
os.environ.setdefault("MAIL_PASSWORD", "test_password")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-key-12345")
os.environ.setdefault("MAIL_SEARCH_DAYS", "7")
os.environ.setdefault("OUTPUT_DIR", "./output")
os.environ.setdefault("DB_PATH", "./data/test_mail_cache.db")