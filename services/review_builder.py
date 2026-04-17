"""
services/review_builder.py

Два режима:
1. build_from_template — собирает структурированный обзор из ответов по вопросам
2. clean_text_with_groq — только корректура текста (опечатки + пунктуация)
"""

import logging
import aiohttp

logger = logging.getLogger(__name__)

_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

_SYSTEM_CLEAN = (
    "Ты корректор. Твоя единственная задача — исправить опечатки и расставить пунктуацию. "
    "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО: менять смысл, переставлять предложения, объединять мысли, "
    "добавлять слова, переписывать, сокращать, перефразировать. "
    "Можно только: исправить явные опечатки, поставить запятые и точки где их нет. "
    "Верни текст максимально близко к оригиналу."
)


async def clean_text_with_groq(text: str, api_key: str) -> str | None:
    """Только корректура — опечатки и пунктуация. Смысл не трогать."""
    if not text or not text.strip():
        return None

    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": _SYSTEM_CLEAN},
            {"role": "user", "content": text},
        ],
        "temperature": 0,
        "max_tokens": 1200,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                _GROQ_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning(f"Groq: статус {resp.status} — {body[:200]}")
                    return None
                data = await resp.json()
                result = (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                    .strip()
                )
                return result or None
    except Exception as e:
        logger.warning(f"Groq: ошибка — {e}")
        return None


def build_from_template(answers: dict) -> str:
    """Собирает структурированный обзор из ответов на 5 вопросов."""
    hook     = answers.get("hook",     answers.get("impression", "")).strip()
    moment   = answers.get("moment",   answers.get("highlight",  "")).strip()
    liked    = answers.get("liked",    "").strip()
    disliked = answers.get("disliked", answers.get("downside",   "")).strip()
    verdict  = answers.get("verdict",  answers.get("recommend",  "")).strip()

    def cap(t: str) -> str:
        t = t.strip()
        if not t:
            return ""
        t = t[0].upper() + t[1:]
        if t[-1] not in ".!?…":
            t += "."
        return t

    parts = []

    if hook:
        parts.append(f"🎮 {cap(hook)}")

    plus_parts = []
    if moment:
        plus_parts.append(cap(moment))
    if liked:
        plus_parts.append(cap(liked))
    if plus_parts:
        parts.append("➕ Плюсы\n" + " ".join(plus_parts))

    if disliked:
        parts.append("➖ Минусы\n" + cap(disliked))

    if verdict:
        parts.append("🎯 Вердикт\n" + cap(verdict))

    return "\n\n".join(parts) if parts else "Обзор не заполнен."


async def build_review(answers: dict,
                       api_key: str | None = None,
                       groq_key: str | None = None) -> str:
    """Алиас для совместимости — собирает обзор из ответов."""
    return build_from_template(answers)
