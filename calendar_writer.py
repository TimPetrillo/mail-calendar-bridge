"""日历写入模块。生成符合 RFC 5545 标准的 iCalendar (.ics) 文件。

支持两种写入模式：
- 累加模式 (append): 将新事件追加到现有 .ics 文件（默认）。
- 全量替换 (rebuild): 从数据库重建整个 .ics 文件。

生成的 .ics 文件可被 Android 日历 App 直接导入。
"""

import hashlib
import logging
import re
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from ics import Calendar, Event
from ics.alarm import DisplayAlarm

import config

logger = logging.getLogger(__name__)

# 北京时间时区
CST = timezone(timedelta(hours=8))


def _generate_ics_uid(source_mail_uid: str, title: str, start_dt: str) -> str:
    """基于邮件 UID + 标题 + 日期生成全局唯一的 iCalendar UID。

    使用 UUID5 (基于 SHA-1) 确保同一事件多次运行时 UID 不变，
    从而在导入日历时能正确去重。
    """
    namespace = uuid.NAMESPACE_DNS
    key = f"{source_mail_uid}|{title}|{start_dt}"
    return str(uuid.uuid5(namespace, key))


def _parse_datetime(dt_str: str) -> datetime:
    """解析 ISO 8601 日期时间字符串为 datetime 对象。

    支持格式:
    - '2026-06-05T14:00:00+08:00' (完整带时区)
    - '2026-06-05' (仅日期，视为北京时间 00:00)
    """
    if "T" in dt_str:
        # 处理时区偏移
        dt = datetime.fromisoformat(dt_str)
        return dt
    else:
        # 仅日期格式
        return datetime.strptime(dt_str, "%Y-%m-%d").replace(tzinfo=CST)


