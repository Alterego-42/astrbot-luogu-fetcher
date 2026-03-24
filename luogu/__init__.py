"""
洛谷插件核心模块

提供以下功能：
- 洛谷账号登录（支持手动验证码）
- Cookie管理
- 数据获取
- 截图功能
- 数据存储
"""

from .login import LuoguLogin
from .data_fetcher import LuoguDataFetcher
from .storage import LuoguDataStorage, get_storage
from .screenshot import LuoguScreenshot, get_screenshot

__version__ = "0.1.0"
__all__ = [
    "LuoguLogin",
    "LuoguDataFetcher",
    "LuoguDataStorage",
    "LuoguScreenshot",
    "get_storage",
    "get_screenshot"
]
