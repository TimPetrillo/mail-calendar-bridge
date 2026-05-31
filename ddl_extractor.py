"""DDL 智能提取模块。通过 Claude API 分析邮件正文，提取截止日期和日程事件。

使用 Tool Use (function calling) 强制结构化输出，支持中文自然语言日期表达。
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from anthropic import Anthropic

import config

logger = logging.getLogger(__name__)

# ---- Claude Tool Schema ----

EXTRACT_EVENTS_TOOL = {
    "name": "extract_calendar_events",
    "description": (
        "从邮件内容中提取与截止日期、日程安排相关的事件。"
        "如果邮件中没有明确的时间要求或日程信息，返回 has_events=false。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "has_events": {
                "type": "boolean",
                "description": "邮件中是否包含至少一个需要记录到日历的事件",
            },
            "events": {
                "type": "array",
                "description": "提取到的日历事件列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": (
                                "事件标题，简洁明确。示例: '提交数值分析作业'、"
                                "'博士生开题答辩'、'组会汇报'。"
                            ),
                        },
                        "start_datetime": {
                            "type": "string",
                            "description": (
                                "事件开始时间，ISO 8601 格式带时区。"
                                "示例: '2026-06-05T14:00:00+08:00'。"
                                "如果是全天事件，只写日期部分: '2026-06-05'。"
                            ),
                        },
                        "end_datetime": {
                            "type": "string",
                            "description": (
                                "事件结束时间，ISO 8601 格式带时区。"
                                "如果邮件未明确结束时间，可根据事件类型合理推断"
                                "（如作业截止通常为当天 23:59，会议通常 1-2 小时）。"
                                "可选字段。"
                            ),
                        },
                        "is_all_day": {
                            "type": "boolean",
                            "description": "是否为全天事件（如: 论文提交截止日、报名截止日等只有日期没有具体时刻的事件）",
                        },
                        "location": {
                            "type": "string",
                            "description": "事件地点。示例: '西区教学楼 3A102'、'线上腾讯会议'。可选字段。",
                        },
                        "description": {
                            "type": "string",
                            "description": (
                                "事件描述，包含关键上下文信息：具体要求、提交方式、"
                                "联系人等。不超过 200 字。"
                            ),
                        },
                        "confidence": {
                            "type": "number",
                            "description": (
                                "置信度 0.0-1.0。"
                                "0.9-1.0: 邮件明确写了日期和时间。"
                                "0.7-0.89: 有日期但表述模糊（如'尽快''近期'）。"
                                "0.5-0.69: 仅推断出可能的时间相关要求。"
                                "0.0-0.49: 不太确定（此类事件不会被写入日历）。"
                            ),
                        },
                        "event_type": {
                            "type": "string",
                            "enum": [
                                "homework_deadline",
                                "exam",
                                "meeting",
                                "thesis",
                                "registration",
                                "payment",
                                "activity",
                                "other",
                            ],
                            "description": "事件类型分类",
                        },
                    },
                    "required": ["title", "start_datetime", "confidence", "event_type"],
                },
            },
        },
        "required": ["has_events", "events"],
    },
}

# ---- System Prompt ----

SYSTEM_PROMPT = """你是一个学术日历助手，专门分析大学邮件内容，提取与截止日期和日程安排相关的信息。

## 你的任务

分析每封邮件的正文内容，判断其中是否包含需要记录到日历中的事件（作业截止、考试安排、会议通知、论文提交、答辩、活动、缴费等）。

## 日期解析规则

1. **所有日期统一使用 Asia/Shanghai 时区 (UTC+8)**。
2. **参考日期**: 邮件的发送日期作为"今天"的基准。我会在邮件正文前标注 `[邮件发送日期: YYYY-MM-DD]`。
3. **中文日期表达解析**:
   - "下周三" → 基于邮件日期推算具体日期
   - "5月20日前" / "截止日期为5月20日" → 并补充年份（当前或最近的）
   - "本周五 14:00" → 推算具体日期 + 时间
   - "明天上午" → 默认 09:00
   - "下周" → 7天后
   - "本学期第15周" → 如果无法推算具体日期，跳过此事件
4. **未指明具体时间**:
   - 作业/论文截止 → 默认 23:59
   - 全天事件（只给日期不给时间）→ is_all_day=true
   - 会议/活动/考试 → 如果没给时间但给了日期，is_all_day=false，结束时间设为开始时间+1小时
5. **范围表述**: "5月20日-25日" 如果是提交窗口，start=5月20日, end=5月25日 23:59
6. **模糊日期**: 如"尽快""近期""下周左右"等无法确定具体日期的，不要提取

## 不要提取的情况

- 已经过去的事件
- 仅提及日期但并非要求读者在此日期前完成某事（如"上次会议于5月1日召开"）
- 纯粹的叙事性时间（如"该项目始于2020年"）
- 无法确定具体日期的模糊表述

## 事件类型说明

- homework_deadline: 作业、实验报告、课程设计提交截止
- exam: 考试（期中、期末、随堂测验等）
- meeting: 会议、组会、讨论
- thesis: 论文提交、开题、答辩、盲审
- registration: 报名、选课、注册
- payment: 缴费
- activity: 讲座、活动、比赛、社团
- other: 其他类型的日程

## 输出要求

