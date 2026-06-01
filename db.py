"""数据库模块。使用 SQLite 追踪已处理的邮件和生成的日历事件。

提供去重逻辑：基于邮件 UID 判断是否已处理；基于内容哈希检测邮件内容变更。
"""

import json
import hashlib
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

import config

logger = logging.getLogger(__name__)

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mail_uid TEXT NOT NULL,
    message_id TEXT,
    subject TEXT,
    from_address TEXT,
    received_date TEXT,
    processed_at TEXT DEFAULT (datetime('now', 'localtime')),

    has_events INTEGER DEFAULT 0,
    events_json TEXT,

    content_hash TEXT,

    UNIQUE(mail_uid)
);

CREATE TABLE IF NOT EXISTS calendar_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ics_uid TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    start_datetime TEXT NOT NULL,
    end_datetime TEXT,
    event_type TEXT,
    confidence REAL,
    source_mail_uid TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (source_mail_uid) REFERENCES processed_emails(mail_uid)
);

CREATE INDEX IF NOT EXISTS idx_processed_emails_message_id
ON processed_emails(message_id);
"""


class Database:
    """SQLite 数据库操作封装。"""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or config.DB_PATH
        self._conn: sqlite3.Connection | None = None

    def _ensure_dir(self) -> None:
        """确保数据库文件所在目录存在。"""
        db_file = Path(self.db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> None:
        """打开数据库连接并初始化表结构。"""
        self._ensure_dir()
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(DB_SCHEMA)
        self._conn.commit()
        logger.debug("数据库已初始化: %s", self.db_path)

    def disconnect(self) -> None:
        """关闭数据库连接。"""
        if self._conn:
            self._conn.close()
            self._conn = None

    def is_processed(self, mail_uid: str) -> bool:
        """检查邮件 UID 是否已处理过。"""
        if not self._conn:
            raise RuntimeError("数据库未连接")
        cursor = self._conn.execute(
            "SELECT 1 FROM processed_emails WHERE mail_uid = ?", (mail_uid,)
        )
        return cursor.fetchone() is not None

    def get_processed_uids(self) -> set[str]:
        """获取所有已处理邮件的 UID 集合。"""
        if not self._conn:
            raise RuntimeError("数据库未连接")
        cursor = self._conn.execute("SELECT mail_uid FROM processed_emails")
        return {row["mail_uid"] for row in cursor.fetchall()}

    def get_processed_message_ids(self) -> set[str]:
        """获取所有已处理邮件的 Message-ID 集合。"""
        if not self._conn:
            raise RuntimeError("数据库未连接")
        cursor = self._conn.execute(
            "SELECT message_id FROM processed_emails WHERE message_id IS NOT NULL AND message_id != ''"
        )
        return {row["message_id"] for row in cursor.fetchall()}

    def mark_processed(
        self,
        mail_uid: str,
        message_id: str,
        subject: str,
        from_address: str,
        received_date: str,
        has_events: bool,
        events_json: str | None = None,
        content_hash: str | None = None,
    ) -> None:
        """记录一封邮件已处理。使用 INSERT OR REPLACE 处理重复情况。"""
        if not self._conn:
            raise RuntimeError("数据库未连接")
        self._conn.execute(
            """INSERT OR REPLACE INTO processed_emails
               (mail_uid, message_id, subject, from_address, received_date,
                has_events, events_json, content_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                mail_uid,
                message_id,
                subject,
                from_address,
                received_date,
                1 if has_events else 0,
                events_json,
                content_hash,
            ),
        )
        self._conn.commit()

    def insert_calendar_event(
        self,
        ics_uid: str,
        title: str,
        start_datetime: str,
        end_datetime: Optional[str],
        event_type: str,
        confidence: float,
        source_mail_uid: str,
    ) -> bool:
        """插入一条日历事件记录。如果 ics_uid 已存在则跳过（返回 False）。"""
        if not self._conn:
            raise RuntimeError("数据库未连接")
        try:
            self._conn.execute(
                """INSERT INTO calendar_events
                   (ics_uid, title, start_datetime, end_datetime,
                    event_type, confidence, source_mail_uid)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    ics_uid,
                    title,
                    start_datetime,
                    end_datetime,
                    event_type,
                    confidence,
                    source_mail_uid,
                ),
            )
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            logger.debug("事件已存在，跳过: %s", ics_uid)
            return False

    def get_all_calendar_events(self) -> list[dict]:
        """获取数据库中所有日历事件。"""
        if not self._conn:
            raise RuntimeError("数据库未连接")
        cursor = self._conn.execute(
            "SELECT * FROM calendar_events ORDER BY start_datetime"
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_statistics(self) -> dict:
        """获取处理统计信息。"""
        if not self._conn:
            raise RuntimeError("数据库未连接")
        total_emails = self._conn.execute(
            "SELECT COUNT(*) as c FROM processed_emails"
        ).fetchone()["c"]
        emails_with_events = self._conn.execute(
            "SELECT COUNT(*) as c FROM processed_emails WHERE has_events = 1"
        ).fetchone()["c"]
        total_events = self._conn.execute(
            "SELECT COUNT(*) as c FROM calendar_events"
        ).fetchone()["c"]
        return {
            "total_emails_processed": total_emails,
            "emails_with_events": emails_with_events,
            "total_calendar_events": total_events,
        }

    @staticmethod
    def compute_content_hash(subject: str, body_text: str) -> str:
        """计算邮件内容的 SHA256 哈希（用于检测内容变更）。"""
        content = f"{subject}\n{body_text}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False