class CalendarWriter:
    """iCalendar 文件生成器。"""

    def __init__(
        self,
        output_dir: str | Path | None = None,
        output_filename: str | None = None,
    ):
        self.output_dir = Path(output_dir or config.OUTPUT_DIR)
        raw_filename = output_filename or config.OUTPUT_FILENAME
        # 支持 {date} 占位符，替换为当前日期 (YYYY-MM-DD)
        self.output_filename = raw_filename.replace(
            "{date}", datetime.now().strftime("%Y-%m-%d")
        )
        self.output_path = self.output_dir / self.output_filename

    def _ensure_output_dir(self) -> None:
        """确保输出目录存在。"""
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def append_events(self, events: list[dict]) -> int:
        """追加新事件到现有 .ics 文件。

        如果文件已存在，先解析现有日历；若解析失败则从空白日历开始。

        Args:
            events: 事件字典列表，每个字典包含 title, start_datetime,
                    end_datetime, is_all_day, location, description,
                    event_type, confidence, source_mail_uid, source_mail_subject。

        Returns:
            成功添加的事件数量。
        """
        self._ensure_output_dir()

        # 尝试加载现有日历
        calendar = Calendar()
        if self.output_path.exists():
            try:
                with open(self.output_path, "r", encoding="utf-8") as f:
                    existing_text = f.read()
                existing = Calendar(existing_text)
                calendar.events = set(existing.events)
                logger.debug("已加载现有日历: %d 个事件", len(calendar.events))
            except Exception as e:
                logger.warning("现有 .ics 文件解析失败，将重新生成: %s", e)

        added_count = 0
        for evt_dict in events:
            ics_event = self._build_event(evt_dict)
            if ics_event is None:
                continue

            # 检查是否已存在（按 UID 去重）
            existing_uids = {e.uid for e in calendar.events if e.uid}
            if ics_event.uid in existing_uids:
                logger.debug("事件已存在于日历中，跳过: %s", ics_event.uid)
                continue

            calendar.events.add(ics_event)
            added_count += 1

        if added_count > 0:
            self._write_calendar(calendar)
            logger.info("已追加 %d 个事件到 %s", added_count, self.output_path)
        else:
            logger.info("没有新事件需要追加")

        return added_count

    def rebuild_from_db(self, db_events: list[dict]) -> int:
        """从数据库事件列表完全重建 .ics 文件。

        Args:
            db_events: 来自 Database.get_all_calendar_events() 的事件列表。

        Returns:
            写入的事件数量。
        """
        self._ensure_output_dir()

        calendar = Calendar()
        count = 0

        for db_evt in db_events:
            evt_dict = {
                "title": db_evt.get("title", ""),
                "start_datetime": db_evt.get("start_datetime", ""),
                "end_datetime": db_evt.get("end_datetime"),
                "is_all_day": False,
                "location": None,
                "description": None,
                "event_type": db_evt.get("event_type", "other"),
                "confidence": db_evt.get("confidence", 0.0),
                "source_mail_uid": db_evt.get("source_mail_uid", ""),
                "source_mail_subject": "",
                "ics_uid": db_evt.get("ics_uid", ""),
            }
            ics_event = self._build_event(evt_dict)
            if ics_event:
                calendar.events.add(ics_event)
                count += 1

        self._write_calendar(calendar)
        logger.info("已重建日历: %d 个事件写入 %s", count, self.output_path)
        return count

    def _build_event(self, evt_dict: dict) -> Optional[Event]:
        """从事件字典构建 ics Event 对象。"""
        title = evt_dict.get("title", "")
        start_str = evt_dict.get("start_datetime", "")
        end_str = evt_dict.get("end_datetime")
        is_all_day = evt_dict.get("is_all_day", False)
        location = evt_dict.get("location", "")
        description = evt_dict.get("description", "")
        event_type = evt_dict.get("event_type", "other")
        confidence = evt_dict.get("confidence", 0.0)
        source_mail_uid = evt_dict.get("source_mail_uid", "")
        source_mail_subject = evt_dict.get("source_mail_subject", "")
        ics_uid = evt_dict.get("ics_uid", "")

        if not title or not start_str:
            logger.warning("事件缺少标题或开始时间，跳过")
            return None

        # 生成或使用已有 UID
        if not ics_uid:
            ics_uid = _generate_ics_uid(source_mail_uid, title, start_str)

        try:
            event = Event()
            event.uid = ics_uid
            event.name = title

            if is_all_day:
                # 全天事件：只设置日期
                dt = _parse_datetime(start_str)
                event.begin = dt.date()
                if end_str:
                    end_dt = _parse_datetime(end_str)
                    event.end = end_dt.date()
                else:
                    event.end = dt.date()
                event.make_all_day()
            else:
                # 有具体时间的事件
                event.begin = _parse_datetime(start_str)
                if end_str:
                    event.end = _parse_datetime(end_str)

            # 地点
            if location:
                event.location = location

            # 描述：组合类型、来源、置信度
            type_labels = {
                "homework_deadline": "作业截止",
                "exam": "考试",
                "meeting": "会议",
                "thesis": "论文/答辩",
                "registration": "报名/注册",
                "payment": "缴费",
                "activity": "活动",
                "other": "其他",
            }
            type_label = type_labels.get(event_type, event_type)

            desc_parts = []
            if description:
                desc_parts.append(description)
            desc_parts.append(f"\n---\n类型: {type_label}")
            desc_parts.append(f"来源邮件: {source_mail_subject}")
            desc_parts.append(f"提取置信度: {confidence:.0%}")
            desc_parts.append(f"\n由 Mail-Calendar-Bridge 自动生成")
            event.description = "\n".join(desc_parts)

            # 提前提醒（30 分钟前）
            alarm = DisplayAlarm(trigger=timedelta(minutes=-30))
            event.alarms = [alarm]

            return event

        except Exception as e:
            logger.warning("构建事件失败: %s (标题: %s)", e, title)
            return None

    @staticmethod
    def _add_dtstamp(ics_text: str) -> str:
        """为每个 VEVENT 添加缺失的 DTSTAMP 属性。

        RFC 5545 规定 DTSTAMP 是 VEVENT 的强制属性。
        Android 日历解析器如果缺少 DTSTAMP 会拒绝导入。
        """
        now_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return re.sub(
            r'BEGIN:VEVENT\r?\n',
            f'BEGIN:VEVENT\r\nDTSTAMP:{now_utc}\r\n',
            ics_text,
        )

    @staticmethod
    def _fold_long_lines(ics_text: str) -> str:
        """对超过 75 octets 的行做 RFC 5545 内容折行。

        RFC 5545 Section 3.1: 每行最多 75 octets（不含 CRLF）。
        超长行在 75 字节处断开，续行以空格开头。
        """
        MAX_OCTETS = 75
        lines = ics_text.split('\r\n')
        folded: list[str] = []

        for line in lines:
            encoded = line.encode('utf-8')
            if len(encoded) <= MAX_OCTETS:
                folded.append(line)
                continue

            # 需要折行：按字节切分
            current = bytearray()
            for char in line:
                char_bytes = char.encode('utf-8')
                if len(current) + len(char_bytes) > MAX_OCTETS:
                    folded.append(current.decode('utf-8'))
                    current = bytearray(b' ' + char_bytes)
                else:
                    current.extend(char_bytes)
            if current:
                folded.append(current.decode('utf-8'))

        return '\r\n'.join(folded)

    @staticmethod
    def _reorder_valarm(ics_text: str) -> str:
        """将每个 VEVENT 中的 VALARM 块移到 END:VEVENT 之前。

        ics.py 0.7.3 把 VALARM 序列化在 VEVENT 的最前面（DTSTART 之前），
        Android 日历解析器对此顺序敏感，会拒绝导入。
        此方法将 VALARM 块移到 END:VEVENT 之前，解决兼容性问题。
        """
        # serialize() 输出使用 \r\n (RFC 5545 标准)
        nl = r'\r?\n'

        # 匹配 BEGIN:VALARM ... END:VALARM 块
        valarm_pattern = re.compile(
            rf'BEGIN:VALARM{nl}.*?END:VALARM{nl}?',
            re.DOTALL,
        )

        def fix_vevent(vevent_text: str) -> str:
            valarms = valarm_pattern.findall(vevent_text)
            if not valarms:
                return vevent_text
            cleaned = valarm_pattern.sub('', vevent_text)
            cleaned = cleaned.replace(
                'END:VEVENT',
                ''.join(valarms) + 'END:VEVENT',
            )
            return cleaned

        # 匹配每个 VEVENT 块
        vevent_pattern = re.compile(
            rf'BEGIN:VEVENT{nl}.*?END:VEVENT{nl}?',
            re.DOTALL,
        )
        return vevent_pattern.sub(
            lambda m: fix_vevent(m.group(0)),
            ics_text,
        )

    def _write_calendar(self, calendar: Calendar) -> None:
        """将日历对象写入文件。"""
        self._ensure_output_dir()
        # ics 库的 serialize() 会处理换行和编码
        ics_text = calendar.serialize()
        # 修复 VALARM 顺序：Android 日历要求 VALARM 在 VEVENT 末尾
        ics_text = self._reorder_valarm(ics_text)
        # 添加 DTSTAMP：RFC 5545 强制属性，Android 缺少它会拒绝导入
        ics_text = self._add_dtstamp(ics_text)
        # RFC 5545 折行：每行最多 75 octets，超长行必须折行
        ics_text = self._fold_long_lines(ics_text)
        # serialize() 已经输出 \r\n，不能用 newline='\r\n'
        # 否则 Python 会把已有的 \n 再转一次，变成 \r\r\n
        with open(self.output_path, "w", encoding="utf-8", newline="") as f:
            f.write(ics_text)

    def get_event_count(self) -> int:
        """获取当前 .ics 文件中的事件数量。"""
        if not self.output_path.exists():
            return 0
        try:
            with open(self.output_path, "r", encoding="utf-8") as f:
                text = f.read()
            calendar = Calendar(text)
            return len(calendar.events)
        except Exception:
            return 0