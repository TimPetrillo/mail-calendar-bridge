"""db 模块的单元测试。"""

from db import Database


def test_get_processed_message_ids_excludes_empty_values(tmp_path):
    db_path = tmp_path / "mail_cache.db"
    with Database(db_path=str(db_path)) as db:
        db.mark_processed(
            mail_uid="uid-with-message-id",
            message_id="<message@example.com>",
            subject="subject",
            from_address="sender@example.com",
            received_date="2026-05-31T14:00:00+08:00",
            has_events=False,
        )
        db.mark_processed(
            mail_uid="uid-without-message-id",
            message_id="",
            subject="subject",
            from_address="sender@example.com",
            received_date="2026-05-31T14:00:00+08:00",
            has_events=False,
        )

        assert db.get_processed_message_ids() == {"<message@example.com>"}
