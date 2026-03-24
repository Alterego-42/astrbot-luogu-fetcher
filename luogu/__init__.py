"""
洛谷插件核心模块

提供以下功能：
- 数据获取
- 截图功能
- 图表生成
- 数据存储
"""

from .data_fetcher import LuoguDataFetcher
from .chart_generator import ChartGenerator
from .screenshot import LuoguScreenshot, get_screenshot
from .storage import LuoguDataStorage, get_storage

__version__ = "0.1.0"
__all__ = [
    "LuoguDataFetcher",
    "ChartGenerator",
    "LuoguScreenshot",
    "LuoguDataStorage",
    "get_storage",
    "get_screenshot"
]
