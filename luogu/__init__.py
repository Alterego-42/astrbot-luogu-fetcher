"""
洛谷插件核心模块

提供以下功能：
- 洛谷账号登录（支持手动验证码）
- Cookie管理
- 数据获取
- 截图功能
- 数据存储
"""

from .core import LuoguLogin, LuoguDataFetcher
from .storage import LuoguDataStorage, get_storage
from .screenshot import LuoguScreenshot, get_screenshot
from .login_with_manual_captcha import LuoguLogin as LuoguLoginManual

# 为了兼容性，保留两个版本
# LuoguLoginManual = 手动验证码模式（推荐）
# LuoguLogin = OCR模式（备用）

__version__ = "0.1.0"
__all__ = [
    "LuoguLogin",  # OCR模式（备用）
    "LuoguLoginManual",  # 手动验证码模式（推荐）
    "LuoguDataFetcher", 
    "LuoguDataStorage",
    "LuoguScreenshot",
    "get_storage",
    "get_screenshot"
]
