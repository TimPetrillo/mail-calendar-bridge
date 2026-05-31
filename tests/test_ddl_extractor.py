"""ddl_extractor 模块的单元测试。"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from ddl_extractor import DDLExtractor, CalendarEvent, ExtractionResult, SYSTEM_PROMPT, EXTRACT_EVENTS_TOOL


class TestCalendarEvent:
    """测试 CalendarEvent 数据类。"""

    def test_create_event(self):
        """测试创建事件对象。"""
        evt = CalendarEvent(
            title="提交作业",
            start_datetime="2026-06-05T23:59:00+08:00",
            event_type="homework_deadline",
            confidence=0.95,
            source_mail_uid="123",
            source_mail_subject="关于提交作业的通知",
            source_mail_date="2026-05-31",
        )
        assert evt.title == "提交作业"
        assert evt.start_datetime == "2026-06-05T23:59:00+08:00"
        assert evt.confidence == 0.95
        assert evt.is_all_day is False


class TestExtractionResult:
    """测试 ExtractionResult 数据类。"""

    def test_empty_result(self):
        """测试无事件的结果。"""
        result = ExtractionResult(mail_uid="123", has_events=False)
        assert result.has_events is False
        assert len(result.events) == 0

    def test_error_result(self):
        """测试带错误的结果。"""
        result = ExtractionResult(
            mail_uid="123",
            has_events=False,
            error="API connection failed",
        )
        assert result.error == "API connection failed"


class TestDDLExtractor:
    """测试 DDLExtractor 类。"""

    def test_init_with_defaults(self):
        """测试默认初始化（需要环境变量中有 API key）。"""
        # 使用 mock API key
        extractor = DDLExtractor(api_key="sk-ant-test")
        assert extractor.confidence_threshold == 0.6

    def test_init_with_custom_threshold(self):
        """测试自定义置信度阈值。"""
        extractor = DDLExtractor(api_key="sk-ant-test", confidence_threshold=0.8)
        assert extractor.confidence_threshold == 0.8

    def test_extract_from_empty_body(self):
        """测试空正文的处理。"""
        extractor = DDLExtractor(api_key="sk-ant-test")
        result = extractor.extract_from_email(
            subject="Test",
            body_text="",
            mail_date=datetime(2026, 5, 31),
            mail_uid="123",
        )
        assert result.has_events is False
        assert len(result.events) == 0

    def test_extract_from_short_body(self):
        """测试过短正文的处理。"""
        extractor = DDLExtractor(api_key="sk-ant-test")
        result = extractor.extract_from_email(
            subject="Test",
            body_text="Hi",
            mail_date=datetime(2026, 5, 31),
            mail_uid="123",
        )
        assert result.has_events is False

    @patch("ddl_extractor.Anthropic")
    def test_extract_with_mock_api(self, mock_anthropic_class):
        """使用 Mock API 测试提取流程。"""
        # 构造 mock 响应
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_content = MagicMock()
        mock_content.type = "tool_use"
        mock_content.input = {
            "has_events": True,
            "events": [
                {
                    "title": "提交数值分析作业",
                    "start_datetime": "2026-06-05T23:59:00+08:00",
                    "end_datetime": "2026-06-05T23:59:00+08:00",
                    "is_all_day": False,
                    "location": "",
                    "description": "通过课程平台提交",
                    "confidence": 0.95,
                    "event_type": "homework_deadline",
                },
                {
                    "title": "模糊事件",
                    "start_datetime": "2026-06-10T00:00:00+08:00",
                    "confidence": 0.4,  # 低于阈值
                    "event_type": "other",
                },
            ],
        }
        mock_response.content = [mock_content]
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_class.return_value = mock_client

        extractor = DDLExtractor(api_key="sk-ant-test")
        result = extractor.extract_from_email(
            subject="关于数值分析课程作业提交的通知",
            body_text="请各位同学在 6月5日 之前通过课程平台提交数值分析作业。",
            mail_date=datetime(2026, 5, 31),
            mail_uid="456",
        )

        assert result.has_events is True
        # 只有一个事件通过置信度阈值
        assert len(result.events) == 1
        assert result.events[0].title == "提交数值分析作业"
        assert result.events[0].confidence == 0.95

    def test_tool_schema_valid(self):
        """验证 Tool Schema 结构。"""
        assert EXTRACT_EVENTS_TOOL["name"] == "extract_calendar_events"
        assert "has_events" in EXTRACT_EVENTS_TOOL["input_schema"]["properties"]
        assert "events" in EXTRACT_EVENTS_TOOL["input_schema"]["properties"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])