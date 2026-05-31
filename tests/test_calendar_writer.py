"""calendar_writer 模块的单元测试。"""

import os
import uuid
import pytest
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

from calendar_writer import (
    CalendarWriter,
    _generate_ics_uid,
    _parse_datetime,
)


class TestGenerateIcsUid:
    """测试 iCalendar UID 生成。"""

    def test_deterministic(self):
        """测试相同输入生成相同的 UID。"""
        uid1 = _generate_ics_uid("mail123", "提交作业", "2026-06-05T23:59:00+08:00")
        uid2 = _generate_ics_uid("mail123", "提交作业", "2026-06-05T23:59:00+08:00")
        assert uid1 == uid2

    def test_different_inputs_different_uids(self):
        """测试不同输入生成不同的 UID。"""
        uid1 = _generate_ics_uid("mail123", "提交作业", "2026-06-05")
        uid2 = _generate_ics_uid("mail124", "提交作业", "2026-06-05")
        assert uid1 != uid2

    def test_valid_uuid_format(self):
        """测试 UID 是有效的 UUID 格式。"""
        uid = _generate_ics_uid("mail123", "test", "2026-06-05")
        # 尝试解析为 UUID（不含连字符也能解析吗？uuid5 返回标准格式）
        parsed = uuid.UUID(uid)
        assert isinstance(parsed, uuid.UUID)


class TestParseDatetime:
    """测试日期时间解析。"""

    def test_full_iso_with_timezone(self):
        """测试完整 ISO 8601 格式。"""
        dt = _parse_datetime("2026-06-05T14:00:00+08:00")
        assert dt.year == 2026
        assert dt.month == 6
        assert dt.day == 5
        assert dt.hour == 14
        assert dt.minute == 0

    def test_date_only(self):
        """测试仅日期格式。"""
        dt = _parse_datetime("2026-06-05")
        assert dt.year == 2026
        assert dt.month == 6
        assert dt.day == 5


class TestCalendarWriter:
    """测试 CalendarWriter 类。"""

    def setup_method(self):
        """每个测试方法前创建临时目录。"""
        self.temp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        """每个测试方法后清理临时目录。"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_init_with_defaults(self):
        """测试默认初始化。"""
        writer = CalendarWriter(output_dir=self.temp_dir, output_filename="test.ics")
        assert writer.output_filename == "test.ics"

    def test_get_event_count_empty_file(self):
        """测试空文件的计数。"""
        writer = CalendarWriter(output_dir=self.temp_dir, output_filename="empty.ics")
        assert writer.get_event_count() == 0

    def test_get_event_count_nonexistent_file(self):
        """测试不存在的文件。"""
        writer = CalendarWriter(
            output_dir=self.temp_dir, output_filename="nonexistent.ics"
        )
        assert writer.get_event_count() == 0

    def test_append_single_event(self):
        """测试追加单个事件。"""
        writer = CalendarWriter(output_dir=self.temp_dir, output_filename="test.ics")

        events = [
            {
                "title": "提交数值分析作业",
                "start_datetime": "2026-06-05T23:59:00+08:00",
                "end_datetime": "2026-06-05T23:59:00+08:00",
                "is_all_day": False,
                "location": "线上",
                "description": "通过课程平台提交",
                "event_type": "homework_deadline",
                "confidence": 0.95,
                "source_mail_uid": "123",
                "source_mail_subject": "作业通知",
            }
        ]

        count = writer.append_events(events)
        assert count == 1
        assert writer.get_event_count() == 1

        # 验证生成的 .ics 文件存在且非空
        ics_path = writer.output_path
        assert ics_path.exists()
        content = ics_path.read_text(encoding="utf-8")
        assert "BEGIN:VCALENDAR" in content
        assert "END:VCALENDAR" in content
        assert "BEGIN:VEVENT" in content
        assert "SUMMARY:提交数值分析作业" in content

    def test_append_duplicate_event(self):
        """测试追加重复事件时去重。"""
        writer = CalendarWriter(output_dir=self.temp_dir, output_filename="test.ics")

        events = [
            {
                "ics_uid": "fixed-uid-123",
                "title": "测试事件",
                "start_datetime": "2026-06-05T14:00:00+08:00",
                "end_datetime": "2026-06-05T15:00:00+08:00",
                "is_all_day": False,
                "location": "",
                "description": "",
                "event_type": "meeting",
                "confidence": 0.9,
                "source_mail_uid": "456",
                "source_mail_subject": "会议通知",
            }
        ]

        count1 = writer.append_events(events)
        assert count1 == 1

        # 再次追加相同的事件
        count2 = writer.append_events(events)
        assert count2 == 0  # 不应重复
        assert writer.get_event_count() == 1

    def test_append_multiple_events(self):
        """测试追加多个事件。"""
        writer = CalendarWriter(output_dir=self.temp_dir, output_filename="test.ics")

        events = [
            {
                "title": f"事件 {i}",
                "start_datetime": f"2026-06-{i+1:02d}T14:00:00+08:00",
                "end_datetime": None,
                "is_all_day": False,
                "location": "",
                "description": "",
                "event_type": "other",
                "confidence": 0.9,
                "source_mail_uid": "uid",
                "source_mail_subject": "",
            }
            for i in range(5)
        ]

        count = writer.append_events(events)
        assert count == 5
        assert writer.get_event_count() == 5

    def test_all_day_event(self):
        """测试全天事件。"""
        writer = CalendarWriter(output_dir=self.temp_dir, output_filename="test.ics")

        events = [
            {
                "title": "论文提交截止",
                "start_datetime": "2026-07-01",
                "end_datetime": "2026-07-01",
                "is_all_day": True,
                "location": "",
                "description": "博士论文盲审提交",
                "event_type": "thesis",
                "confidence": 0.95,
                "source_mail_uid": "789",
                "source_mail_subject": "盲审通知",
            }
        ]

        count = writer.append_events(events)
        assert count == 1

        content = writer.output_path.read_text(encoding="utf-8")
        assert "SUMMARY:论文提交截止" in content

    def test_rebuild_from_db(self):
        """测试从数据库完全重建日历。"""
        writer = CalendarWriter(output_dir=self.temp_dir, output_filename="test.ics")

        # 先追加一些事件
        events = [
            {
                "ics_uid": "uid-rebuild-1",
                "title": "事件 A",
                "start_datetime": "2026-06-01T10:00:00+08:00",
                "end_datetime": None,
                "is_all_day": False,
                "location": "",
                "description": "",
                "event_type": "meeting",
                "confidence": 0.9,
                "source_mail_uid": "a",
            }
        ]
        writer.append_events(events)

        # 模拟数据库事件列表
        db_events = [
            {
                "ics_uid": "uid-rebuild-1",
                "title": "事件 A",
                "start_datetime": "2026-06-01T10:00:00+08:00",
                "end_datetime": None,
                "event_type": "meeting",
                "confidence": 0.9,
                "source_mail_uid": "a",
            },
            {
                "ics_uid": "uid-rebuild-2",
                "title": "事件 B",
                "start_datetime": "2026-06-02T14:00:00+08:00",
                "end_datetime": "2026-06-02T16:00:00+08:00",
                "event_type": "exam",
                "confidence": 0.95,
                "source_mail_uid": "b",
            },
        ]

        count = writer.rebuild_from_db(db_events)
        assert count == 2

        content = writer.output_path.read_text(encoding="utf-8")
        assert "事件 A" in content
        assert "事件 B" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])