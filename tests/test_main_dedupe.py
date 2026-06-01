"""main 模块去重逻辑测试。"""

from datetime import datetime
from unittest.mock import MagicMock, patch

from ddl_extractor import ExtractionResult
from mail_reader import EmailRecord
import main


def _context_mock() -> MagicMock:
    mock = MagicMock()
    mock.__enter__.return_value = mock
    mock.__exit__.return_value = False
    return mock


def test_run_pipeline_skips_legacy_processed_message_id():
    """UID 变化但 Message-ID 已处理时不重复调用提取。"""
    email = EmailRecord(
        uid="real-imap-uid-101",
        message_id="<legacy@example.com>",
        subject="已处理邮件",
        from_address="sender@example.com",
        from_name="Sender",
        date=datetime(2026, 5, 31),
        body_text="这是一封正文长度足够的测试邮件。",
    )

    db = _context_mock()
    db.get_processed_uids.return_value = set()
    db.get_processed_message_ids.return_value = {"<legacy@example.com>"}

    reader = _context_mock()
    reader.fetch_emails.return_value = [email]

    extractor = MagicMock()

    with patch("main.Database", return_value=db), \
        patch("main.MailReader", return_value=reader), \
        patch("main.DDLExtractor", return_value=extractor), \
        patch("main.CalendarWriter"):
        stats = main.run_pipeline()

    assert stats["total_emails"] == 1
    assert stats["new_emails"] == 0
    extractor.extract_batch.assert_not_called()


def test_force_all_bypasses_uid_and_message_id_dedupe():
    """force_all 会忽略 UID 和 Message-ID 去重。"""
    email = EmailRecord(
        uid="real-imap-uid-101",
        message_id="<legacy@example.com>",
        subject="已处理邮件",
        from_address="sender@example.com",
        from_name="Sender",
        date=datetime(2026, 5, 31),
        body_text="这是一封正文长度足够的测试邮件。",
    )

    db = _context_mock()
    db.get_processed_uids.return_value = {"real-imap-uid-101"}
    db.get_processed_message_ids.return_value = {"<legacy@example.com>"}

    reader = _context_mock()
    reader.fetch_emails.return_value = [email]

    extractor = MagicMock()
    extractor.extract_batch.return_value = [
        ExtractionResult(mail_uid="real-imap-uid-101", has_events=False)
    ]

    with patch("main.Database", return_value=db), \
        patch("main.MailReader", return_value=reader), \
        patch("main.DDLExtractor", return_value=extractor), \
        patch("main.CalendarWriter"):
        stats = main.run_pipeline(force_all=True)

    assert stats["total_emails"] == 1
    assert stats["new_emails"] == 1
    extractor.extract_batch.assert_called_once()
