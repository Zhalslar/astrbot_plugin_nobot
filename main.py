
from astrbot.api.event import filter
from astrbot.api.star import Context, Star, register
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.core.star.filter.event_message_type import EventMessageType
from astrbot.core.star.star_tools import StarTools

from .core.control import BotController
from .core.db import BotMonitorDB
from .core.llm import LLMAction
from .utils import get_ats, get_nickname, parse_bool


@register("astrbot_plugin_nobot", "Zhalslar", "...", "...")
class NobotPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.context = context
        self.conf = config
        self.plugin_data_dir = StarTools.get_data_dir("astrbot_plugin_nobot")
        json_path = self.plugin_data_dir / "bot_data.json"

        # 机器人监控数据库
        self.db = BotMonitorDB(json_path)
        # llm 调用类
        self.llm = LLMAction(self.context, self.conf)
        # 人机控制器
        self.controller = BotController(self.context, self.conf, self.db)

    @filter.event_message_type(EventMessageType.GROUP_MESSAGE)
    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("人机禁言")
    async def set_bot_ban(self, event: AstrMessageEvent, mode_str: str | bool | None = None):
        """人机禁言"""
        gid = event.get_group_id()
        mode = parse_bool(mode_str)
        groups = self.conf["monitoring_groups"]
        match mode:
            case True:
                if gid not in groups:
                    groups.append(gid)
                    self.conf.save_config()
            case False:
                if gid in groups:
                    groups.remove(gid)
                    self.conf.save_config()
            case None:
                mode = gid in groups
        yield event.plain_result(f"本群人机禁言：{mode}")


    @filter.event_message_type(EventMessageType.GROUP_MESSAGE)
    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("标记人机")
    async def label_bot(self, event: AiocqhttpMessageEvent):
        """标记人机"""
        gid = event.get_group_id()
        bot_ids = get_ats(event)
        nicknames = []
        for bid in bot_ids:
            nickname = await get_nickname(event, bid)
            await self.db.set(bid, "nickname", nickname)
            await self.db.add(bid, "gids", gid)
            nicknames.append(nickname)
        yield event.plain_result(f"已标记人机: {nicknames}")

    @filter.event_message_type(EventMessageType.GROUP_MESSAGE)
    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("取消标记", alias={"取消人机标记"})
    async def unlabel_bot(self, event: AiocqhttpMessageEvent):
        """取消人机标记"""
        gid = event.get_group_id()
        bot_ids = get_ats(event)
        nicknames = []
        for bid in bot_ids:
            nickname = await get_nickname(event, bid)
            nicknames.append(nickname)
            await self.db.remove(bid, "gids", gid)
        yield event.plain_result(f"已取消人机标记: {nicknames}")

    @filter.event_message_type(EventMessageType.GROUP_MESSAGE)
    @filter.command("人机列表")
    async def bot_list(self, event: AiocqhttpMessageEvent):
        """人机列表（仅展示昵称）"""
        gid = event.get_group_id()
        bots = self.db.get_all_bots(gid)

        if not bots:
            yield event.plain_result("本群暂无人机记录")
            return

        nicks = [data.get("nickname", bid) for bid, data in bots.items()]

        text = "本群人机：" + "\n".join(nicks)
        yield event.plain_result(text)

    @filter.event_message_type(EventMessageType.GROUP_MESSAGE)
    @filter.command("找人机")
    async def handle_empty_mention(self, event: AiocqhttpMessageEvent):
        """找出群里的人机"""
        gid = event.get_group_id()
        bids = await self.llm.judge_bot(event)
        nicknames = []
        for bid in bids:
            nickname = await get_nickname(event, bid)
            nicknames.append(nickname)
            if event.is_admin():
                await self.db.add(bid, "gids", gid)
                await self.db.set(bid, "nickname", nickname)
        yield event.plain_result(f"找到的人机: {nicknames}")


    @filter.event_message_type(EventMessageType.GROUP_MESSAGE)
    async def handle_msg(self, event: AiocqhttpMessageEvent):
        """强制控制人机发言"""
        await self.controller.handle_msg(event)
