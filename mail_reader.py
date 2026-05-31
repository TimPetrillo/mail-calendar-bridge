"""邮件读取模块。通过 IMAP SSL 连接 USTC 邮箱，搜索并解析邮件内容。

处理 Coremail 邮件系统的中文编码（Base64 / Quoted-Printable 主题），
将 HTML 邮件正文转换为纯文本供 LLM 分析。
"""

import email
import email.message
import logging
import imaplib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, date
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from typing import Optional

from bs4 import BeautifulSoup

import config

logger = logging.getLogger(__name__)


@dataclass
class EmailRecord:
    """从 IMAP 解析出的邮件结构化数据。"""
    uid: str                          # IMAP 唯一标识符
    message_id: str                   # RFC 822 Message-ID
    subject: str                      # 解码后的邮件主题
    from_address: str                 # 发件人地址
    from_name: str                    # 发件人名称（如有）
    date: datetime                    # 邮件发送日期
    body_text: str                    # 纯文本正文
    body_html: Optional[str] = None   # HTML 正文（仅保留给高级分析使用）


def _decode_mime_header(raw: str) -> str:
    """解码 MIME 编码的邮件头（处理中文 Base64 / QP 编码）。

    例如：'=?UTF-8?B?5pyq5p2l5Lyg5Lq6?=' → '未来传人'
    """
    if raw is None:
        return ""
    try:
        parts = decode_header(raw)
        return str(make_header(parts))
    except Exception:
        # 解码失败时返回原始字符串
        return raw


def _extract_body(msg: email.message.Message) -> tuple[str, Optional[str]]:
    """从 MIME 消息中提取纯文本和 HTML 正文。

    优先使用 text/plain 部分；若只有 text/html，用 BeautifulSoup 转为纯文本。

    Returns:
        (plain_text, html_or_none): 纯文本正文和可选的 HTML 正文。
    """
    text_parts: list[str] = []
    html_parts: list[str] = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))

            # 跳过附件
            if "attachment" in disposition:
                continue

            try:
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                charset = part.get_content_charset() or "utf-8"
                decoded = payload.decode(charset, errors="replace")
            except Exception:
                continue

            if content_type == "text/plain":
                text_parts.append(decoded)
            elif content_type == "text/html":
                html_parts.append(decoded)
    else:
        # 非 multipart 邮件
        content_type = msg.get_content_type()
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                decoded = payload.decode(charset, errors="replace")
                if content_type == "text/plain":
                    text_parts.append(decoded)
                elif content_type == "text/html":
                    html_parts.append(decoded)
        except Exception:
            pass

    plain_text = "\n".join(text_parts).strip()
    html_text = "\n".join(html_parts).strip() if html_parts else None

    # 如果只有 HTML，转为纯文本
    if not plain_text and html_text:
        try:
            soup = BeautifulSoup(html_text, "lxml")
            plain_text = soup.get_text(separator="\n", strip=True)
        except Exception:
            plain_text = html_text  # 降级：保留原始 HTML

    # 截断超长正文，避免 LLM token 浪费
    max_length = 5000
    if len(plain_text) > max_length:
        plain_text = plain_text[:max_length] + "\n\n[邮件正文过长，已截断]"

    return plain_text, (html_text if html_parts else None)


def _parse_date(date_str: Optional[str]) -> datetime:
    """解析邮件日期字符串为 datetime 对象。"""
    if not date_str:
        return datetime.now()
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        logger.warning("无法解析邮件日期: %s，使用当前时间", date_str)
        return datetime.now()


