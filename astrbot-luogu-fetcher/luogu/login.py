"""
洛谷登录核心模块
使用Playwright实现自动登录，处理验证码
"""
import asyncio
import os
import sys
from pathlib import Path
from typing import Optional, Callable, Awaitable, Tuple
from dataclasses import dataclass

from playwright.async_api import async_playwright, Playwright, Browser, BrowserContext, Page
from playwright.async_api import Error as PlaywrightError

from .captcha import CaptchaHandler, CaptchaMode
from .storage import LuoguStorage


@dataclass
class LoginResult:
    """登录结果"""
    success: bool
    message: str
    cookies: Optional[list] = None
    luogu_uid: Optional[str] = None
    captcha_image_path: Optional[str] = None  # 如果需要手动输入验证码，返回图片路径


class LuoguLogin:
    """洛谷登录器"""

    # 登录页面URL
    LOGIN_URL = "https://www.luogu.com.cn/auth/login"
    # 验证码图片CSS选择器
    CAPTCHA_IMG_SELECTOR = "#app > div.main-wrapper.lfe-body > div > div > div > div.step-2.active > div.methods > div > div > div > img"
    # 验证码输入框选择器
    CAPTCHA_INPUT_SELECTOR = "#app > div.main-wrapper.lfe-body > div > div > div > div.step-2.active > div.methods > div > div > input"
    # 密码输入框选择器
    PASSWORD_INPUT_SELECTOR = "#app > div.main-wrapper.lfe-body > div > div > div > div.step-2.active > div.methods > div > input[type=password]"
    # 用户名输入框选择器
    USERNAME_INPUT_SELECTOR = "#app > div.main-wrapper.lfe-body > div > div > div > div.step-1.active > div:nth-child(1) > div.input-group > input[type=text]"
    # 下一步按钮选择器 (step-1)
    NEXT_BTN_SELECTOR = "#app > div.main-wrapper.lfe-body > div > div > div > div.step-1.active > div:nth-child(1) > button"
    # 登录按钮选择器 (step-2)
    LOGIN_BTN_SELECTOR = "#app > div.main-wrapper.lfe-body > div > div > div > div.step-2.active > div.methods > div > button"

    def __init__(
        self,
        storage: LuoguStorage,
        captcha_mode: CaptchaMode = CaptchaMode.AUTO,
        captcha_dir: Optional[Path] = None,
        headless: bool = True
    ):
        """
        初始化登录器

        Args:
            storage: 数据存储器
            captcha_mode: 验证码处理模式
            captcha_dir: 验证码图片保存目录
            headless: 是否无头模式运行浏览器
        """
        self.storage = storage
        self.captcha_handler = CaptchaHandler(mode=captcha_mode)
        self.headless = headless

        # 设置验证码图片保存目录
        if captcha_dir is None:
            captcha_dir = storage.data_dir / "captcha"
        self.captcha_dir = captcha_dir
        self.captcha_dir.mkdir(parents=True, exist_ok=True)

        # Playwright实例
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self._init_browser()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器退出"""
        await self.close()

    async def _init_browser(self) -> None:
        """初始化浏览器"""
        if self._playwright is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=self.headless)
            # 每次登录创建新的context，使用独立的cookie存储
            self._context = await self._browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )

    async def close(self) -> None:
        """关闭浏览器"""
        if self._context:
            await self._context.close()
            self._context = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def login(
        self,
        username: str,
        password: str,
        qq_id: Optional[str] = None,
        max_retries: int = 3,
        on_captcha_needed: Optional[Callable[[str], Awaitable[None]]] = None
    ) -> LoginResult:
        """
        执行登录

        Args:
            username: 用户名(手机号或邮箱)
            password: 密码
            qq_id: QQ用户ID，用于保存Cookie
            max_retries: 最大重试次数
            on_captcha_needed: 当需要手动输入验证码时的回调，参数为验证码图片路径

        Returns:
            LoginResult: 登录结果
        """
        if self._context is None:
            await self._init_browser()

        page = await self._context.new_page()

        try:
            # 1. 访问登录页面
            print(f"[LuoguLogin] 访问登录页面: {self.LOGIN_URL}")
            await page.goto(self.LOGIN_URL, wait_until="networkidle")
            await asyncio.sleep(1)  # 等待页面渲染

            # 2. 输入用户名
            print(f"[LuoguLogin] 输入用户名: {username}")
            await page.locator(self.USERNAME_INPUT_SELECTOR).fill(username)
            await page.locator(self.NEXT_BTN_SELECTOR).click()
            await asyncio.sleep(1)  # 等待step切换

            # 3. 输入密码
            print(f"[LuoguLogin] 输入密码")
            await page.locator(self.PASSWORD_INPUT_SELECTOR).fill(password)
            await asyncio.sleep(0.5)

            # 4. 处理验证码（可能多次尝试）
            for attempt in range(1, max_retries + 1):
                print(f"[LuoguLogin] 第 {attempt} 次尝试登录")

                # 截图验证码
                captcha_path = self.captcha_dir / f"captcha_{qq_id or 'unknown'}_{attempt}.png"
                await page.locator(self.CAPTCHA_IMG_SELECTOR).screenshot(path=str(captcha_path))
                print(f"[LuoguLogin] 验证码图片已保存: {captcha_path}")

                # 识别验证码
                captcha_code = None
                if self.captcha_handler.mode == CaptchaMode.AUTO:
                    captcha_code = await self.captcha_handler.recognize_from_file(str(captcha_path))

                # 如果需要手动输入
                if captcha_code is None and on_captcha_needed:
                    await on_captcha_needed(str(captcha_path))
                    # 这里需要等待外部设置验证码，实际使用时通过session_waiter实现
                    # 暂时返回需要手动输入
                    await page.close()
                    return LoginResult(
                        success=False,
                        message="需要手动输入验证码",
                        captcha_image_path=str(captcha_path)
                    )

                if captcha_code is None:
                    print(f"[LuoguLogin] 无法识别验证码，跳过此次尝试")
                    # 点击刷新验证码
                    await page.locator(self.CAPTCHA_IMG_SELECTOR).click()
                    await asyncio.sleep(0.5)
                    continue

                # 填写验证码并提交
                print(f"[LuoguLogin] 填写验证码: {captcha_code}")
                await page.locator(self.CAPTCHA_INPUT_SELECTOR).fill(captcha_code)
                await page.locator(self.LOGIN_BTN_SELECTOR).click()

                # 等待登录结果
                try:
                    # 检查是否跳转到首页（登录成功）
                    await page.wait_for_url(
                        lambda url: "luogu.com.cn" in url and "/auth/login" not in url,
                        timeout=8000
                    )
                    print(f"[LuoguLogin] 登录成功！")

                    # 获取Cookie
                    cookies = await self._context.cookies()
                    luogu_uid = self._get_luogu_uid_from_cookies(cookies)
                    print(f"[LuoguLogin] 洛谷UID: {luogu_uid}")

                    # 保存Cookie
                    if qq_id and cookies:
                        self.storage.save_cookies(qq_id, cookies, luogu_uid)

                    await page.close()
                    return LoginResult(
                        success=True,
                        message="登录成功",
                        cookies=cookies,
                        luogu_uid=luogu_uid
                    )

                except asyncio.TimeoutError:
                    print(f"[LuoguLogin] 登录超时，尝试刷新验证码")
                    if attempt < max_retries:
                        # 点击刷新验证码
                        await page.locator(self.CAPTCHA_IMG_SELECTOR).click()
                        await asyncio.sleep(0.5)
                        continue
                    else:
                        await page.close()
                        return LoginResult(
                            success=False,
                            message="登录失败，已达最大重试次数"
                        )

            # 达到最大重试次数
            await page.close()
            return LoginResult(
                success=False,
                message=f"登录失败，已尝试 {max_retries} 次"
            )

        except Exception as e:
            print(f"[LuoguLogin] 登录异常: {e}")
            await page.close()
            return LoginResult(
                success=False,
                message=f"登录异常: {str(e)}"
            )

    async def login_with_manual_captcha(
        self,
        username: str,
        password: str,
        captcha_code: str,
        qq_id: Optional[str] = None
    ) -> LoginResult:
        """
        使用手动输入的验证码登录

        Args:
            username: 用户名
            password: 密码
            captcha_code: 验证码
            qq_id: QQ用户ID

        Returns:
            LoginResult: 登录结果
        """
        if self._context is None:
            await self._init_browser()

        page = await self._context.new_page()

        try:
            # 访问登录页面
            await page.goto(self.LOGIN_URL, wait_until="networkidle")
            await asyncio.sleep(1)

            # 输入用户名
            await page.locator(self.USERNAME_INPUT_SELECTOR).fill(username)
            await page.locator(self.NEXT_BTN_SELECTOR).click()
            await asyncio.sleep(1)

            # 输入密码
            await page.locator(self.PASSWORD_INPUT_SELECTOR).fill(password)
            await asyncio.sleep(0.5)

            # 输入验证码
            await page.locator(self.CAPTCHA_INPUT_SELECTOR).fill(captcha_code)
            await page.locator(self.LOGIN_BTN_SELECTOR).click()

            # 等待登录结果
            try:
                await page.wait_for_url(
                    lambda url: "luogu.com.cn" in url and "/auth/login" not in url,
                    timeout=8000
                )

                cookies = await self._context.cookies()
                luogu_uid = self._get_luogu_uid_from_cookies(cookies)

                if qq_id and cookies:
                    self.storage.save_cookies(qq_id, cookies, luogu_uid)

                await page.close()
                return LoginResult(
                    success=True,
                    message="登录成功",
                    cookies=cookies,
                    luogu_uid=luogu_uid
                )

            except asyncio.TimeoutError:
                await page.close()
                return LoginResult(
                    success=False,
                    message="验证码错误或登录失败"
                )

        except Exception as e:
            await page.close()
            return LoginResult(
                success=False,
                message=f"登录异常: {str(e)}"
            )

    def _get_luogu_uid_from_cookies(self, cookies: list) -> Optional[str]:
        """从Cookie中提取洛谷UID"""
        for cookie in cookies:
            if cookie.get("name") == "__uid":
                return cookie.get("value")
        return None

    async def check_login_status(self, cookies: list) -> Tuple[bool, Optional[str]]:
        """
        检查登录状态

        Args:
            cookies: Cookie列表

        Returns:
            (是否登录, 用户名或UID)
        """
        if self._context is None:
            await self._init_browser()

        # 设置Cookie
        await self._context.add_cookies(cookies)

        page = await self._context.new_page()
        try:
            # 访问用户主页API
            await page.goto("https://luogu.com.cn/", wait_until="networkidle")
            await asyncio.sleep(1)

            # 检查是否包含用户信息
            content = await page.content()
            if "__NEXT_DATA__" in content or "window.__INITIAL_STATE__" in content:
                await page.close()
                return True, None

            await page.close()
            return False, None

        except Exception as e:
            await page.close()
            return False, str(e)

    @staticmethod
    async def quick_login(username: str, password: str, captcha_mode: CaptchaMode = CaptchaMode.AUTO) -> LoginResult:
        """
        快速登录（独立使用，不保存到存储）

        Args:
            username: 用户名
            password: 密码
            captcha_mode: 验证码模式

        Returns:
            LoginResult: 登录结果
        """
        async with LuoguLogin(
            storage=None,
            captcha_mode=captcha_mode
        ) as login:
            return await login.login(username, password)


# 辅助函数：检查Playwright是否安装
def check_playwright_installed() -> bool:
    """检查Playwright是否正确安装"""
    try:
        from playwright.sync_api import sync_playwright
        return True
    except ImportError:
        return False


def ensure_playwright_browsers() -> bool:
    """确保Playwright浏览器已安装"""
    import subprocess
    try:
        result = subprocess.run(
            ["playwright", "install", "chromium"],
            capture_output=True,
            text=True,
            timeout=300
        )
        return result.returncode == 0
    except Exception as e:
        print(f"安装Playwright浏览器失败: {e}")
        return False
