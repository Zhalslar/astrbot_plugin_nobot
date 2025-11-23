import asyncio

import astrbot.api.message_components as Comp
from astrbot import logger
from astrbot.api.event import filter
from astrbot.api.star import Context, Star, register
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.message.components import (
    At,
    Forward,
    Image,
    Plain,
    Record,
    Reply,
    Video,
)
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.core.star.filter.event_message_type import EventMessageType
from astrbot.core.utils.session_waiter import (
    SessionController,
    session_waiter,
)

from .manager import BotManager
from .utils import get_ats, get_nickname


@register("astrbot_plugin_nobot", "Zhalslar", "找出并禁言群里的人机!", "...", "...")
class NobotPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.conf = config
        # 人机数据
        bot_data_list: list[dict] = config.get("bot_data_list", {})
        bot_data = bot_data_list[0] if bot_data_list else {}
        # 人机管理器
        self.bm = BotManager(bot_data, config)

    @staticmethod
    async def ban(event: AiocqhttpMessageEvent, user_id: str | int, duration: int = 0):
        """禁言/解禁"""
        try:
            await event.bot.set_group_ban(
                group_id=int(event.get_group_id()),
                user_id=int(user_id),
                duration=duration,
            )
        except Exception as e:
            logger.error(f"禁言{user_id}失败: {e}")

    @staticmethod
    async def delete_msg(event: AiocqhttpMessageEvent):
        """撤回消息"""
        try:
            await event.bot.delete_msg(message_id=int(event.message_obj.message_id))
        except Exception as e:
            logger.error(f"撤回消息失败: {e}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("开启人机禁言")
    async def start_ban(self, event: AstrMessageEvent):
        group_id = event.get_group_id()
        self.conf["monitoring_groups"].append(group_id)
        yield event.plain_result("本群已开启人机禁言")
        self.conf.save_config()

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("关闭人机禁言")
    async def stop_ban(self, event: AstrMessageEvent):
        group_id = event.get_group_id()
        self.conf["monitoring_groups"].remove(group_id)
        yield event.plain_result("本群已关闭人机禁言")
        self.conf.save_config()

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("标记人机", alias={"杀"})
    async def label_bot(self, event: AstrMessageEvent):
        """标记人机"""
        group_id = event.get_group_id()
        bot_ids = get_ats(event)

        for bot_id in bot_ids:
            is_success = self.bm.add_bot_record(group_id, bot_id)
            if is_success:
                bot_name = await get_nickname(event, bot_id)
                yield event.plain_result(f"已将【{bot_name}】标记为人机")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("取消标记", alias={"救"})
    async def unlabel_bot(self, event: AiocqhttpMessageEvent):
        """取消人机标记"""
        group_id = event.get_group_id()
        bot_ids = get_ats(event)

        for bot_id in bot_ids:
            self.bm.remove_bot_record(group_id, bot_id)
            await self.ban(event, bot_id, 0)
            bot_name = await get_nickname(event, bot_id)
            yield event.plain_result(f"已取消【{bot_name}】的人机标记")

    @filter.command("人机列表")
    async def bot_list(self, event: AstrMessageEvent):
        """人机列表"""
        group_id = event.get_group_id()
        bot_ids = self.bm.get_bot_ids(group_id)
        bot_names = await asyncio.gather(
            *[get_nickname(event, bot_id) for bot_id in bot_ids]
        )
        yield event.plain_result(f"{bot_names}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("找人机")
    async def handle_empty_mention(self, event: AstrMessageEvent):
        """找出群里的人机"""
        timeout = self.conf["test_interval"] * (len(self.conf["test_cmds"]) + 1)

        @session_waiter(timeout=timeout, record_history_chains=False)  # type: ignore
        async def empty_mention_waiter(
            controller: SessionController, event: AstrMessageEvent
        ):
            chain = event.get_messages()
            message_str = event.message_str
            group_id = event.get_group_id()
            user_id = event.get_sender_id()
            bot_name = await get_nickname(event, user_id)

            reply = f"{bot_name}别乱发消息，小心被标成人机"

            if chain and isinstance(chain[0], Comp.Reply):
                self.bm.add_bot_record(group_id, user_id)
                reply = f"【{bot_name}】合并转发了消息，已标记为人机"

            elif len(message_str) > self.conf["max_length"]:
                self.bm.add_bot_record(group_id, user_id)
                reply = f"【{bot_name}】话太多了，已标记为人机"

            elif message_str:
                for word in self.conf["bot_words"]:
                    if word in message_str:
                        self.bm.add_bot_record(group_id, user_id)
                        bot_name = await get_nickname(event, user_id)
                        reply = f"【{bot_name}】言语中含有人机特征，已标记为人机"
                        break

            message_result = event.make_result()
            message_result.chain = [Comp.Plain(reply)]
            await event.send(message_result)

            controller.keep(timeout=0, reset_timeout=False)

        async def run_empty_mention_waiter():
            try:
                await empty_mention_waiter(event)
            except TimeoutError as _:
                message_result = event.make_result()
                message_result.chain = [Comp.Plain("找完了")]
                await event.send(message_result)
            except Exception as e:
                logger.error("handle_empty_mention error: " + str(e))
            finally:
                event.stop_event()

        async def run_test_cmds():
            for cmd in self.conf["test_cmds"]:
                message_result = event.make_result()
                message_result.chain = [Comp.Plain(f"{cmd}")]
                await event.send(message_result)
                await asyncio.sleep(self.conf["test_interval"])

        await asyncio.gather(run_empty_mention_waiter(), run_test_cmds())

    @filter.event_message_type(EventMessageType.GROUP_MESSAGE)
    async def handle_msg(self, event: AiocqhttpMessageEvent):
        """强制控制人机发言"""
        raw_message = getattr(event.message_obj, "raw_message", None)

        if not (
            raw_message
            and isinstance(raw_message, dict)
            and event.message_obj.message
            and isinstance(
                event.message_obj.message[0],
                Plain | Image | Record | Video | Forward | Reply | At,
            )
        ):
            return

        role = raw_message.get("sender", {}).get("role")
        if role in ["owner", "admin"]:
            return

        group_id = event.get_group_id()
        sender_id = event.get_sender_id()
        # 检查群聊是否在监控列表中以及用户是否为人机
        if (
            group_id not in self.conf["monitoring_groups"]
            or group_id not in self.bm.get_groups()
            or sender_id not in self.bm.get_bot_ids(group_id)
        ):
            return

        # 通融机制
        chain = event.get_messages()
        if chain and isinstance(chain[0], Comp.At):
            await asyncio.sleep(self.conf["ban_sleep"])

        # 检查消息长度
        if len(event.message_str) > self.conf["max_length"]:
            yield event.plain_result("干嘛发这么长的文本！")
            if self.conf["is_delete_msg"]:
                await self.delete_msg(event)
            await self.ban(event, sender_id, self.conf["ban_duration"])
            return

        # 检查发言频率、同时更新发言时间
        if self.bm.check_speak_frequency(
            group_id, sender_id, self.conf["speak_threshold"]
        ):
            event.stop_event()
            if self.conf["is_delete_msg"]:
                await self.delete_msg(event)
            await self.ban(event, sender_id, self.conf["ban_duration"])
            return

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE, priority=99)
    async def on_waking(self, event: AiocqhttpMessageEvent):
        """收到消息后的预处理"""
        # 屏蔽特定指令
        if not event.is_admin() and event.message_str in self.conf["ignore_cmds"]:
            event.stop_event()
            return
