from astrbot.api import logger
from astrbot.core.message.components import At
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)


async def get_nickname(event: AiocqhttpMessageEvent, user_id) -> str:
    """获取指定群友的群昵称或Q名"""
    client = event.bot
    group_id = event.get_group_id()
    all_info = await client.get_group_member_info(
        group_id=int(group_id), user_id=int(user_id)
    )
    return all_info.get("card") or all_info.get("nickname")


def get_ats(event: AiocqhttpMessageEvent) -> list[str]:
    """获取被at者们的id列表"""
    return [
        str(seg.qq)
        for seg in event.get_messages()
        if (isinstance(seg, At) and str(seg.qq) != event.get_self_id())
    ]


@staticmethod
async def set_group_ban(
    event: AiocqhttpMessageEvent, user_id: str | int, duration: int = 0
):
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


def parse_bool(mode: str | bool | None):
    """解析布尔值"""
    mode = str(mode).strip().lower()
    match mode:
        case "开" | "开启" | "启用" | "on" | "true" | "1" | "是" | "真":
            return True
        case "关" | "关闭" | "禁用" | "off" | "false" | "0" | "否" | "假":
            return False
        case _:
            return None