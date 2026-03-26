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
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright, Page
    from astrbot.api import logger
except ImportError:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    logger = logging.getLogger('luogu_plugin')
    from playwright.sync_api import sync_playwright, Page

from luogu.tags import DIFFICULTY_NAMES, KNOWN_TAG_IDS


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
            selected_tag_map: Dict[str, str] = {}
            missing_tags: List[str] = []
            if tags_to_select_ui:
                logger.info(f'[Luogu] 剩余标签 UI 筛选: {tags_to_select_ui}')
                selection = self._select_tags(tags_to_select_ui)
                missing_tags = selection.get('missing', [])
                selected_tag_map = {
                    item['requested']: item['matched']
                    for item in selection.get('selected', [])
                }
                if missing_tags and not tag_ids and not selected_tag_map:
                    logger.warning('[Luogu] 标签筛选失败：所有待选标签都不存在')
                    return {
                        'success': False,
                        'message': f'标签不存在: {missing_tags}',
                        'list_url': list_url,
                        'missing_tags': missing_tags,
                        'applied_tags': [],
                    }
                time.sleep(2)
                # 标签筛选后页面已更新，更新 list_url
                list_url = self.page.url
                logger.info(f'[Luogu] 标签筛选后 URL: {list_url}')

            # 3. 获取筛选结果统计（动态检测 page_size）
            result = self._get_filter_result()
            logger.info(f'[Luogu] 筛选结果: 共 {result.get("total", 0)} 题，{result.get("total_pages", 0)} 页，每页{result.get("page_size_detected", "?")}题')
            applied_tags: List[str] = []
            for tag in tags or []:
                if tag in KNOWN_TAG_IDS:
                    applied_tags.append(tag)
                elif tag in selected_tag_map:
                    applied_tags.append(selected_tag_map[tag])
            result['success'] = True
            result['list_url'] = list_url
            result['missing_tags'] = missing_tags
            result['applied_tags'] = applied_tags
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

            # 边界保护：处理 index 超出范围的情况
            # 如果 index > 总题目数，取最后一题
            actual_index = min(index, page_size)  # 临时用 page_size 估算，实际点击时会检测
            logger.info(f'[Luogu] 目标题目: 第{index}题, 估算每页{page_size}题')

            # 计算目标页码
            page_num = (index - 1) // page_size + 1
            pos_in_page = (index - 1) % page_size + 1

            logger.info(f'[Luogu] 目标题目: 第{index}题 -> 第{page_num}页，第{pos_in_page}个位置（每页{page_size}题）')

            # 跳转到目标页
            if page_num > 1:
                self._go_to_page(page_num)
                time.sleep(1.5)
                # 跳转后重新检测 page_size（末页可能不同）
                page_size = self._detect_page_size()
                # 重新计算位置
                pos_in_page = (index - 1) % page_size + 1
                logger.info(f'[Luogu] 跳转后重新检测: 每页{page_size}题，第{pos_in_page}个位置')

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

    def _select_tags(self, tags: List[str]) -> Dict[str, Any]:
        """
        选择标签（支持多 Tab：算法/来源/时间/区域/特殊题目）。

        正确流程：
        1. 点击"算法/来源/时间/状态"按钮打开标签选择器（.modal）
        2. 找到标签选择弹窗（.modal，包含"选择标签"文本）
        3. 对每个标签，先在当前 Tab 查找，找不到则遍历切换所有 Tab
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
                return {'selected': [], 'missing': tags[:]}

            # 2. 找到标签选择弹窗（.modal，包含"选择标签"文本）
            tag_modal = None
            # 优先找 .modal 中的 l-card
            for modal in self.page.locator('.modal').all():
                try:
                    txt = modal.inner_text()
                    if '选择标签' in txt:
                        tag_modal = modal
                        break
                except:
                    pass
            
            # 备用：找包含"选择标签"的 .l-card
            if not tag_modal:
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
                return {'selected': [], 'missing': tags[:]}

            logger.info('[Luogu] 已打开标签选择弹窗')

            # 3. 对每个标签，尝试在当前及所有 Tab 中查找
            selected = []
            missing = []
            for tag in tags:
                matched_text = self._find_and_click_tag_in_modal(tag_modal, tag)

                if not matched_text:
                    logger.warning(f'[Luogu] 标签不存在（所有 Tab 已搜索）: {tag}')
                    missing.append(tag)
                    continue
                selected.append({'requested': tag, 'matched': matched_text})

            # 4. 点击确认按钮（在 modal 的 l-card 内）
            confirm_btn = tag_modal.locator('button.solid:has-text("确认")')
            if confirm_btn.count() == 0:
                # 尝试在整个 modal 查找
                confirm_btn = self.page.locator('.modal button.solid:has-text("确认")')

            if confirm_btn.count() > 0:
                confirm_btn.first.click(force=True)
                logger.info('[Luogu] 已点击确认按钮')
                time.sleep(1.5)
            else:
                logger.warning('[Luogu] 未找到确认按钮，尝试按 Enter')
                self.page.keyboard.press('Enter')
                time.sleep(1.5)

            return {'selected': selected, 'missing': missing}

        except Exception as e:
            logger.warning(f'[Luogu] 选择标签失败: {e}')
            self._close_tag_modal()
            return {'selected': [], 'missing': tags[:]}

    def _find_and_click_tag_in_modal(self, tag_modal, tag: str) -> Optional[str]:
        """
        在弹窗中查找并点击指定标签，必要时切换 Tab。

        核心问题：洛谷标签弹窗在 .modal > .l-card 中，Tab 是 .entry 元素。
        
        正确策略：
        1. 先在当前已显示的 .toggle-tag 中查找
        2. 用 JS 在 modal 内搜索标签元素
        3. 如果未找到，切换 Tab 后重试
        """
        # Step 1: 先在当前已显示的 .toggle-tag 中查找
        direct_match = self._try_click_tag(tag_modal, tag)
        if direct_match:
            return direct_match

        # Step 2: 用 JS 在 modal 内搜索标签
        js_match = self._js_find_and_click_tag_in_modal(tag)
        if js_match:
            return js_match

        # Step 3: 仍未找到 → 切换 Tab 后重试
        # Tab 是 .modal .entry 元素（span.entry）
        tab_entries = self.page.evaluate("""
            () => {
                const modal = document.querySelector('.modal');
                if (!modal) return [];
                const entries = modal.querySelectorAll('.entry');
                return Array.from(entries).map(el => el.innerText.trim());
            }
        """)
        
        if not tab_entries:
            logger.warning('[Luogu] 未找到任何 Tab 按钮')
            return None

        logger.info(f'[Luogu] 弹窗 Tab 列表: {tab_entries}')

        # 遍历所有 Tab
        for tab_text in tab_entries:
            if not tab_text:
                continue
            logger.info(f'[Luogu] 尝试切换到 Tab: "{tab_text}"')
            
            # 点击这个 Tab
            clicked = self.page.evaluate(f"""
                () => {{
                    const modal = document.querySelector('.modal');
                    if (!modal) return false;
                    const entries = modal.querySelectorAll('.entry');
                    for (const el of entries) {{
                        if (el.innerText.trim() === '{tab_text}') {{
                            el.click();
                            return true;
                        }}
                    }}
                    return false;
                }}
            """)
            if clicked:
                time.sleep(0.8)
                # 在当前 Tab 中查找标签
                direct_match = self._try_click_tag(tag_modal, tag)
                if direct_match:
                    return direct_match
                js_match = self._js_find_and_click_tag_in_modal(tag)
                if js_match:
                    return js_match

        return None

    def _js_find_and_click_tag_in_modal(self, tag: str) -> Optional[str]:
        """
        用 JS 在 modal 内搜索并点击标签元素。
        """
        for strategy in ('exact', 'fuzzy'):
            try:
                match_text = self.page.evaluate(f"""
                    () => {{
                        const modal = document.querySelector('.modal');
                        if (!modal) return null;
                        const tags = modal.querySelectorAll('.toggle-tag');
                        for (const el of tags) {{
                            const text = (el.innerText || '').trim();
                            let match = false;
                            if ('{strategy}' === 'exact') {{
                                match = text === '{tag}';
                            }} else {{
                                match = text.includes('{tag}');
                            }}
                            if (match) {{
                                el.click();
                                return text;
                            }}
                        }}
                        return null;
                    }}
                """)
                if match_text:
                    logger.info(
                        f'[Luogu] JS {"精确" if strategy == "exact" else "模糊"}匹配点击标签: {match_text}'
                    )
                    time.sleep(0.3)
                    return str(match_text)
            except Exception as e:
                logger.debug(f'[Luogu] JS 查找标签（第{strategy}策略）失败: {e}')
        return None

    def _try_click_tag(self, tag_modal, tag: str) -> Optional[str]:
        """在 tag_modal 中查找并点击 .toggle-tag，返回是否成功"""
        all_toggle_tags = tag_modal.locator('.toggle-tag')
        for el in all_toggle_tags.all():
            try:
                el_text = el.inner_text().strip()
                if el_text == tag or tag in el_text:
                    el.click(force=True)
                    time.sleep(0.3)
                    logger.info(f'[Luogu] 已选中标签: {el_text}')
                    return el_text
            except:
                pass
        return None



    def _close_tag_modal(self):
        """关闭标签选择弹窗"""
        try:
            # 方法1: 按 ESC
            self.page.keyboard.press('Escape')
            time.sleep(0.3)

            # 方法2: 点击确认按钮（modal 内的确认按钮）
            confirm_btn = self.page.locator('.modal button.solid:has-text("确认")')
            if confirm_btn.count() > 0:
                confirm_btn.first.click(force=True)
                time.sleep(0.3)
                return

            # 方法3: 点击关闭按钮
            close_btn = self.page.locator('.modal .close, .modal button:has-text("确认")')
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

    def extract_markdown_content(self, pid: str = None) -> str:
        """
        获取题目 Markdown 内容。

        优先方案：
        1. 解析页面内嵌的 `#lentille-context` JSON
        2. 解析页面中隐藏的 `.lfe-marked-original` 原文块
        3. 尝试旧的复制按钮 / API 方案
        4. 最后兜底提取当前页面文本

        Args:
            pid: 题目编号（如 P1047）。若为 None，则从当前页面 URL 提取。

        Returns:
            题目的原始 Markdown 格式文本
        """
        try:
            # 确保在题目页面
            if not pid:
                current_url = self.page.url
                pid_match = re.search(r'/problem/([Pp]?\w+)', current_url, re.IGNORECASE)
                if pid_match:
                    pid = pid_match.group(1)
                    pid = 'P' + pid.lstrip('pP')

            if not pid:
                return '（未能确定题目编号）'

            # 新主路径：页面内嵌 JSON，结构稳定且不依赖剪贴板权限
            md_content = self._extract_markdown_from_lentille_context()
            if md_content and len(md_content) > 20:
                logger.info(f'[Luogu] 通过 lentille-context 获取 Markdown，长度: {len(md_content)}')
                return md_content

            # 次优路径：页面隐藏的原始 Markdown 块
            md_content = self._extract_markdown_from_hidden_original()
            if md_content and len(md_content) > 20:
                logger.info(f'[Luogu] 通过隐藏原文块获取 Markdown，长度: {len(md_content)}')
                return md_content

            # 旧路径：尝试点击「复制 Markdown」按钮
            md_content = self._try_click_copy_markdown_button()
            if md_content and len(md_content) > 20:
                logger.info(f'[Luogu] 通过复制按钮获取 Markdown，长度: {len(md_content)}')
                return md_content

            # 旧接口兜底：保留用于兼容未来页面调整
            logger.info('[Luogu] 页面内嵌内容未命中，尝试旧 API 兜底')
            return self._fetch_markdown_via_api(pid)

        except Exception as e:
            logger.error(f'[Luogu] 获取 Markdown 失败: {e}')
            return f'（获取题目内容失败: {e}）'

    def _extract_markdown_from_lentille_context(self) -> Optional[str]:
        """从页面内嵌的 `#lentille-context` JSON 中重建 Markdown。"""
        try:
            payload = self.page.evaluate("""
                () => {
                    const script = document.querySelector('#lentille-context');
                    if (!script) {
                        return { error: 'missing lentille-context' };
                    }
                    try {
                        const data = JSON.parse(script.textContent || '{}');
                        const problem = (((data || {}).data || {}).problem || {});
                        return {
                            pid: problem.pid || '',
                            title: problem.title || '',
                            contenu: problem.contenu || {},
                            samples: problem.samples || [],
                            translation: problem.translation || null,
                        };
                    } catch (error) {
                        return { error: String(error) };
                    }
                }
            """)
        except Exception as e:
            logger.warning(f'[Luogu] 读取 lentille-context 失败: {e}')
            return None

        if not isinstance(payload, dict):
            return None
        if payload.get('error'):
            logger.info(f'[Luogu] lentille-context 不可用: {payload["error"]}')
            return None

        contenu = payload.get('contenu')
        samples = payload.get('samples')
        translation = payload.get('translation')

        sections: List[str] = []
        ordered_fields = [
            ('background', '题目背景'),
            ('description', '题目描述'),
            ('formatI', '输入格式'),
            ('formatO', '输出格式'),
            ('hint', '说明/提示'),
        ]

        for field_name, heading in ordered_fields:
            raw = ''
            if isinstance(contenu, dict):
                raw = str(contenu.get(field_name) or '').strip()
            if raw:
                sections.append(f'{heading}\n\n{raw}')

        sample_section = self._build_samples_markdown(samples)
        if sample_section:
            insert_at = 4 if len(sections) >= 4 else len(sections)
            sections.insert(insert_at, sample_section)

        translation_section = self._build_translation_markdown(translation)
        if translation_section:
            sections.append(translation_section)

        markdown = '\n\n'.join(section for section in sections if section.strip()).strip()
        return markdown or None

    def _build_samples_markdown(self, samples: Any) -> Optional[str]:
        """把 `problem.samples` 结构化为 Markdown 样例段。"""
        if not isinstance(samples, list) or not samples:
            return None

        blocks: List[str] = ['输入输出样例']
        for index, sample in enumerate(samples, start=1):
            sample_input = ''
            sample_output = ''

            if isinstance(sample, (list, tuple)):
                if len(sample) > 0:
                    sample_input = str(sample[0] or '')
                if len(sample) > 1:
                    sample_output = str(sample[1] or '')
            elif isinstance(sample, dict):
                sample_input = str(
                    sample.get('input')
                    or sample.get('in')
                    or sample.get('stdin')
                    or ''
                )
                sample_output = str(
                    sample.get('output')
                    or sample.get('out')
                    or sample.get('stdout')
                    or ''
                )

            blocks.append(f'输入 #{index}\n\n```plain\n{sample_input}\n```')
            blocks.append(f'输出 #{index}\n\n```plain\n{sample_output}\n```')

        return '\n\n'.join(blocks).strip()

    def _build_translation_markdown(self, translation: Any) -> Optional[str]:
        """兼容存在题面翻译时的 Markdown 输出。"""
        if not isinstance(translation, dict):
            return None

        text_candidates = []
        for key in ('background', 'description', 'content', 'text'):
            value = str(translation.get(key) or '').strip()
            if value:
                text_candidates.append(value)

        if not text_candidates:
            return None
        return '题面翻译\n\n' + '\n\n'.join(text_candidates)

    def _extract_markdown_from_hidden_original(self) -> Optional[str]:
        """从页面中隐藏的 `.lfe-marked-original` 代码块提取原始 Markdown。"""
        try:
            result = self.page.evaluate("""
                () => {
                    const container = document.querySelector('.l-card.problem');
                    if (!container) return [];

                    const sections = [];
                    let currentHeading = '';
                    for (const child of Array.from(container.children)) {
                        const tag = (child.tagName || '').toUpperCase();
                        if (tag === 'H2') {
                            currentHeading = (child.textContent || '').trim();
                            continue;
                        }

                        const original = child.querySelector('.lfe-marked-original');
                        if (original) {
                            sections.push({
                                heading: currentHeading,
                                text: (original.textContent || '').trim(),
                            });
                        }
                    }
                    return sections;
                }
            """)
        except Exception as e:
            logger.warning(f'[Luogu] 读取隐藏原文块失败: {e}')
            return None

        if not isinstance(result, list):
            return None

        parts = []
        for section in result:
            if not isinstance(section, dict):
                continue
            heading = str(section.get('heading') or '').strip()
            text = str(section.get('text') or '').strip()
            if not text:
                continue
            if heading:
                parts.append(f'{heading}\n\n{text}')
            else:
                parts.append(text)

        markdown = '\n\n'.join(parts).strip()
        return markdown or None

    def _try_click_copy_markdown_button(self) -> Optional[str]:
        """点击页面上的「复制 Markdown」按钮"""
        try:
            # 实际测试发现：
            # 1. 按钮是 <a> 标签，不是 <button>
            # 2. 文本是 "复制 Markdown"（有空格）
            # 3. 点击后无法直接读取剪贴板（浏览器权限限制）
            # 4. 需要从页面元素提取 Markdown 内容

            # 方法1: 用 JS 点击按钮，然后从页面提取 Markdown
            click_result = self.page.evaluate("""
                () => {
                    const btn = Array.from(document.querySelectorAll('a')).find(a => a.textContent.includes('复制 Markdown'));
                    if (btn) {
                        btn.click();
                        return 'clicked';
                    }
                    return 'not found';
                }
            """)
            if click_result != 'clicked':
                logger.info(f'[Luogu] 复制 Markdown 按钮未命中: {click_result}')
            if click_result == 'clicked':
                time.sleep(0.3)
                # 从页面元素提取 Markdown 内容
                md_content = self._extract_markdown_from_page()
                if md_content and len(md_content) > 20:
                    return md_content

            # 方法2: 尝试 Playwright locator 方式（备用）
            copy_selectors = [
                'a:has-text("复制Markdown")',
                'a:has-text("复制 Markdown")',
                'a:has-text("复制markdown")',
                'a[href*="javascript"]',
            ]

            for selector in copy_selectors:
                try:
                    btn = self.page.locator(selector).filter(has_text=re.compile(r'复制\s*Markdown?', re.I)).first
                    if btn.count() > 0:
                        btn.click()
                        time.sleep(0.3)
                        md_content = self._extract_markdown_from_page()
                        if md_content and len(md_content) > 20:
                            return md_content
                except Exception:
                    continue

            # 备选：直接提取页面 Markdown 内容
            return self._extract_markdown_from_page()
        except Exception as e:
            logger.warning(f'[Luogu] 复制按钮点击失败: {e}')
            return None

    def _extract_markdown_from_page(self) -> Optional[str]:
        """从页面元素提取类似 Markdown 的内容"""
        try:
            # 洛谷题目页面的内容可以通过 body 获取
            # 需要过滤掉页面头部、底部等非题目内容
            md_content = self.page.evaluate("""
                () => {
                    // 尝试找 Markdown 源内容区域
                    const mdEl = document.querySelector('.problem-markdown')
                        || document.querySelector('[class*="markdown"]')
                        || document.querySelector('.lg-markdown');
                    if (mdEl) return mdEl.innerText;

                    // 尝试找题目内容区域
                    const contentEl = document.querySelector('.problem-content')
                        || document.querySelector('.lg-content');
                    if (contentEl) return contentEl.innerText;

                    // 兜底：从 body 获取，然后过滤非题目内容
                    const bodyText = document.body.innerText;
                    // 找到"题目背景"或"题目描述"开始的位置
                    const startMarkers = ['题目背景', '题目描述', '输入格式', '输出格式', '输入输出样例', '说明/提示'];
                    let startIdx = -1;
                    for (const marker of startMarkers) {
                        const idx = bodyText.indexOf(marker);
                        if (idx !== -1 && (startIdx === -1 || idx < startIdx)) {
                            startIdx = idx;
                        }
                    }
                    if (startIdx !== -1) {
                        return bodyText.substring(startIdx);
                    }
                    return bodyText;
                }
            """)
            return md_content if md_content and len(md_content) > 20 else None
        except Exception:
            return None

    def _fetch_markdown_via_api(self, pid: str) -> str:
        """通过洛谷 API 获取 Markdown（需要登录态）"""
        if not pid:
            return '（未能确定题目编号）'

        # 通过 API 获取原始 Markdown
        api_url = f'https://www.luogu.com.cn/problem/{pid}?_contentOnly=1'
        logger.info(f'[Luogu] 通过 API 获取题目 Markdown: {api_url}')

        # 使用绝对 URL 并添加必要的请求头
        result = self.page.evaluate(f"""
            async () => {{
                try {{
                    const resp = await fetch('{api_url}', {{
                        headers: {{
                            'x-luogu-type': 'content-only',
                            'accept': 'application/json',
                            'referer': 'https://www.luogu.com.cn/problem/{pid}'
                        }},
                        credentials: 'include'
                    }});
                    const text = await resp.text();
                    // 检查是否返回了 HTML（未登录或被拦截）
                    if (!text.startsWith('{{')) {{
                        return {{
                            error: '非JSON响应，旧接口可能失效或返回 HTML',
                            status: resp.status,
                            contentType: resp.headers.get('content-type'),
                            raw: text.substring(0, 200)
                        }};
                    }}
                    return JSON.parse(text);
                }} catch(e) {{
                    return {{ error: e.toString() }};
                }}
            }}
        """)

        if isinstance(result, dict):
            if result.get('error'):
                logger.warning(
                    '[Luogu] API 请求失败，回退页面文本提取: '
                    f'error={result.get("error")}, '
                    f'status={result.get("status")}, '
                    f'contentType={result.get("contentType")}'
                )
                return self._extract_markdown_fallback()

            # 尝试从 JSON 中提取 Markdown
            current_data = result.get('currentData', {})
            problem_data = current_data.get('problem', {})

            content = problem_data.get('content', '')
            if content and len(content) > 50:
                logger.info(f'[Luogu] 成功获取题目 Markdown，长度: {len(content)}')
                return content

            for field in ['description', 'body', 'statement']:
                val = problem_data.get(field, '')
                if val and len(val) > 50:
                    logger.info(f'[Luogu] 通过字段 {field} 获取内容，长度: {len(val)}')
                    return val

            # 全量 dump 查找内容
            logger.warning(f'[Luogu] API 返回结构异常，尝试全量提取')
            raw_str = json.dumps(result, ensure_ascii=False)
            if 'inputFormat' in raw_str or '输入格式' in raw_str or '输入描述' in raw_str:
                def _find_md(obj, depth=0):
                    if depth > 10:
                        return ''
                    if isinstance(obj, str) and len(obj) > 100 and ('##' in obj or '\n\n' in obj or '输入' in obj):
                        return obj
                    if isinstance(obj, dict):
                        for v in obj.values():
                            r = _find_md(v, depth + 1)
                            if r:
                                return r
                    if isinstance(obj, list):
                        for item in obj:
                            r = _find_md(item, depth + 1)
                            if r:
                                return r
                    return ''
                found = _find_md(result)
                if found:
                    return found

        return self._extract_markdown_fallback()

    def _extract_markdown_fallback(self) -> str:
        """兜底：从当前页面提取题目内容"""
        try:
            md_content = self.page.evaluate("""
                () => {
                    const bodyText = document.body.innerText;
                    // 找到题目内容开始的位置
                    const startMarkers = ['题目背景', '题目描述', '输入格式', '输出格式', '输入输出样例', '说明/提示'];
                    let startIdx = -1;
                    for (const marker of startMarkers) {
                        const idx = bodyText.indexOf(marker);
                        if (idx !== -1 && (startIdx === -1 || idx < startIdx)) {
                            startIdx = idx;
                        }
                    }
                    if (startIdx !== -1) {
                        return bodyText.substring(startIdx);
                    }
                    return bodyText;
                }
            """)
            if md_content and len(md_content) > 20:
                return md_content
            return '（未能获取题目内容）'
        except Exception as e:
            return f'（内容提取失败: {e}）'


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
