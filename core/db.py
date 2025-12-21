
import json
from pathlib import Path

from astrbot.api import logger


class BotMonitorDB:
    """
    人机监控数据库（JSON 文件 + 缓存 + 动态字段）
    - 以 bid（机器人ID）为主键
    """

    def __init__(self, data_dir: Path):
        self.json_path = data_dir / "bot_data.json"
        self._cache: dict[str, dict] = {}
        self.default_data = {
            "nickname": "",
            "gids": [],
            "commands": [],
            "ai_confidence": 0.0,
        }

    # ============================== 初始化 ==============================

    async def init(self):
        self.json_path.parent.mkdir(parents=True, exist_ok=True)

        if self.json_path.exists():
            try:
                self._cache = json.loads(self.json_path.read_text("utf-8"))
            except Exception:
                logger.exception("加载 bot JSON 数据失败，已重置为空")
                self._cache = {}
        else:
            self._cache = {}
            self._save_sync()

        logger.info("BotMonitorDB (JSON) initialized (%d bots)", len(self._cache))

    # ============================== 保存 ==============================

    def _save_sync(self):
        """同步写入，避免频繁 async I/O"""
        self.json_path.write_text(
            json.dumps(self._cache, ensure_ascii=False, indent=2),
            "utf-8",
        )

    async def _save(self):
        self._save_sync()

    # ============================== 确保存在 ==============================

    def exists(self, bid: str) -> bool:
        """
        判断 bot 是否存在
        """
        return bid in self._cache

    async def ensure_bot(self, bid: str):
        """
        确保 bot 存在
        """
        if not self.exists(bid):
            # 深拷贝默认数据
            self._cache[bid] = json.loads(json.dumps(self.default_data))
            await self._save()

    # ============================== 极简 API ==============================

    async def all(self, bid: str) -> dict:
        """
        获取整个 bot 数据，并自动补齐缺失字段
        """
        await self.ensure_bot(bid)
        data = self._cache[bid]

        changed = False
        for k, v in self.default_data.items():
            if k not in data:
                data[k] = json.loads(json.dumps(v))
                changed = True

        if changed:
            await self._save()

        return data

    async def get(self, bid: str, field: str, default=None):
        await self.ensure_bot(bid)
        data = self._cache[bid]

        if field not in data:
            data[field] = json.loads(json.dumps(default))
            await self._save()

        return data[field]

    async def set(self, bid: str, field: str, value):
        await self.ensure_bot(bid)
        self._cache[bid][field] = value
        await self._save()

    async def add(self, bid: str, field: str, value):
        """
        列表字段追加
        """
        lst = list(await self.get(bid, field, []))
        if value not in lst:
            lst.append(value)
            await self.set(bid, field, lst)

    async def remove(self, bid: str, field: str, value):
        """
        列表字段删除
        """
        lst = [i for i in await self.get(bid, field, []) if i != value]
        await self.set(bid, field, lst)

    # ============================== 删除 bot ==============================

    async def delete_bot(self, bid: str):
        """彻底删除 bot 记录"""
        if bid in self._cache:
            del self._cache[bid]
            await self._save()

    def get_all_bots(self, gid: str):
        """获取某个群的所有 bot 数据：{bid: bot_data}"""
        return {
            bid: data
            for bid, data in self._cache.items()
            if gid in data.get("gids", [])
        }
