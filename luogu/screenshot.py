"""
洛谷数据截图模块

功能：
1. 截取做题热度图（直接从网页截图，洛谷原版样式）
2. 截取等级分趋势图（直接从网页截图）
3. 截取难度分布统计（直接从网页截图）
4. 截取已通过题目列表
"""

import base64
import io
import os
import time
from typing import Optional, Tuple
from PIL import Image


class LuoguScreenshot:
    """洛谷截图类（基于Playwright）"""

    def __init__(self, page=None):
        """
        初始化截图器

        Args:
            page: Playwright的page实例
        """
        self.page = page

    def set_page(self, page):
        """设置Playwright页面实例"""
        self.page = page

    def screenshot_element(self, selector: str, filename: str = None,
                          padding: dict = None) -> Optional[bytes]:
        """
        截取指定元素的截图

        Args:
            selector: CSS选择器或元素定位器
            filename: 保存文件名
            padding: 额外的内边距 {top, bottom, left, right}

        Returns:
            截图的字节数据
        """
        if not self.page:
            print("未设置Playwright页面")
            return None

        try:
            element = self.page.locator(selector)
            element.wait_for(state='visible', timeout=10000)
            screenshot_bytes = element.screenshot(type='png')

            if filename:
                with open(filename, "wb") as f:
                    f.write(screenshot_bytes)
                print(f"截图已保存: {filename}")

            return screenshot_bytes

        except Exception as e:
            print(f"截图失败: {e}")
            return None

    def screenshot_page(self, filename: str = None) -> Optional[bytes]:
        """截取整个页面"""
        if not self.page:
            print("未设置Playwright页面")
            return None

        try:
            screenshot_bytes = self.page.screenshot(type='png')

            if filename:
                with open(filename, "wb") as f:
                    f.write(screenshot_bytes)
                print(f"页面截图已保存: {filename}")

            return screenshot_bytes

        except Exception as e:
            print(f"页面截图失败: {e}")
            return None

    def capture_heatmap(self, uid: str = None, filename: str = None) -> Optional[bytes]:
        """
        截取洛谷个人主页的做题热度图（洛谷原版样式）

        热度图选择器: .heat-map

        Args:
            uid: 用户ID（可选，如果已设置page且在个人主页）
            filename: 保存文件名

        Returns:
            热度图字节数据
        """
        if not self.page:
            return None

        try:
            # 访问个人主页（如果需要）
            if uid:
                self.page.goto(f"https://www.luogu.com.cn/user/{uid}", timeout=15000)
                self.page.wait_for_load_state("networkidle")
                time.sleep(3)

            # 截取热度图（.heat-map）
            heatmap = self.page.locator('.heat-map')
            if heatmap.count() > 0:
                box = heatmap.bounding_box()
                if box:
                    # 使用clip扩展边距以包含标题
                    screenshot_bytes = self.page.screenshot(
                        type='png',
                        clip={
                            'x': max(0, box['x'] - 10),
                            'y': max(0, box['y'] - 40),
                            'width': min(box['width'] + 20, 900),
                            'height': min(box['height'] + 50, 300)
                        }
                    )
                    if filename:
                        with open(filename, "wb") as f:
                            f.write(screenshot_bytes)
                        print(f"热度图已保存: {filename}")
                    return screenshot_bytes

            return None

        except Exception as e:
            print(f"截取热度图失败: {e}")
            return None

    def capture_rating_trend(self, uid: str = None, filename: str = None) -> Optional[bytes]:
        """
        截取等级分趋势图（洛谷原版样式）

        等级分趋势图是canvas元素

        Args:
            uid: 用户ID（可选）
            filename: 保存文件名

        Returns:
            等级分趋势图字节数据
        """
        if not self.page:
            return None

        try:
            if uid:
                self.page.goto(f"https://www.luogu.com.cn/user/{uid}", timeout=15000)
                self.page.wait_for_load_state("networkidle")
                time.sleep(3)

            # 等级分趋势图是canvas
            canvas = self.page.locator('canvas')
            if canvas.count() > 0:
                box = canvas.bounding_box()
                if box:
                    screenshot_bytes = self.page.screenshot(
                        type='png',
                        clip={
                            'x': max(0, box['x'] - 10),
                            'y': max(0, box['y'] - 40),
                            'width': min(box['width'] + 20, 900),
                            'height': min(box['height'] + 50, 500)
                        }
                    )
                    if filename:
                        with open(filename, "wb") as f:
                            f.write(screenshot_bytes)
                        print(f"等级分趋势图已保存: {filename}")
                    return screenshot_bytes

            return None

        except Exception as e:
            print(f"截取等级分趋势图失败: {e}")
            return None

    def capture_difficulty_stats(self, uid: str = None, filename: str = None) -> Optional[bytes]:
        """
        截取难度分布统计（洛谷原版样式）

        难度分布在练习情况标签页 /user/{uid}/practice

        Args:
            uid: 用户ID（可选）
            filename: 保存文件名

        Returns:
            难度分布字节数据
        """
        if not self.page:
            return None

        try:
            if uid:
                self.page.goto(f"https://www.luogu.com.cn/user/{uid}/practice", timeout=15000)
                self.page.wait_for_load_state("networkidle")
                time.sleep(2)

            # 难度统计区域 - 尝试多种选择器
            selectors = [
                'text=难度统计',      # 标题文本
                '.difficulty-card',   # 难度卡片
                '[class*="difficulty"]',  # 包含difficulty的类
            ]

            for selector in selectors:
                elements = self.page.locator(selector)
                if elements.count() > 0:
                    el = elements.first
                    box = el.bounding_box()
                    if box and box['width'] > 50:
                        screenshot_bytes = self.page.screenshot(
                            type='png',
                            clip={
                                'x': max(0, box['x'] - 20),
                                'y': max(0, box['y'] - 50),
                                'width': min(box['width'] + 40, 1200),
                                'height': min(box['height'] + 60, 400)
                            }
                        )
                        if filename:
                            with open(filename, "wb") as f:
                                f.write(screenshot_bytes)
                            print(f"难度分布已保存: {filename}")
                        return screenshot_bytes

            return None

        except Exception as e:
            print(f"截取难度分布失败: {e}")
            return None

    def capture_practice_page(self, uid: str = None, filename: str = None) -> Optional[bytes]:
        """
        截取练习页面（包含已通过题目和难度分布）

        Args:
            uid: 用户ID（可选）
            filename: 保存文件名

        Returns:
            练习页面截图字节数据
        """
        if not self.page:
            return None

        try:
            if uid:
                self.page.goto(f"https://www.luogu.com.cn/user/{uid}/practice", timeout=15000)
                self.page.wait_for_load_state("networkidle")
                time.sleep(2)

            # 滚动到顶部
            self.page.evaluate('window.scrollTo(0, 0)')
            time.sleep(0.5)

            screenshot_bytes = self.page.screenshot(type='png')

            if filename:
                with open(filename, "wb") as f:
                    f.write(screenshot_bytes)
                print(f"练习页面已保存: {filename}")

            return screenshot_bytes

        except Exception as e:
            print(f"截取练习页面失败: {e}")
            return None

    def capture_profile(self, uid: str, filename: str = None) -> Optional[bytes]:
        """
        截取完整的个人主页

        Args:
            uid: 用户ID
            filename: 保存文件名

        Returns:
            主页截图字节数据
        """
        if not self.page:
            return None

        try:
            self.page.goto(f"https://www.luogu.com.cn/user/{uid}", timeout=15000)
            self.page.wait_for_load_state("networkidle")
            time.sleep(2)

            screenshot_bytes = self.page.screenshot(type='png')

            if filename:
                with open(filename, "wb") as f:
                    f.write(screenshot_bytes)
                print(f"个人主页已保存: {filename}")

            return screenshot_bytes

        except Exception as e:
            print(f"截取个人主页失败: {e}")
            return None

    def capture_all_charts(self, uid: str, save_dir: str = 'screenshots') -> dict:
        """
        截取所有图表

        Args:
            uid: 用户ID
            save_dir: 保存目录

        Returns:
            dict: 包含各个图表截图的字典
        """
        os.makedirs(save_dir, exist_ok=True)
        results = {}

        # 1. 热度图
        print("截取热度图...")
        results['heatmap'] = self.capture_heatmap(
            uid=uid,
            filename=os.path.join(save_dir, 'heatmap_from_web.png')
        )

        # 2. 等级分趋势图
        print("截取等级分趋势图...")
        results['rating_trend'] = self.capture_rating_trend(
            uid=uid,
            filename=os.path.join(save_dir, 'rating_trend_from_web.png')
        )

        # 3. 练习页面（难度分布+题目列表）
        print("截取练习页面...")
        results['practice'] = self.capture_practice_page(
            uid=uid,
            filename=os.path.join(save_dir, 'practice_from_web.png')
        )

        return results

    @staticmethod
    def bytes_to_base64(image_bytes: bytes) -> str:
        """将图片字节转换为base64字符串（便于在QQ中发送）"""
        return base64.b64encode(image_bytes).decode("utf-8")

    @staticmethod
    def save_to_file(image_bytes: bytes, filename: str):
        """保存截图到文件"""
        os.makedirs(os.path.dirname(filename) if os.path.dirname(filename) else '.', exist_ok=True)
        with open(filename, "wb") as f:
            f.write(image_bytes)
        print(f"截图已保存: {filename}")


# 全局截图实例
_screenshot = None


def get_screenshot(page=None) -> LuoguScreenshot:
    """获取全局截图实例"""
    global _screenshot
    if _screenshot is None:
        _screenshot = LuoguScreenshot(page)
    elif page:
        _screenshot.set_page(page)
    return _screenshot
