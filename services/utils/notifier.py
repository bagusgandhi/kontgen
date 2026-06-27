"""
Telegram Notifier
Sends pipeline run results to a Telegram chat via Bot API.
Uses MarkdownV2 format for rich message display.
"""

from typing import Optional
import structlog
import httpx

from core.config import settings
from core.models import PipelineResult

logger = structlog.get_logger(__name__)

# Telegram Bot API base URL
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def _escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special = r"\_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in special else c for c in str(text))


class TelegramNotifier:
    """
    Sends pipeline result notifications to a Telegram chat.
    Requires a bot token and a chat/group ID.

    Setup:
      1. Buat bot via @BotFather → dapat TELEGRAM_BOT_TOKEN
      2. Tambahkan bot ke group/channel
      3. Dapatkan chat ID via https://api.telegram.org/bot<token>/getUpdates
         atau kirim pesan ke bot lalu cek field chat.id
    """

    def __init__(
        self,
        bot_token: str = "",
        chat_id: str = "",
    ):
        self._token = bot_token or settings.TELEGRAM_BOT_TOKEN
        self._chat_id = chat_id or settings.TELEGRAM_CHAT_ID

    async def send_result(self, result: PipelineResult) -> bool:
        """
        Send pipeline result notification to Telegram.
        Returns True if sent successfully.
        """
        if not self._token or not self._chat_id:
            logger.warning(
                "Telegram not configured, skipping notification",
                has_token=bool(self._token),
                has_chat_id=bool(self._chat_id),
            )
            return False

        text = self._build_message(result)

        try:
            url = TELEGRAM_API.format(token=self._token)
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    url,
                    json={
                        "chat_id": self._chat_id,
                        "text": text,
                        "parse_mode": "MarkdownV2",
                        "disable_web_page_preview": False,
                    },
                )
                response.raise_for_status()

            logger.info(
                "Telegram notification sent",
                success=result.success,
                keyword=result.keyword,
            )
            return True

        except httpx.HTTPStatusError as e:
            logger.error(
                "Telegram notification failed",
                status=e.response.status_code,
                error=e.response.text[:300],
            )
            return False
        except Exception as e:
            logger.error("Telegram notification error", error=str(e))
            return False

    def _build_message(self, result: PipelineResult) -> str:
        """Build MarkdownV2 formatted Telegram message."""
        status_icon = "✅" if result.success else "❌"
        status_text = "SUCCESS" if result.success else "FAILED"
        timestamp_str = result.timestamp.strftime("%d %b %Y, %H:%M WIB")

        lines = [
            f"{status_icon} *AutoBlog Generator — {_escape_md(status_text)}*",
            "",
            f"📝 *Judul:* {_escape_md(result.article_title or '(No title)')}",
            f"🔑 *Keyword:* {_escape_md(result.keyword)}",
            f"🖼 *Thumbnail:* {_escape_md(result.thumbnail_source or '-')}",
            f"📊 *Jumlah Kata:* {_escape_md(str(result.word_count))}",
            f"⏱ *Waktu Proses:* {_escape_md(f'{result.processing_time_seconds:.1f}s')}",
            f"🕐 *Timestamp:* {_escape_md(timestamp_str)}",
        ]

        if result.wp_draft_url:
            lines.append(f"🔗 [Lihat Draft WordPress]({result.wp_draft_url})")

        if not result.success and result.error_message:
            lines += [
                "",
                f"⚠️ *Error:*",
                f"`{_escape_md(result.error_message[:300])}`",
            ]

        return "\n".join(lines)