class MailReader:
    """USTC 邮箱 IMAP 读取器。"""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        folder: str | None = None,
    ):
        self.host = host or config.MAIL_HOST
        self.port = port or config.MAIL_PORT
        self.username = username or config.MAIL_USERNAME
        self.password = password or config.MAIL_PASSWORD
        self.folder = folder or config.MAIL_FOLDER
        self._conn: imaplib.IMAP4_SSL | None = None

    def connect(self) -> None:
        """建立 IMAP SSL 连接并登录。"""
        logger.info("正在连接 %s:%d ...", self.host, self.port)
        self._conn = imaplib.IMAP4_SSL(self.host, self.port)
        self._conn.login(self.username, self.password)
        logger.info("IMAP 登录成功 (用户: %s)", self.username)

    def disconnect(self) -> None:
        """关闭 IMAP 连接。"""
        if self._conn:
            try:
                self._conn.logout()
            except Exception:
                pass
            self._conn = None
            logger.info("IMAP 连接已关闭")

    def fetch_emails(self, search_days: int | None = None) -> list[EmailRecord]:
        """搜索并返回最近 N 天的邮件列表。

        Args:
            search_days: 搜索范围（天），默认使用配置中的 MAIL_SEARCH_DAYS。

        Returns:
            解析后的 EmailRecord 列表，按日期从旧到新排列。
        """
        if self._conn is None:
            raise RuntimeError("IMAP 未连接，请先调用 connect()")

        days = search_days if search_days is not None else config.MAIL_SEARCH_DAYS

        # 选择文件夹
        status, _ = self._conn.select(self.folder, readonly=True)
        if status != "OK":
            raise RuntimeError(f"无法选择邮件文件夹: {self.folder}")

        # 按日期搜索
        since_date = (date.today() - timedelta(days=days)).strftime("%d-%b-%Y")
        logger.info("搜索 %s 以来 (近 %d 天) 的邮件...", since_date, days)

        status, msg_ids = self._conn.search(None, f'(SINCE "{since_date}")')
        if status != "OK":
            raise RuntimeError("IMAP 搜索失败")

        uid_list = msg_ids[0].split()
        if not uid_list:
            logger.info("未找到新邮件")
            return []

        logger.info("找到 %d 封邮件，开始解析...", len(uid_list))

        # 批量获取邮件
        uids_str = b",".join(uid_list)
        status, msg_data = self._conn.fetch(uids_str, "(RFC822)")

        emails: list[EmailRecord] = []
        for i, uid in enumerate(uid_list):
            try:
                record = self._parse_single_email(uid.decode(), msg_data, i)
                if record:
                    emails.append(record)
            except Exception:
                logger.exception("解析邮件失败 (UID: %s)，跳过", uid.decode())

        # 按日期排序：从旧到新
        emails.sort(key=lambda e: e.date)
        logger.info("成功解析 %d 封邮件", len(emails))
        return emails

    def _parse_single_email(
        self, uid_str: str, raw_data: list, index: int
    ) -> Optional[EmailRecord]:
        """解析单封邮件为 EmailRecord。

        注意：imaplib 的 fetch 返回格式为 [b'1 (RFC822 {N}', b'...raw...'), b')']。
        这里用简单的索引方式解析。
        """
        # IMAP fetch 响应对批量 UID 的格式是扁平的列表
        try:
            # IMAP fetch 返回的 raw_data 是一个扁平列表：
            # [(b'UID (RFC822 {size}', b'raw_message'), b')', ...]
            # 先收集所有邮件数据 tuple，再按 index 取对应的那封
            raw_email = None
            if isinstance(raw_data, list):
                email_data_items: list[bytes] = []
                for item in raw_data:
                    if isinstance(item, tuple) and len(item) == 2:
                        email_data_items.append(item[1])

                if index < len(email_data_items):
                    raw_email = email_data_items[index]

            if raw_email is None:
                logger.warning("无法从 IMAP 响应中提取邮件数据 (UID: %s)", uid_str)
                return None

            msg = email.message_from_bytes(raw_email)

            # 提取各字段
            subject = _decode_mime_header(msg.get("Subject", "(无主题)"))
            from_header = _decode_mime_header(msg.get("From", ""))
            message_id = msg.get("Message-ID", uid_str)
            date_val = _parse_date(msg.get("Date"))

            # 解析发件人
            from_name, from_address = self._parse_from_header(from_header)

            # 提取正文
            body_text, body_html = _extract_body(msg)

            if not body_text:
                logger.debug("邮件无正文内容 (UID: %s, 主题: %s)", uid_str, subject)

            return EmailRecord(
                uid=uid_str,
                message_id=message_id,
                subject=subject,
                from_address=from_address,
                from_name=from_name,
                date=date_val,
                body_text=body_text,
                body_html=body_html,
            )

        except Exception:
            logger.exception("解析邮件时发生异常 (UID: %s)", uid_str)
            return None

    @staticmethod
    def _parse_from_header(from_str: str) -> tuple[str, str]:
        """解析 From 头为 (名称, 地址) 元组。

        例如: '张三 <zhangsan@mail.ustc.edu.cn>' → ('张三', 'zhangsan@mail.ustc.edu.cn')
        """
        if not from_str:
            return ("", "")

        # 尝试用 email.utils 解析
        from email.utils import parseaddr
        name, addr = parseaddr(from_str)
        return (name or "", addr or from_str)

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False