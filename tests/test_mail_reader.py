"""mail_reader 模块的单元测试。"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta

from mail_reader import MailReader, EmailRecord, _decode_mime_header, _parse_date


class TestDecodeMimeHeader:
    """测试 MIME 头解码。"""

    def test_plain_ascii(self):
        """测试纯 ASCII 字符串。"""
        result = _decode_mime_header("Hello World")
        assert result == "Hello World"

    def test_none_input(self):
        """测试 None 输入。"""
        result = _decode_mime_header(None)
        assert result == ""

    def test_empty_string(self):
        """测试空字符串。"""
        result = _decode_mime_header("")
        assert result == ""


class TestParseDate:
    """测试日期解析。"""

    def test_rfc2822_date(self):
        """测试标准 RFC 2822 日期格式。"""
        result = _parse_date("Mon, 31 May 2026 14:00:00 +0800")
        assert isinstance(result, datetime)
        assert result.year == 2026
        assert result.month == 5
        assert result.day == 31

    def test_none_date(self):
        """测试 None 输入返回当前时间。"""
        result = _parse_date(None)
        assert isinstance(result, datetime)


class TestMailReader:
    """测试 MailReader 类。"""

    def test_init_with_defaults(self):
        """测试使用默认配置初始化。"""
        reader = MailReader()
        assert reader.host == "mail.ustc.edu.cn"
        assert reader.port == 993

    def test_init_with_custom_values(self):
        """测试使用自定义值初始化。"""
        reader = MailReader(
            host="imap.example.com",
            port=143,
            username="test@example.com",
            password="secret",
            folder="Junk",
        )
        assert reader.host == "imap.example.com"
        assert reader.port == 143
        assert reader.username == "test@example.com"
        assert reader.folder == "Junk"

    def test_parse_from_header_with_name(self):
        """测试解析带名称的发件人。"""
        name, addr = MailReader._parse_from_header(
            "张三 <zhangsan@mail.ustc.edu.cn>"
        )
        assert name == "张三"
        assert addr == "zhangsan@mail.ustc.edu.cn"

    def test_parse_from_header_bare_address(self):
        """测试解析纯地址。"""
        name, addr = MailReader._parse_from_header("admin@ustc.edu.cn")
        assert addr == "admin@ustc.edu.cn"

    def test_parse_from_header_empty(self):
        """测试解析空字符串。"""
        name, addr = MailReader._parse_from_header("")
        assert name == ""
        assert addr == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])