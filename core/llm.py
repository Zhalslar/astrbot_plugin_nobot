import json
import re
from typing import Any

from astrbot.api import logger
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.core.star.context import Context


class LLMAction:
    def __init__(self, context: Context, config: AstrBotConfig):
        self.context = context
        self.config = config

    def _build_context(self, round_messages: list[dict[str, Any]]) -> str:
        lines = []
        for msg in round_messages:
            text_segments = [
                seg["data"]["text"] for seg in msg["message"] if seg["type"] == "text"
            ]
            text = "".join(text_segments).strip()
            if text:
                lines.append(f"{msg['sender']['user_id']}: {text}")
        return "\n".join(lines)

    async def _get_msg_contexts(self, event: AiocqhttpMessageEvent) -> str:
        """获取群聊历史消息"""
        group_id = int(event.get_group_id())
        message_seq = 0
        lines: list[str] = []
        for _ in range(self.config["history_msg_rounds"]):
            payloads = {
                "group_id": group_id,
                "message_seq": message_seq,
                "count": 200,
                "reverseOrder": True,
            }
            result: dict = await event.bot.api.call_action(
                "get_group_msg_history", **payloads
            )
            round_messages = result["messages"]
            if not round_messages:
                break
            message_seq = round_messages[0]["message_id"]

            lines.append(self._build_context(round_messages))
        return "\n".join(lines)

    async def _get_contexts(self, event: AstrMessageEvent) -> list[dict] | None:
        """获取当前会话上下文"""
        umo = event.unified_msg_origin
        conv_mgr = self.context.conversation_manager
        curr_cid = await conv_mgr.get_curr_conversation_id(umo)
        if not curr_cid:
            return None
        conversation = await conv_mgr.get_conversation(umo, curr_cid)
        if not conversation:
            return None
        contexts = json.loads(conversation.history)
        return contexts

    async def judge_bot(self, event: AstrMessageEvent) -> list[str]:
        """根据群聊的聊天记录判断人机，返回人机 ID 列表"""
        get_using = self.context.get_using_provider()
        if not get_using:
            raise ValueError("未配置 LLM 提供商")

        history_text = ""
        contexts = []
        if (
            isinstance(event, AiocqhttpMessageEvent)
            and (self.config["history_msg_rounds"])
        ):
            history_text = await self._get_msg_contexts(event)
        else:
            contexts = await self._get_contexts(event)

        if not contexts and not history_text:
            logger.warning("未获取到上下文")
            return []

        system_prompt = (
            "你接收到的是一段群聊记录"
            "请判断其中哪些用户更像机器人（人机）"
            '输出格式必须为 JSON：{"bot_ids": ["123", "456"]}'
            "只填写用户 ID，不要附加解释、不要输出多余文字"
        )
        logger.debug(f"{system_prompt}\n\n{contexts}")

        try:
            llm_response = await get_using.text_chat(
                system_prompt=system_prompt,
                contexts=contexts,
                prompt=history_text,
            )
            text = llm_response.completion_text
            logger.debug(text)
            bids = self._extract_content(text)
            logger.info(f"LLM判断的人机：{bids}")
            return bids

        except Exception as e:
            raise ValueError(f"LLM 调用失败：{e}")

    def _extract_content(self, text: str) -> list[str]:
        if not text:
            return []

        # 去掉 Markdown 包裹
        text = re.sub(r"```json\s*|\s*```", "", text, flags=re.I)

        # 1. 优先解析 JSON
        try:
            data = json.loads(text.strip())
            if isinstance(data, dict) and isinstance(data.get("bot_ids"), list):
                return [str(x) for x in data["bot_ids"]]
        except Exception as e:
            logger.debug(f"JSON 解析失败，原因：{e}，文本：{text}")

        # 2. 兜底正则
        pattern = r"bot_ids\s*[:=]\s*\[([^\]]*)\]"
        if match := re.search(pattern, text, re.IGNORECASE):
            raw = match.group(1)
            ids = re.findall(r"\"(\d+)\"|(\d+)", raw)
            flat_ids = [i[0] or i[1] for i in ids]
            return flat_ids

        return []
