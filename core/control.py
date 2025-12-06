import asyncio
import time

from astrbot.api import logger
from astrbot.api.message_components import (
    At,
    Forward,
    Image,
    Plain,
    Record,
    Reply,
    Video,
)
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.core.star.context import Context

from ..utils import delete_msg, set_group_ban
from .db import BotMonitorDB


class BotController:
    """人机控制器（last_speak 使用内存缓存，不写数据库）"""

    def __init__(self, context: Context, config: AstrBotConfig, db: BotMonitorDB):
        self.context = context
        self.conf = config
        self.db = db
        # {bid: {gid: timestamp}}
        self.ts_cache: dict[str, dict[str, float]] = {}

    def check_and_update_last_speak(self, bid: str, gid: str) -> bool:
        """
        统一管理 last_speak：
        - 自动读取上次发言时间
        - 自动更新为当前时间
        - 返回 True = 说话过快
        """
        now = time.time()

        # 获取 bot 的群发言记录
        bot_map = self.ts_cache.setdefault(bid, {})

        last = bot_map.get(gid)
        bot_map[gid] = now  # 写入最新发言时间

        if last is None:
            return False

        return (now - last) < self.conf["speak_threshold"]

    # ===================== 处罚处理 =====================

    async def _punish(self, event, bid: str):
        """禁言 + 删除消息"""
        gid = event.get_group_id()
        duration = self.conf["ban_duration"]

        if self.conf["is_delete_msg"]:
            await delete_msg(event)

        await set_group_ban(event, bid, duration)
        logger.info(f"{gid} 禁言 {bid} {duration} 秒")

    # ===================== 主处理入口 =====================

    async def handle_msg(self, event: AiocqhttpMessageEvent):
        """主入口: 强制控制人机发言"""

        msg = event.get_messages()
        if not msg or not isinstance(
            msg[0], Plain | Image | Record | Video | Forward | Reply | At
        ):
            return

        gid = event.get_group_id()
        sender_id = event.get_sender_id()

        # 未监控的群，跳过
        if gid not in self.conf["monitoring_groups"]:
            return

        sender_id = event.get_sender_id()

        # 没有人机记录，跳过
        if not self.db.exists(sender_id):
            return

        # 未在本群被标记成人机，跳过
        if sender_id not in await self.db.get(sender_id, "gids", []):
            return

        # 群主/管理员的消息，跳过
        raw = getattr(event.message_obj, "raw_message", {}) or {}
        role = raw.get("sender", {}).get("role")
        if role in ["owner", "admin"]:
            return

        # 被 @ 时宽限(TODO: 待完善)
        # chain = event.get_messages()
        # if chain and isinstance(chain[0], At):
        #     await asyncio.sleep(self.conf["ban_sleep"])

        # 规则一：文本太长
        if len(event.message_str) > self.conf["max_length"]:
            await event.send(event.plain_result("干嘛发这么长的文本！"))
            await self._punish(event, sender_id)
            return

        # 规则二：发言频率过快
        if self.check_and_update_last_speak(sender_id, gid):
            event.stop_event()
            await self._punish(event, sender_id)
            return