如果邮件中没有可提取的日历事件，设置 has_events=false 并返回空的 events 数组。
每个事件的 confidence 必须如实反映你对提取结果的确定程度。"""


@dataclass
class CalendarEvent:
    """从邮件中提取出的日历事件。"""
    title: str
    start_datetime: str              # ISO 8601 或 YYYY-MM-DD
    end_datetime: Optional[str] = None
    is_all_day: bool = False
    location: Optional[str] = None
    description: Optional[str] = None
    event_type: str = "other"
    confidence: float = 0.0
    source_mail_uid: str = ""
    source_mail_subject: str = ""
    source_mail_date: str = ""


@dataclass
class ExtractionResult:
    """单封邮件的提取结果。"""
    mail_uid: str
    has_events: bool
    events: list[CalendarEvent] = field(default_factory=list)
    raw_response: Optional[str] = None     # 用于调试
    error: Optional[str] = None


class DDLExtractor:
    """使用 Claude API 从邮件内容中提取 DDL 事件。"""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        confidence_threshold: float | None = None,
    ):
        self.client = Anthropic(
            api_key=api_key or config.ANTHROPIC_API_KEY,
            base_url=config.ANTHROPIC_BASE_URL,
        )
        self.model = model or config.ANTHROPIC_MODEL
        self.confidence_threshold = (
            confidence_threshold
            if confidence_threshold is not None
            else config.DDL_CONFIDENCE_THRESHOLD
        )

    def extract_from_email(
        self, subject: str, body_text: str, mail_date: datetime, mail_uid: str
    ) -> ExtractionResult:
        """分析单封邮件，提取日历事件。

        Args:
            subject: 邮件主题。
            body_text: 邮件纯文本正文。
            mail_date: 邮件发送日期。
            mail_uid: 邮件的 IMAP UID。

        Returns:
            ExtractionResult 包含提取出的事件列表。
        """
        if not body_text or len(body_text.strip()) < 10:
            return ExtractionResult(
                mail_uid=mail_uid,
                has_events=False,
                events=[],
            )

        # 构造 prompt：在正文前标注邮件日期
        date_prefix = f"[邮件发送日期: {mail_date.strftime('%Y-%m-%d')}]\n\n"
        user_message = f"主题: {subject}\n\n{date_prefix}{body_text}"

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
                tools=[EXTRACT_EVENTS_TOOL],
                tool_choice={"type": "tool", "name": "extract_calendar_events"},
            )

            # 提取 tool_use 结果
            result = ExtractionResult(mail_uid=mail_uid, has_events=False, events=[])

            for content_block in response.content:
                if content_block.type == "tool_use":
                    tool_input = content_block.input
                    result.has_events = tool_input.get("has_events", False)
                    result.raw_response = json.dumps(tool_input, ensure_ascii=False)

                    if result.has_events:
                        for evt_data in tool_input.get("events", []):
                            confidence = evt_data.get("confidence", 0.0)
                            if confidence >= self.confidence_threshold:
                                event = CalendarEvent(
                                    title=evt_data.get("title", ""),
                                    start_datetime=evt_data.get("start_datetime", ""),
                                    end_datetime=evt_data.get("end_datetime"),
                                    is_all_day=evt_data.get("is_all_day", False),
                                    location=evt_data.get("location"),
                                    description=evt_data.get("description"),
                                    event_type=evt_data.get("event_type", "other"),
                                    confidence=confidence,
                                    source_mail_uid=mail_uid,
                                    source_mail_subject=subject,
                                    source_mail_date=mail_date.strftime("%Y-%m-%d"),
                                )
                                result.events.append(event)
                            else:
                                logger.debug(
                                    "事件置信度 %.2f 低于阈值 %.2f，跳过: %s (UID: %s)",
                                    confidence,
                                    self.confidence_threshold,
                                    evt_data.get("title", ""),
                                    mail_uid,
                                )

            return result

        except Exception as e:
            logger.exception("Claude API 调用失败 (UID: %s)", mail_uid)
            return ExtractionResult(
                mail_uid=mail_uid,
                has_events=False,
                events=[],
                error=str(e),
            )

    def extract_batch(
        self,
        emails: list[tuple[str, str, datetime, str]],
    ) -> list[ExtractionResult]:
        """批量分析多封邮件。

        Args:
            emails: 列表，每项为 (subject, body_text, mail_date, mail_uid)。

        Returns:
            ExtractionResult 列表，与输入顺序一致。
        """
        results: list[ExtractionResult] = []
        total = len(emails)

        for i, (subject, body_text, mail_date, mail_uid) in enumerate(emails, 1):
            logger.info("分析邮件 [%d/%d]: %s", i, total, subject[:60])
            result = self.extract_from_email(subject, body_text, mail_date, mail_uid)
            results.append(result)

            if result.has_events:
                logger.info(
                    "  → 提取到 %d 个事件 (阈值过滤后)", len(result.events)
                )
                for evt in result.events:
                    logger.info(
                        "    - [%s] %s @ %s (置信度: %.2f)",
                        evt.event_type,
                        evt.title,
                        evt.start_datetime,
                        evt.confidence,
                    )
            elif result.error:
                logger.warning("  → 提取失败: %s", result.error)
            else:
                logger.debug("  → 无日历事件")

        return results