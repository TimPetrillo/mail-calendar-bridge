"""Mail-Calendar-Bridge 主入口。

从 USTC 邮箱读取新邮件，用 Claude API 提取 DDL 事件，生成 .ics 日历文件。

用法:
    python main.py                     # 默认运行
    python main.py --days 14           # 搜索最近 14 天
    python main.py --dry-run           # 干跑模式（不实际写入）
    python main.py --force-all         # 强制重新处理所有邮件
    python main.py --confidence 0.7    # 自定义置信度阈值
    python main.py --rebuild-ics       # 从数据库重建 .ics 文件
    python main.py --output-dir ./docs # 自定义 .ics 输出目录
"""

import argparse
import json
import logging
import sys
from datetime import datetime

# 修复 Windows 终端中文编码问题：必须在 logging.basicConfig 之前设置
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

import config
from mail_reader import MailReader, EmailRecord
from ddl_extractor import DDLExtractor, CalendarEvent, ExtractionResult
from db import Database
from calendar_writer import CalendarWriter, _generate_ics_uid

# 配置日志
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="Mail-Calendar-Bridge: 从 USTC 邮箱提取 DDL 并写入日历",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py                        # 检查最近 7 天的新邮件
  python main.py --days 14              # 检查最近 14 天
  python main.py --dry-run              # 仅预览，不写入
  python main.py --confidence 0.8       # 只记录高置信度事件
  python main.py --rebuild-ics          # 从数据库重建 .ics 文件
        """,
    )
    parser.add_argument(
        "--days", type=int, default=None,
        help=f"搜索最近 N 天的邮件（默认: {config.MAIL_SEARCH_DAYS}）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="干跑模式：读取和分析邮件，但不写入 .ics 和数据库",
    )
    parser.add_argument(
        "--force-all", action="store_true",
        help="强制重新处理所有邮件（忽略已处理记录）",
    )
    parser.add_argument(
        "--confidence", type=float, default=None,
        help=f"置信度阈值 (0.0-1.0)，低于此值的事件不写入日历（默认: {config.DDL_CONFIDENCE_THRESHOLD}）",
    )
    parser.add_argument(
        "--rebuild-ics", action="store_true",
        help="不从新邮件生成，而是从数据库完全重建 .ics 文件",
    )
    parser.add_argument(
        "--output-dir", type=str, default=None,
        help=f"自定义 .ics 输出目录（默认: {config.OUTPUT_DIR}）",
    )
    return parser.parse_args()


def run_pipeline(
    days: int | None = None,
    dry_run: bool = False,
    force_all: bool = False,
    confidence_threshold: float | None = None,
    output_dir: str | None = None,
) -> dict:
    """执行完整的邮件→DDL→日历流水线。

    Returns:
        统计信息字典。
    """
    stats = {
        "total_emails": 0,
        "new_emails": 0,
        "emails_with_events": 0,
        "total_events_found": 0,
        "total_events_written": 0,
        "errors": 0,
    }

    # 初始化各模块
    extractor = DDLExtractor(confidence_threshold=confidence_threshold)
    writer = CalendarWriter(output_dir=output_dir)

    with Database() as db, MailReader() as reader:
        # 读取邮件
        all_emails = reader.fetch_emails(search_days=days)
        stats["total_emails"] = len(all_emails)

        if not all_emails:
            logger.info("未搜索到邮件，退出")
            return stats

        # 过滤已处理的邮件
        processed_uids = set() if force_all else db.get_processed_uids()
        processed_message_ids = set() if force_all else db.get_processed_message_ids()
        new_emails = [
            e for e in all_emails
            if e.uid not in processed_uids
            and (not e.message_id or e.message_id not in processed_message_ids)
        ]
        stats["new_emails"] = len(new_emails)

        processed_email_count = stats["total_emails"] - stats["new_emails"]
        if not new_emails:
            logger.info(
                "没有新邮件需要处理（共 %d 封，%d 封已处理）",
                stats["total_emails"],
                processed_email_count,
            )
            return stats

        logger.info(
            "开始处理 %d 封新邮件（共 %d 封，%d 封已处理）...",
            stats["new_emails"],
            stats["total_emails"],
            processed_email_count,
        )

        # 批量提取 DDL
        email_tuples = [
            (e.subject, e.body_text, e.date, e.uid) for e in new_emails
        ]
        results = extractor.extract_batch(email_tuples)

        # 收集所有高置信度事件
        all_new_events: list[CalendarEvent] = []
        for result in results:
            if result.error:
                stats["errors"] += 1

            if result.has_events:
                stats["emails_with_events"] += 1
                stats["total_events_found"] += len(result.events)
                all_new_events.extend(result.events)

            # 更新数据库
            if not dry_run:
                # 找到对应的原始邮件信息
                orig = next(
                    (e for e in new_emails if e.uid == result.mail_uid), None
                )
                events_json = json.dumps(
                    [
                        {
                            "title": e.title,
                            "start_datetime": e.start_datetime,
                            "end_datetime": e.end_datetime,
                            "event_type": e.event_type,
                            "confidence": e.confidence,
                        }
                        for e in result.events
                    ],
                    ensure_ascii=False,
                )
                content_hash = (
                    Database.compute_content_hash(orig.subject, orig.body_text)
                    if orig
                    else ""
                )
                db.mark_processed(
                    mail_uid=result.mail_uid,
                    message_id=orig.message_id if orig else "",
                    subject=orig.subject if orig else "",
                    from_address=orig.from_address if orig else "",
                    received_date=orig.date.isoformat() if orig else "",
                    has_events=result.has_events,
                    events_json=events_json,
                    content_hash=content_hash,
                )

        # 写入日历
        if all_new_events and not dry_run:
            # 先插入数据库日历事件表
            for evt in all_new_events:
                ics_uid = _generate_ics_uid(
                    evt.source_mail_uid, evt.title, evt.start_datetime
                )
                inserted = db.insert_calendar_event(
                    ics_uid=ics_uid,
                    title=evt.title,
                    start_datetime=evt.start_datetime,
                    end_datetime=evt.end_datetime,
                    event_type=evt.event_type,
                    confidence=evt.confidence,
                    source_mail_uid=evt.source_mail_uid,
                )
                if inserted:
                    stats["total_events_written"] += 1

            # 生成 .ics 事件字典列表并写入文件
            events_for_ics = [
                {
                    "ics_uid": _generate_ics_uid(
                        e.source_mail_uid, e.title, e.start_datetime
                    ),
                    "title": e.title,
                    "start_datetime": e.start_datetime,
                    "end_datetime": e.end_datetime,
                    "is_all_day": e.is_all_day,
                    "location": e.location or "",
                    "description": e.description or "",
                    "event_type": e.event_type,
                    "confidence": e.confidence,
                    "source_mail_uid": e.source_mail_uid,
                    "source_mail_subject": e.source_mail_subject,
                }
                for e in all_new_events
            ]
            writer.append_events(events_for_ics)

        elif all_new_events and dry_run:
            logger.info("[DRY RUN] 将写入 %d 个事件:", len(all_new_events))
            for evt in all_new_events:
                logger.info(
                    "  - [%s] %s | %s | 置信度: %.0f%%",
                    evt.event_type,
                    evt.title,
                    evt.start_datetime,
                    evt.confidence * 100,
                )
            stats["total_events_written"] = 0

    return stats


def rebuild_ics(output_dir: str | None = None) -> int:
    """从数据库完全重建 .ics 文件。"""
    writer = CalendarWriter(output_dir=output_dir)
    with Database() as db:
        events = db.get_all_calendar_events()
        if not events:
            logger.info("数据库中没有日历事件")
            return 0
        count = writer.rebuild_from_db(events)
        return count


def print_summary(stats: dict) -> None:
    """打印运行摘要。"""
    print()
    print("=" * 60)
    print("  Mail-Calendar-Bridge 运行摘要")
    print("=" * 60)
    print(f"  扫描邮件总数:      {stats.get('total_emails', 0)}")
    print(f"  其中新邮件:        {stats.get('new_emails', 0)}")
    print(f"  包含事件的邮件:    {stats.get('emails_with_events', 0)}")
    print(f"  提取的事件总数:    {stats.get('total_events_found', 0)}")
    print(f"  写入日历的事件:    {stats.get('total_events_written', 0)}")
    print(f"  错误数:            {stats.get('errors', 0)}")
    print("=" * 60)

    writer = CalendarWriter()
    output_path = writer.output_path
    if output_path.exists():
        print(f"  日历文件:          {output_path.resolve()}")
        evt_count = writer.get_event_count()
        print(f"  日历中事件总数:    {evt_count}")
    print("=" * 60)
    print()

    if stats.get("total_events_written", 0) > 0:
        print("提示: 将日历文件传输到手机后，在文件管理器中点击 .ics 文件即可导入日历。")


def main() -> None:
    """主入口函数。"""
    args = parse_args()

    # 启动前校验必需配置
    missing = config.validate_config()
    if missing:
        print("错误: 缺少以下必需配置项:")
        for item in missing:
            print(f"  - {item}")
        print("\n请在 .env 文件中设置这些配置项。参考 .env.example 模板。")
        sys.exit(1)

    try:
        if args.rebuild_ics:
            logger.info("从数据库重建 .ics 文件...")
            count = rebuild_ics(output_dir=args.output_dir)
            logger.info("重建完成: %d 个事件", count)
            print(f"已从数据库重建 .ics 文件，共 {count} 个事件。")
            return

        logger.info("Mail-Calendar-Bridge 启动")
        if args.dry_run:
            logger.info("模式: DRY RUN (不实际写入)")

        stats = run_pipeline(
            days=args.days,
            dry_run=args.dry_run,
            force_all=args.force_all,
            confidence_threshold=args.confidence,
            output_dir=args.output_dir,
        )
        print_summary(stats)

    except KeyboardInterrupt:
        logger.info("用户中断")
        sys.exit(0)
    except Exception as e:
        logger.exception("运行失败: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()