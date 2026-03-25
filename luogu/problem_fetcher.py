"""
洛谷题库筛选与跳转模块

功能：
1. 题库列表页面筛选（难度、标签、关键词）
2. 直接定位到目标题目（第 N 个/随机）
3. 获取题目详情并截图题面
"""

import re
import json
import time
import random
import logging
from typing import Dict, List, Optional, Tuple
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright, Page
    from astrbot.api import logger
except ImportError:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    logger = logging.getLogger('luogu_plugin')
    from playwright.sync_api import sync_playwright, Page

from luogu.tags import DIFFICULTY_NAMES, fuzzy_match_tag, KNOWN_TAG_IDS


class ProblemFetcher:
    """洛谷题库筛选与跳转器"""

    # 每页题目数量（洛谷默认每页20题）
    PAGE_SIZE = 20

    def __init__(self, cookies_file: str, headless: bool = True):
        self.cookies_file = cookies_file
        self.headless = headless
        self.browser = None
        self.context = None
        self.page: Optional[Page] = None
        self._playwright = None

    # ── 生命周期 ──────────────────────────────────────────────

    def setup(self) -> 'ProblemFetcher':
        """初始化 Playwright"""
        self._playwright = sync_playwright().start()
        self.browser = self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
            ]
        )
        self.context = self.browser.new_context(
            viewport={'width': 1440, 'height': 900},
            device_scale_factor=2,  # Retina 级别
            ignore_https_errors=True,
        )
        self._load_cookies()
        self.page = self.context.new_page()
        self.page.set_default_timeout(30000)
        return self

    def close(self):
        if self.browser:
            self.browser.close()
        if self._playwright:
            self._playwright.stop()

    def __enter__(self):
        return self.setup()

    def __exit__(self, *_):
        self.close()

    def _load_cookies(self):
        """加载 cookies"""
        if not Path(self.cookies_file).exists():
            return
        with open(self.cookies_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for cookie in data.get('cookies', []):
            try:
                self.context.add_cookies([cookie])
            except Exception:
                pass

    # ── 核心筛选方法 ──────────────────────────────────────────

    def apply_filters(
        self,
        difficulty: int = None,  # 0-7, None 表示不限
        tags: List[str] = None,   # 标签列表，None 表示不限
        keyword: str = None,      # 关键词，None 表示不限
    ) -> Dict:
        """
        应用筛选条件并定位到目标题目。

        策略：
        - 难度：使用 URL 参数 ?difficulty=N（0=暂无评定, 1=入门, 2=普及-, 3=普及/提高-, ...）
        - 标签：使用 UI 交互（打开标签弹窗 → 点击标签 → 确认）
        - 关键词：使用 URL 参数 ?keyword= 或 UI 搜索框

        Returns:
            {
                'success': bool,
                'total': int,        # 总题目数
                'total_pages': int,  # 总页数
                'page_size': int,    # 每页题数（动态检测）
                'page_size_detected': int,  # 实际检测到的每页题数
                'list_url': str,      # 题库列表页 URL（用于后续 navigate_to_problem 恢复）
                'message': str,       # 状态消息
            }
        """
        try:
            # 构建 URL 参数
            params = []
            if difficulty is not None and 0 <= difficulty <= 7:
                # URL difficulty 参数: 0=暂无评定(无param), 1=入门, 2=普及-, 3=普及/提高-, ...
                if difficulty == 0:
                    # 暂无评定：使用 UI 方式
                    logger.info(f'[Luogu] 应用难度筛选（UI）: {DIFFICULTY_NAMES[difficulty]}')
                    self._select_difficulty(difficulty)
                else:
                    params.append(f'difficulty={difficulty}')
            if keyword:
                # URL encode
                encoded_kw = keyword.replace(' ', '+')
                params.append(f'keyword={encoded_kw}')

            # 解析标签为 tag ID
            # 策略：优先用已知 KNOWN_TAG_IDS 中的 ID，兜底用 UI 交互
            tags_to_select_ui = []  # 需要 UI 交互的标签（未找到 ID）
            tag_ids = []            # 已解析的 tag ID 列表
            if tags:
                for tag in tags:
                    tag_id = KNOWN_TAG_IDS.get(tag)
                    if tag_id is not None:
                        tag_ids.append(tag_id)
                        logger.info(f'[Luogu] 标签 "{tag}" -> tag ID {tag_id}')
                    else:
                        tags_to_select_ui.append(tag)

            # 将 tag ID 加入 URL 参数（支持多标签：&tag=302&tag=408）
            for tid in tag_ids:
                params.append(f'tag={tid}')

            # 1. 访问题库列表页（带筛选参数）
            base_url = 'https://www.luogu.com.cn/problem/list'
            if params:
                list_url = f'{base_url}?{"&".join(params)}'
            else:
                list_url = base_url

            logger.info(f'[Luogu] 访问题库列表页: {list_url}')
            self.page.goto(list_url, timeout=20000)
            self.page.wait_for_load_state('domcontentloaded', timeout=15000)
            time.sleep(1.5)

            # 2. 应用剩余标签筛选（UI 交互，未找到 ID 的标签）
            if tags_to_select_ui:
                logger.info(f'[Luogu] 剩余标签 UI 筛选: {tags_to_select_ui}')
                if not self._select_tags(tags_to_select_ui):
                    logger.warning(f'[Luogu] 标签筛选失败')
                    return {'success': False, 'message': f'标签不存在: {tags_to_select_ui}', 'list_url': list_url}
                time.sleep(2)
                # 标签筛选后页面已更新，更新 list_url
                list_url = self.page.url
                logger.info(f'[Luogu] 标签筛选后 URL: {list_url}')

            # 3. 获取筛选结果统计（动态检测 page_size）
            result = self._get_filter_result()
            logger.info(f'[Luogu] 筛选结果: 共 {result.get("total", 0)} 题，{result.get("total_pages", 0)} 页，每页{result.get("page_size_detected", "?")}题')
            result['success'] = True
            result['list_url'] = list_url
            return result

        except Exception as e:
            logger.error(f'[Luogu] 筛选失败: {e}')
            return {'success': False, 'message': str(e), 'list_url': None}

    def _detect_page_size(self, max_retries: int = 3) -> int:
        """
        从当前页动态检测每页题目数量。

        添加重试逻辑：标签筛选后页面可能需要额外时间渲染。
        """
        for attempt in range(max_retries):
            try:
                url = self.page.url
                title = self.page.title()
                all_links = self.page.evaluate(
                    "document.querySelectorAll('a[href]').length"
                )
                count = self.page.evaluate(
                    "document.querySelectorAll('a[href*=\"/problem/P\"], a[href*=\"/problem/p\"]').length"
                )
                logger.info(f'[Luogu] _detect_page_size 第{attempt+1}次: url={url}, 总链接={all_links}, 题目链接={count}')
                if count >= 10:
                    logger.info(f'[Luogu] 检测到每页 {count} 道题')
                    return count
                if 0 < count < 10:
                    # 只有 1-9 题时，直接返回实际数量（不用等待重试）
                    logger.info(f'[Luogu] 检测到 {count} 道题（少于1页）')
                    return count
                if attempt < max_retries - 1:
                    time.sleep(1.5)
            except Exception as e:
                logger.warning(f'[Luogu] _detect_page_size 第{attempt+1}次失败: {e}')
                if attempt < max_retries - 1:
                    time.sleep(1.5)
        logger.warning(f'[Luogu] _detect_page_size 未能检测到足够题目链接，回退到 20')
        return 20  # 兜底默认值

    def navigate_to_problem(self, index: int, list_url: str = None) -> Optional[str]:
        """
        跳转到第 index 个题目（从1开始计数）。

        Args:
            index: 题目序号（从1开始）
            list_url: 可选，题库列表页 URL（用于 page 失效时重新导航）

        Returns:
            题目的 PID（如 'P1001'），或 None 如果失败
        """
        try:
            # 确保 page 有效
            current_url = self.page.url
            if not current_url or current_url == 'about:blank':
                logger.warning(f'[Luogu] page 状态异常（{current_url}），尝试恢复')
                if list_url:
                    self.page.goto(list_url, timeout=20000)
                    self.page.wait_for_load_state('domcontentloaded', timeout=15000)
                    time.sleep(2)
                else:
                    return None

            # 动态检测实际每页题目数量
            page_size = self._detect_page_size()

            # 计算目标页码
            page_num = (index - 1) // page_size + 1
            pos_in_page = (index - 1) % page_size + 1

            logger.info(f'[Luogu] 目标题目: 第{index}题 -> 第{page_num}页，第{pos_in_page}个位置（每页{page_size}题）')

            # 跳转到目标页
            if page_num > 1:
                self._go_to_page(page_num)
                time.sleep(1)

            # 在当前页定位到目标题目
            pid = self._click_problem_at_position(pos_in_page)
            return pid

        except Exception as e:
            logger.error(f'[Luogu] 跳转到题目失败: {e}')
            return None

    def get_random_problem(self, difficulty: int = None, tags: List[str] = None) -> Optional[str]:
        """
        随机获取一个符合条件的题目。

        Returns:
            题目的 PID，或 None 如果失败
        """
        try:
            # 应用筛选
            result = self.apply_filters(difficulty=difficulty, tags=tags)
            if not result.get('success') or result.get('total', 0) == 0:
                return None

            total = result['total']
            # 随机选择一个题目序号
            random_index = random.randint(1, total)
            logger.info(f'[Luogu] 随机选择第 {random_index} 题（共 {total} 题）')

            # 跳转到该题目
            return self.navigate_to_problem(random_index)

        except Exception as e:
            logger.error(f'[Luogu] 随机选题失败: {e}')
            return None

    def get_problem_detail(self, pid: str = None) -> Dict:
        """
        获取题目详情。

        Args:
            pid: 题目编号，如果为 None 则从当前页面提取

        Returns:
            {
                'pid': str,           # 题目编号 P1001
                'title': str,         # 题目标题
                'difficulty': int,   # 难度等级 0-7
                'difficulty_name': str,  # 难度名称
                'passed_rate': str,   # 通过率
                'tags': List[str],    # 标签列表
                'url': str,           # 题目链接
            }
        """
        try:
            # 如果提供了 pid，直接访问该题目页面
            if pid:
                # 统一转为大写 P 开头
                pid_upper = pid.upper()
                if not pid_upper.startswith('P'):
                    pid_upper = 'P' + pid_upper
                pid = pid_upper
                self.page.goto(f'https://www.luogu.com.cn/problem/{pid}', timeout=20000)
                self.page.wait_for_load_state('domcontentloaded', timeout=15000)
                time.sleep(1)
            else:
                # 从当前页面提取（假设已经进入了题目详情页）
                current_url = self.page.url
                pid_match = re.search(r'/problem/([Pp]?\w+)', current_url, re.IGNORECASE)
                if pid_match:
                    pid = pid_match.group(1)
                    pid = 'P' + pid.lstrip('pP')

            # 提取题目信息
            detail = self._extract_problem_detail()
            detail['pid'] = pid
            detail['url'] = f'https://www.luogu.com.cn/problem/{pid}'
            return detail

        except Exception as e:
            logger.error(f'[Luogu] 获取题目详情失败: {e}')
            return {'pid': pid, 'title': '获取失败', 'error': str(e)}

    def screenshot_problem(self, pid: str = None) -> Optional[bytes]:
        """
        截图题目详情页。

        Args:
            pid: 题目编号

        Returns:
            PNG 字节数据，或 None
        """
        try:
            # 确保在题目页面
            if pid:
                # 统一转为大写 P 开头
                pid_upper = pid.upper()
                if not pid_upper.startswith('P'):
                    pid_upper = 'P' + pid_upper
                pid = pid_upper
                self.page.goto(f'https://www.luogu.com.cn/problem/{pid}', timeout=20000)
                self.page.wait_for_load_state('domcontentloaded', timeout=15000)
                time.sleep(1)
            else:
                current_url = self.page.url
                pid_match = re.search(r'/problem/([Pp]?\w+)', current_url, re.IGNORECASE)
                if pid_match:
                    pid = pid_match.group(1)
                    pid = 'P' + pid.lstrip('pP')

            # 截图题目内容区域
            selectors = [
                '.problem-content',
                '.lg-content',
                '#app .content',
                '.main-container',
                '#app',
            ]

            for selector in selectors:
                elements = self.page.locator(selector)
                if elements.count() > 0:
                    el = elements.first
                    box = el.bounding_box()
                    if box and box['width'] > 100 and box['height'] > 100:
                        # 截图
                        img_bytes = self.page.screenshot(
                            type='png',
                            clip={
                                'x': max(0, box['x']),
                                'y': max(0, box['y']),
                                'width': min(box['width'], 1200),
                                'height': min(box['height'], 900),
                            }
                        )
                        logger.info(f'[Luogu] 题目 {pid} 截图成功')
                        return img_bytes

            # 兜底：截取可视区域
            img_bytes = self.page.screenshot(type='png')
            logger.info(f'[Luogu] 题目 {pid} 截图成功（整页模式）')
            return img_bytes

        except Exception as e:
            logger.error(f'[Luogu] 题目截图失败: {e}')
            return None

    # ── 内部辅助方法 ──────────────────────────────────────────

    def _select_difficulty(self, difficulty: int) -> bool:
        """
        选择难度等级。

        正确流程：
        1. 点击难度下拉框（.combo-wrapper.form-item.block-item.combo）
        2. 等待下拉展开（[class*="dropdown"] li）
        3. 点击对应难度选项
        4. 点击"确认"按钮（button.solid 或 button:has-text("确认")）
        """
        try:
            # 点击难度下拉框
            dropdown = self.page.locator('.combo-wrapper.form-item.block-item.combo')
            if dropdown.count() == 0:
                logger.warning('[Luogu] 未找到难度下拉框')
                return False

            dropdown.first.click()
            time.sleep(1)  # 等待下拉展开

            # 找下拉选项列表
            dropdown_options = self.page.locator('[class*="dropdown"] li')
            if dropdown_options.count() == 0:
                logger.warning('[Luogu] 未找到下拉选项')
                return False

            # 找到目标难度并点击
            target_text = DIFFICULTY_NAMES[difficulty]
            clicked = False
            for el in dropdown_options.all():
                try:
                    txt = el.inner_text().strip()
                    if txt == target_text:
                        el.click()
                        clicked = True
                        logger.info(f'[Luogu] 已选择难度: {target_text}')
                        time.sleep(0.5)
                        break
                except Exception:
                    pass

            if not clicked:
                # 备用：直接点击下拉选项中对应索引
                idx = difficulty + 1  # 0=所有, 1=暂无评定, 2=入门, ...
                if dropdown_options.count() > idx:
                    dropdown_options.nth(idx).click()
                    clicked = True
                    time.sleep(0.5)

            if clicked:
                # 点击"确认"按钮应用筛选
                # 按钮可能被左侧导航栏遮挡，必须使用 force=True
                time.sleep(0.3)
                confirm_btn = self.page.locator('button.solid:has-text("确认")')
                if confirm_btn.count() > 0:
                    confirm_btn.first.click(force=True, timeout=5000)
                    logger.info('[Luogu] 已点击确认按钮(force=True)')
                    time.sleep(1.5)
                else:
                    logger.warning('[Luogu] 未找到确认按钮，尝试按 Enter')
                    self.page.keyboard.press('Enter')
                    time.sleep(1.5)

            return clicked
        except Exception as e:
            logger.warning(f'[Luogu] 选择难度失败: {e}')
            return False

    def _select_tags(self, tags: List[str]) -> bool:
        """
        选择标签。

        正确流程：
        1. 点击"算法/来源/时间/状态"按钮打开标签选择器
        2. 找到标签选择弹窗（包含文本"选择标签"的 .l-card）
        3. 在弹窗中查找并点击具体标签（.toggle-tag）
        4. 点击确认按钮
        """
        try:
            # 1. 点击"算法/来源/时间/状态"按钮打开标签选择器
            tag_button = self.page.locator('button:has-text("算法/来源/时间/状态")')
            if tag_button.count() == 0:
                tag_button = self.page.locator('button.block-item:has-text("算法")')

            if tag_button.count() > 0:
                tag_button.first.click(force=True)
                time.sleep(1.5)  # 等待弹窗出现
            else:
                logger.warning('[Luogu] 未找到标签筛选按钮')
                return False

            # 2. 找到标签选择弹窗（包含"选择标签"文本的 .l-card）
            tag_modal = None
            for card in self.page.locator('.l-card').all():
                try:
                    txt = card.inner_text()
                    if '选择标签' in txt:
                        tag_modal = card
                        break
                except:
                    pass

            if not tag_modal:
                logger.warning('[Luogu] 未找到标签选择弹窗')
                return False

            logger.info('[Luogu] 已打开标签选择弹窗')

            # 3. 在弹窗中查找并点击标签
            for tag in tags:
                found = False

                # 查找所有 .toggle-tag 元素
                all_toggle_tags = tag_modal.locator('.toggle-tag')

                for el in all_toggle_tags.all():
                    try:
                        el_text = el.inner_text().strip()
                        # 精确匹配或包含匹配
                        if el_text == tag or tag in el_text:
                            el.click(force=True)
                            time.sleep(0.3)
                            logger.info(f'[Luogu] 已选中标签: {el_text}')
                            found = True
                            break
                    except:
                        pass

                if not found:
                    logger.warning(f'[Luogu] 标签不存在: {tag}')
                    self._close_tag_modal()
                    return False

            # 4. 点击确认按钮
            confirm_btn = tag_modal.locator('button.solid:has-text("确认")')
            if confirm_btn.count() == 0:
                # 尝试在整个页面查找
                confirm_btn = self.page.locator('.l-card button.solid:has-text("确认")')

            if confirm_btn.count() > 0:
                confirm_btn.first.click(force=True)
                logger.info('[Luogu] 已点击确认按钮')
                time.sleep(1.5)
            else:
                logger.warning('[Luogu] 未找到确认按钮，尝试按 Enter')
                self.page.keyboard.press('Enter')
                time.sleep(1.5)

            return True

        except Exception as e:
            logger.warning(f'[Luogu] 选择标签失败: {e}')
            self._close_tag_modal()
            return False

    def _close_tag_modal(self):
        """关闭标签选择弹窗"""
        try:
            # 方法1: 按 ESC
            self.page.keyboard.press('Escape')
            time.sleep(0.3)

            # 方法2: 点击关闭按钮
            close_btn = self.page.locator('.l-card button:has-text("确认"), .l-card .close')
            if close_btn.count() > 0:
                close_btn.first.click(force=True)
                time.sleep(0.3)
        except Exception:
            pass

    def _input_keyword(self, keyword: str):
        """输入关键词"""
        try:
            # 优先用 placeholder 选择器
            search_input = self.page.locator('input[placeholder="算法、标题或题目编号"]')
            if search_input.count() == 0:
                search_input = self.page.locator('.search-text input')

            if search_input.count() > 0:
                search_input.first.fill(keyword)
                time.sleep(0.5)
                search_input.first.press('Enter')
                logger.info(f'[Luogu] 关键词搜索: {keyword}')
        except Exception as e:
            logger.warning(f'[Luogu] 输入关键词失败: {e}')

    def _get_filter_result(self) -> Dict:
        """
        获取筛选结果统计。

        总题目数从 <div class="result"><div class="count">共计 <span class="number">XXX</span> 条结果</div>
        总页数从 .page-bar 提取
        每页题数动态检测（洛谷实际为 50 题/页）
        """
        try:
            # 动态检测每页题目数（基于当前页的题目链接数量）
            page_size = self._detect_page_size()

            html = self.page.content()

            # 提取总题目数
            total = 0
            count_match = re.search(r'class="count">共计\s*<[^>]*class="number"[^>]*>(\d+)</[^>]+>\s*条结果', html)
            if count_match:
                total = int(count_match.group(1))
            else:
                # 备用：直接从 HTML 找
                count_match2 = re.search(r'class="number">(\d+)</span>\s*条结果', html)
                if count_match2:
                    total = int(count_match2.group(1))

            # 提取总页数
            total_pages = 1
            page_match = re.search(r'共\s*<[^>]*>(\d+)</[^>]+>\s*页', html)
            if page_match:
                total_pages = int(page_match.group(1))
            else:
                # 备用
                page_match2 = re.search(r'共\s*(\d+)\s*页', html)
                if page_match2:
                    total_pages = int(page_match2.group(1))

            return {
                'total': total,
                'total_pages': total_pages,
                'page_size': page_size,
                'page_size_detected': page_size,
            }
        except Exception as e:
            logger.warning(f'[Luogu] 获取筛选结果失败: {e}')
            return {'total': 0, 'total_pages': 0, 'page_size': 50, 'page_size_detected': 50}

    def _go_to_page(self, page_num: int):
        """跳转到指定页"""
        try:
            page_buttons = self.page.locator('.page-bar button')

            for btn in page_buttons.all():
                text = btn.inner_text()
                try:
                    num = int(text)
                    if num == page_num:
                        btn.click()
                        time.sleep(1)
                        return
                except ValueError:
                    pass

        except Exception as e:
            logger.warning(f'[Luogu] 跳转页面失败: {e}')

    def _click_problem_at_position(self, position: int) -> Optional[str]:
        """点击当前页第 position 个题目，返回 PID"""
        try:
            # JS 获取所有链接 href
            links = self.page.evaluate(
                "Array.from(document.querySelectorAll('a[href*=\"/problem/p\"], a[href*=\"/problem/P\"]'))"
                ".map(a => a.getAttribute('href'))"
            )
            count = len(links)
            if count == 0:
                logger.warning(f'[Luogu] 当前页找不到题目链接（期望第 {position} 个）')
                return None
            if count < position:
                logger.warning(f'[Luogu] 题目数量不足：当前页 {count} 题，期望第 {position} 个')
                return None

            href = links[position - 1]
            if not href:
                logger.warning(f'[Luogu] 第 {position} 个题目链接为空')
                return None

            # 大小写不敏感匹配 PID
            pid_match = re.search(r'/problem/([Pp]?\w+)', href, re.IGNORECASE)
            if not pid_match:
                logger.warning(f'[Luogu] 无法从链接提取 PID: {href}')
                return None

            pid = pid_match.group(1)
            pid = 'P' + pid.lstrip('pP')
            # 直接跳转到题目 URL（比点击更可靠）
            self.page.goto(f'https://www.luogu.com.cn/problem/{pid}', timeout=15000)
            self.page.wait_for_load_state('domcontentloaded', timeout=12000)
            time.sleep(1.5)
            logger.info(f'[Luogu] 已跳转到题目: {pid}')
            return pid
        except Exception as e:
            logger.warning(f'[Luogu] 点击题目失败: {e}')
            return None

    def _extract_problem_detail(self) -> Dict:
        """从当前页面提取题目详情"""
        try:
            html = self.page.content()

            # 提取难度
            difficulty = 0
            for i, name in enumerate(DIFFICULTY_NAMES):
                if name in html:
                    difficulty = i
                    break

            # 提取标签
            tags = []
            tag_matches = re.findall(r'class="tag-color[^"]*"[^>]*>([^<]+)<', html)
            tags = [t.strip() for t in tag_matches if t.strip()]

            # 提取通过率
            passed_rate = ''
            rate_match = re.search(r'通过率[^>]*>(\d+\.?\d*%)', html)
            if rate_match:
                passed_rate = rate_match.group(1)

            # 提取标题
            title = ''
            title_match = re.search(r'<h1[^>]*class="lfe-h1"[^>]*>([^<]+)<', html)
            if title_match:
                title = title_match.group(1).strip()
            else:
                title_match = re.search(r'<title>([^<]+)</title>', html)
                if title_match:
                    title = title_match.group(1).split(' - ')[0].strip()

            return {
                'title': title,
                'difficulty': difficulty,
                'difficulty_name': DIFFICULTY_NAMES[difficulty] if difficulty < len(DIFFICULTY_NAMES) else '未知',
                'passed_rate': passed_rate,
                'tags': tags[:10],
            }
        except Exception as e:
            logger.warning(f'[Luogu] 提取题目详情失败: {e}')
            return {
                'title': '提取失败',
                'difficulty': 0,
                'difficulty_name': '未知',
                'passed_rate': '',
                'tags': [],
            }

    def extract_markdown_content(self) -> str:
        """
        提取题目内容的 Markdown 文本。

        Returns:
            题目的 Markdown 格式文本
        """
        try:
            # 等待题目内容加载
            self.page.wait_for_load_state('networkidle', timeout=15000)
            time.sleep(1)

            # 使用 JavaScript 提取 Markdown 内容
            md_content = self.page.evaluate("""
                () => {
                    // 查找题目内容区域
                    const contentEl = document.querySelector('.problem-content') 
                        || document.querySelector('.lg-content')
                        || document.querySelector('.main-container')
                        || document.querySelector('#app');

                    if (!contentEl) return '题目内容未找到';

                    // 获取所有文本节点并拼接
                    function getTextWithNewlines(el) {
                        const parts = [];
                        
                        function processNode(node) {
                            if (node.nodeType === Node.TEXT_NODE) {
                                const text = node.textContent.trim();
                                if (text) parts.push(text);
                            } else if (node.nodeType === Node.ELEMENT_NODE) {
                                const tag = node.tagName.toLowerCase();
                                const skipTags = ['script', 'style', 'noscript'];
                                if (skipTags.includes(tag)) return;
                                
                                const isBlock = ['p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                                               'li', 'ul', 'ol', 'pre', 'blockquote', 'tr'].includes(tag);
                                
                                // 递归处理子节点
                                for (const child of node.childNodes) {
                                    processNode(child);
                                }
                                
                                // 块级元素后换行
                                if (isBlock && parts.length > 0 && !parts[parts.length-1].endsWith('\\n')) {
                                    parts.push('\\n');
                                }
                            }
                        }
                        
                        for (const child of el.childNodes) {
                            processNode(child);
                        }
                        
                        return parts.join(' ');
                    }

                    return getTextWithNewlines(contentEl);
                }
            """)

            # 清理和格式化
            lines = md_content.split('\n')
            formatted_lines = []
            for line in lines:
                line = line.strip()
                if line:
                    # 处理标题
                    if line.startswith('#'):
                        formatted_lines.append(line)
                    # 处理代码块标记
                    elif '```' in line or line.startswith('    '):
                        formatted_lines.append(line)
                    else:
                        formatted_lines.append(line)
            
            return '\n\n'.join(formatted_lines)

        except Exception as e:
            logger.warning(f'[Luogu] 提取 Markdown 内容失败: {e}')
            return '提取题目内容失败'


# ── 便捷函数 ──────────────────────────────────────────────────

def jump_to_problem(
    cookies_file: str,
    index: int,
    difficulty: int = None,
    tags: List[str] = None,
    keyword: str = None,
) -> Tuple[Optional[str], Dict]:
    """一步到位：筛选并跳转到指定题目"""
    with ProblemFetcher(cookies_file) as fetcher:
        result = fetcher.apply_filters(difficulty, tags, keyword)
        if not result.get('success'):
            return None, {'error': result.get('message', '筛选失败')}

        pid = fetcher.navigate_to_problem(index)
        if not pid:
            return None, {'error': '跳转题目失败'}

        detail = fetcher.get_problem_detail(pid)
        return pid, detail


def random_problem(
    cookies_file: str,
    difficulty: int = None,
    tags: List[str] = None,
) -> Tuple[Optional[str], Dict]:
    """随机获取一个符合条件的题目"""
    with ProblemFetcher(cookies_file) as fetcher:
        pid = fetcher.get_random_problem(difficulty, tags)
        if not pid:
            return None, {'error': '随机选题失败'}

        detail = fetcher.get_problem_detail(pid)
        return pid, detail


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')

    cookies_file = sys.argv[1] if len(sys.argv) > 1 else 'cookies/cookies_19738806113.json'

    print('测试题库筛选功能...')

    with ProblemFetcher(cookies_file) as fetcher:
        result = fetcher.apply_filters(difficulty=1)  # 入门
        print(f'筛选结果: {result}')

        pid = fetcher.get_random_problem(difficulty=1)
        if pid:
            print(f'随机题目: {pid}')
            detail = fetcher.get_problem_detail(pid)
            print(f'详情: {detail}')
