import json
import re
from typing import Any

from aiocqhttp import CQHttp

from astrbot.api import logger
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.star.context import Context


class LLMAction:
    def __init__(self, context: Context, config: AstrBotConfig):
        self.context = context
        self.config = config

    def _build_context(
        self, round_messages: list[dict[str, Any]]
    ) -> list[dict[str, str]]:
        """
        把所有回合里的纯文本消息打包成 openai-style 的 user 上下文。
        """
        contexts: list[dict[str, str]] = []
        for msg in round_messages:
            # 提取并拼接所有 text 片段
            text_segments = [
                seg["data"]["text"] for seg in msg["message"] if seg["type"] == "text"
            ]

            text = f"{msg['sender']['nickname']}: {''.join(text_segments).strip()}"
            # 仅当真正说了话才保留
            if text:
                contexts.append({"role": "user", "content": text})
        return contexts

    async def _get_msg_contexts(self, client: CQHttp, group_id: str) -> list[dict]:
        """获取群聊历史消息"""
        message_seq = 0
        contexts: list[dict] = []
        while len(contexts) < self.config["max_history_msg"]:
            payloads = {
                "group_id": group_id,
                "message_seq": message_seq,
                "count": 200,
                "reverseOrder": True,
            }
            result: dict = await client.api.call_action(
                "get_group_msg_history", **payloads
            )
            round_messages = result["messages"]
            if not round_messages:
                break
            message_seq = round_messages[0]["message_id"]

            contexts.extend(self._build_context(round_messages))
        return contexts

    def _extract_content(self, text: str) -> list[str]:
        """
        提取 LLM 返回的 bot_ids 列表
        """
        if not text:
            return []

        # 1. 优先解析 JSON
        try:
            data = json.loads(text)
            if isinstance(data, dict) and isinstance(data.get("bot_ids"), list):
                return [str(x) for x in data["bot_ids"]]
        except Exception:
            pass  # 继续走正则

        # 2. 兜底方案：正则匹配 ID
        # 支持格式：bot_ids: ["123","456"]  或 bot_ids=[123,456]
        pattern = r"bot_ids\s*[:=]\s*\[([^\]]*)\]"
        if match := re.search(pattern, text, re.IGNORECASE):
            raw = match.group(1)
            # 再抓 ID：整数或字符串
            ids = re.findall(r"\"(\d+)\"|(\d+)", raw)
            flat_ids = [i[0] or i[1] for i in ids]
            return flat_ids

        return []

    async def judge_bot(self,client: CQHttp, group_id: str) -> list[str]:
        """根据群聊的聊天记录判断人机，返回人机 ID 列表"""
        get_using = self.context.get_using_provider()
        if not get_using:
            raise ValueError("未配置 LLM 提供商")

        contexts = await self._get_msg_contexts(client, group_id)

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
            )
            bids = self._extract_content(llm_response.completion_text)
            logger.info(f"LLM判断的人机：{bids}")
            return bids

        except Exception as e:
            raise ValueError(f"LLM 调用失败：{e}")
