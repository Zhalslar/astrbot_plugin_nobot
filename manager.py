from datetime import datetime, timedelta
from typing import Any

from astrbot import logger
from astrbot.core.config.astrbot_config import AstrBotConfig


class BotManager:
    def __init__(self, bot_data: dict[str, dict[str, str]], config: AstrBotConfig):
        """
        管理多个群组的人机识别记录、监控与禁言状态。
        :param bot_data: 群组数据字典，格式如下：
            {
                "group_id": {
                    "bot_id": "YYYY-MM-DD HH:MM:SS",
                }
            }
        :param config: 配置对象，用于保存更改。
        """
        self.data = bot_data
        self.config = config

    def _get_group(self, group_id: str) -> dict[str, Any] | None:
        """获取指定群组的数据，如果不存在则返回 None 而不是创建新条目。"""
        return self.data.get(group_id, None)

    def _get_or_create_group(self, group_id: str) -> dict[str, Any]:
        """获取指定群组的数据，如果不存在则创建默认值。"""
        return self.data.setdefault(group_id, {})

    def get_groups(self) -> list[str]:
        """获取所有管理的群组 ID 列表。"""
        return list(self.data.keys())

    def get_bot_ids(self, group_id: str) -> list[str]:
        """获取指定群组下的所有 Bot ID。"""
        group = self._get_or_create_group(group_id)
        return list(group.keys())

    def add_bot_record(self, group_id: str, bot_id: str) -> bool:
        """添加 Bot 记录，若已存在则返回 False。"""
        group = self._get_or_create_group(group_id)
        if bot_id not in group:
            group[bot_id] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.config["bot_data_list"] = [self.data]
            self.config.save_config()
            logger.info(f"添加人机记录：群组 {group_id}，Bot ID {bot_id}")
            return True
        return False

    def remove_bot_record(self, group_id: str, bot_id: str) -> bool:
        """移除 Bot 记录。"""
        group = self._get_or_create_group(group_id)
        if bot_id in group:
            del group[bot_id]
            self.config["bot_data_list"] = [self.data]
            self.config.save_config()
            logger.info(f"删除人机记录：群组 {group_id}，Bot ID {bot_id}")
            return True
        return False

    def view_bot_records(self, group_id: str):
        """查看群组下的所有 Bot 记录。"""
        group = self._get_or_create_group(group_id)
        return group

    def check_speak_frequency(self, group_id: str, bot_id: str, threshold: int) -> bool:
        """
        检查发言频率是否超过阈值（单位：秒），不自动创建新的群组条目。
        超过则返回 False，否则更新时间并返回 True。
        """
        group = self._get_group(group_id)
        if group and bot_id in group:
            last_time_str = group[bot_id]
            now = datetime.now()

            group[bot_id] = now.strftime("%Y-%m-%d %H:%M:%S")
            if last_time_str:
                last_time = datetime.strptime(last_time_str, "%Y-%m-%d %H:%M:%S")
                return (now - last_time) < timedelta(seconds=threshold)
            return True  # 第一次发言总是允许
        else:
            return False

