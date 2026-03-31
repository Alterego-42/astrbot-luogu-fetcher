"""
洛谷助手 AstrBot 插件

指令列表：
  /luogu bind <手机号> <密码> [-s]   绑定洛谷账号（通过 Playwright 登录并保存 cookie，-s 保存账号密码）
  /luogu info [uid]             查看个人主页统计（统计卡片图片）
  /luogu checkin                每日打卡
  /luogu heatmap                做题热度日历图（近26周）
  /luogu elo                    比赛等级分趋势图
  /luogu practice               查看练习情况（按难度分类通过题数）
  /luogu jump                   题库跳转（多轮对话，支持筛选+随机/指定题目+题面截图）
  /luogu help                   显示帮助

支持平台：aiocqhttp、qq_official
"""

from __future__ import annotations

import os
import sys
import re
import json
import time
import asyncio
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

# ── 路径处理 ──────────────────────────────────────────────────
_PLUGIN_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(_PLUGIN_DIR))

# ── AstrBot 导入（可选，独立运行时不可用） ──────────────────────
try:
    from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
    from astrbot.api.star import Context, Star, register
    from astrbot.api import logger
    from astrbot.api.message_components import Face, Plain, Node, Nodes, Image
    from astrbot.core.agent.tool import ToolSet
    from astrbot.core.utils.session_waiter import session_waiter, SessionController
    from astrbot.core.agent.message import TextPart
    _ASTRBOT = True
except ImportError:
    _ASTRBOT = False
    import logging
    logger = logging.getLogger('luogu_plugin')
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s [%(levelname)s] %(message)s')

# ── 插件内部模块 ──────────────────────────────────────────────
from luogu.data_fetcher import LuoguDataFetcher
from luogu.problem_fetcher import ProblemFetcher
from luogu.problem_lookup import (
    extract_problem_id,
    format_luogu_problem_tool_result,
    lookup_luogu_problem_by_pid,
    lookup_luogu_problems,
    run_problem_async,
)
from luogu.request_count import clamp_luogu_request_count
from luogu.llm_routing_policy import (
    enforce_luogu_request,
    plan_luogu_llm_request,
)
from luogu.llm_search_workflow import (
    execute_luogu_lookup_turn,
    format_luogu_session_snapshot,
)
from luogu.tool_entry import (
    normalize_luogu_image_mode,
    prepare_luogu_problem_display_target,
    resolve_luogu_bound_cookie_file,
)
from luogu.session_events import (
    EVENT_IMAGE_SENT,
    EVENT_STATEMENT_SENT,
    append_session_event,
)
from luogu.intent_classifier import classify_luogu_routing_intent
from luogu.tags import HOT_TAGS
from luogu.chart_generator import (
    generate_summary_card,
    generate_heatmap,
    generate_elo_trend,
    generate_bar_chart,
    generate_difficulty_cards,
)
from luogu.jump_session import (
    apply_jump_difficulty_input,
    apply_jump_keyword_input,
    apply_jump_search_intent_filters,
    apply_jump_tag_update,
    build_jump_problem_fallback_messages,
    build_jump_problem_forward_nodes,
    choose_jump_random_positions,
    JUMP_HELP_TEXT,
    format_jump_batch_preview,
    is_jump_back_to_difficulty_command,
    is_jump_back_to_keyword_command,
    is_jump_done_command,
    is_jump_help_command,
    is_jump_quit_command,
    is_jump_random_command,
    is_jump_show_image_command,
    is_jump_show_screenshot_command,
    is_jump_skip_command,
    is_jump_status_command,
    looks_like_jump_commandish_input,
    normalize_jump_tag_list_with_meta,
    render_jump_step,
    render_no_result_prompt,
    render_selected_tags_update,
    render_problem_header,
    render_problem_footer,
    resolve_jump_selection_target,
    suggest_jump_step_command,
)
from luogu.jump_runtime import (
    build_jump_initial_state,
    clear_jump_selection_state,
    ensure_jump_cookie_ready,
    move_jump_to_difficulty_step,
    move_jump_to_keyword_step,
    remember_jump_filter_result,
    remember_jump_problem_artifact,
)
from luogu.jump_batch import load_jump_problem_batch, refresh_jump_batch_summaries
from luogu.jump_playwright import (
    apply_jump_filters_via_fetcher,
    ensure_jump_fetcher,
    load_jump_problem_detail,
    screenshot_jump_problem,
)
from luogu.nl_jump import parse_jump_natural_language

# ── 常量 ──────────────────────────────────────────────────────
COOKIES_DIR    = _PLUGIN_DIR / 'cookies'
DATA_DIR       = _PLUGIN_DIR / 'user_data'
CREDENTIALS_DIR = _PLUGIN_DIR / 'credentials'  # 账号密码（可选保存）
BIND_FILE      = DATA_DIR / 'bindings.json'    # qq_id -> luogu_uid
COOKIES_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)
CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)


# ════════════════════════════════════════════════════════════════
# 工具函数
# ════════════════════════════════════════════════════════════════

def _load_bindings() -> Dict[str, str]:
    """加载 QQ -> luogu_uid 绑定表"""
    if BIND_FILE.exists():
        try:
            return json.loads(BIND_FILE.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {}


def _save_bindings(bindings: Dict[str, str]):
    BIND_FILE.write_text(json.dumps(bindings, ensure_ascii=False, indent=2),
                         encoding='utf-8')


def _cookies_path(qq_id: str) -> Path:
    return COOKIES_DIR / f'cookies_{qq_id}.json'


def _uid_file(qq_id: str) -> Path:
    return COOKIES_DIR / f'cookies_{qq_id}_uid.txt'


def _userdata_path(qq_id: str) -> Path:
    return DATA_DIR / f'userdata_{qq_id}.json'


def _credentials_path(qq_id: str) -> Path:
    """账号密码存储路径（加密）"""
    return CREDENTIALS_DIR / f'cred_{qq_id}.bin'


def _save_credentials(qq_id: str, username: str, password: str) -> bool:
    """
    保存账号密码（Base64 编码）
    返回是否保存成功
    """
    import base64
    try:
        cred = f'{username}:{password}'
        encoded = base64.b64encode(cred.encode('utf-8')).decode('ascii')
        _credentials_path(qq_id).write_text(encoded, encoding='utf-8')
        logger.info(f'[Luogu] 用户 {qq_id} 的账号密码已保存到本地')
        return True
    except Exception as e:
        logger.warning(f'[Luogu] 保存账号密码失败: {e}')
        return False


def _load_credentials(qq_id: str) -> Optional[Tuple[str, str]]:
    """加载账号密码，返回 (username, password) 或 None"""
    import base64
    cred_file = _credentials_path(qq_id)
    if not cred_file.exists():
        return None
    try:
        encoded = cred_file.read_text(encoding='utf-8')
        cred = base64.b64decode(encoded.encode('ascii')).decode('utf-8')
        username, password = cred.split(':', 1)
        return (username, password)
    except Exception as e:
        logger.warning(f'[Luogu] 加载账号密码失败: {e}')
        return None


def _delete_credentials(qq_id: str) -> bool:
    """删除保存的账号密码"""
    try:
        cred_file = _credentials_path(qq_id)
        if cred_file.exists():
            cred_file.unlink()
        return True
    except Exception as e:
        logger.warning(f'[Luogu] 删除账号密码失败: {e}')
        return False


def _has_credentials(qq_id: str) -> bool:
    """检查是否保存了账号密码"""
    return _credentials_path(qq_id).exists()


def _get_uid_for_qq(qq_id: str) -> Optional[str]:
    """从绑定表 / uid 缓存文件获取 uid"""
    bindings = _load_bindings()
    if qq_id in bindings:
        return bindings[qq_id]
    # 兜底：uid 缓存文件
    uid_f = _uid_file(qq_id)
    if uid_f.exists():
        return uid_f.read_text().strip() or None
    return None


import tempfile
import uuid

def _ensure_image_path(img_data: Any) -> Optional[str]:
    """
    确保图片数据可以被 image_result 使用。
    如果是 bytes，保存为临时文件返回路径。
    如果是 str，直接返回。
    返回 None 如果数据无效。
    """
    if img_data is None:
        return None
    
    # 如果是 bytes，保存为临时文件
    if isinstance(img_data, bytes):
        try:
            # 创建临时文件
            temp_dir = tempfile.gettempdir()
            filename = f'luogu_temp_{uuid.uuid4().hex[:8]}.png'
            temp_path = os.path.join(temp_dir, filename)
            with open(temp_path, 'wb') as f:
                f.write(img_data)
            return temp_path
        except Exception as e:
            logger.warning(f'[Luogu] 保存临时图片失败: {e}')
            return None
    
    # 如果是 str（文件路径或 URL），直接返回
    if isinstance(img_data, str):
        return img_data
    
    return None


def _run_sync(cookies_file: str, qq_id: str, task_fn, **kwargs) -> Any:
    """
    在同步线程中运行 LuoguDataFetcher 任务。
    task_fn 接受 (fetcher, **kwargs) 并返回结果。
    """
    uid = _get_uid_for_qq(qq_id)
    with LuoguDataFetcher(cookies_file, user_id=uid) as fetcher:
        return task_fn(fetcher, **kwargs)


async def _run_async(cookies_file: str, qq_id: str, task_fn, **kwargs) -> Any:
    """异步包装：在线程池中运行同步任务"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: _run_sync(cookies_file, qq_id, task_fn, **kwargs)
    )


def _check_cookie_valid(cookies_file: str) -> bool:
    """
    检测 cookie 是否有效（使用 Playwright 模拟浏览器访问）。
    返回 True 表示有效，False 表示已过期。
    """
    from playwright.sync_api import sync_playwright

    if not Path(cookies_file).exists():
        return False

    try:
        with open(cookies_file, 'r', encoding='utf-8') as f:
            cookie_data = json.load(f)

        cookies = cookie_data.get('cookies', [])
        if not cookies:
            return False

        # 使用 Playwright 检测登录状态
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context()
            context.add_cookies(cookies)
            page = context.new_page()

            try:
                page.goto('https://www.luogu.com.cn/', timeout=15000, wait_until='networkidle')
                time.sleep(1)

                # 检查页面是否包含用户信息（登录状态）
                content = page.content()
                if '__NEXT_DATA__' in content or 'window.__INITIAL_STATE__' in content:
                    logger.info('[Luogu] Cookie 检测成功（Playwright）')
                    return True

                # 备用：检查页面是否有登录后的元素
                if page.is_visible('.user-nav'):
                    logger.info('[Luogu] Cookie 检测成功（发现 .user-nav）')
                    return True

                logger.warning('[Luogu] Cookie 检测失败：未检测到登录状态')
                return False
            finally:
                page.close()
                context.close()
                browser.close()
    except Exception as e:
        logger.warning(f'[Luogu] Cookie 检测异常: {e}')
        return False
    except Exception as e:
        logger.warning(f'[Luogu] Cookie 检测失败: {e}')
        return False


# ════════════════════════════════════════════════════════════════
# 各功能的实际执行函数（同步，在线程中运行）
# ════════════════════════════════════════════════════════════════

def _task_checkin(fetcher: LuoguDataFetcher) -> Dict:
    return fetcher.checkin()


def _task_profile(fetcher: LuoguDataFetcher) -> Dict:
    return fetcher.fetch_profile_stats()


def _task_practice(fetcher: LuoguDataFetcher) -> Dict:
    return fetcher.fetch_practice_data()


def _task_all(fetcher: LuoguDataFetcher) -> Dict:
    return fetcher.fetch_all()


# ── 截图任务 ──────────────────────────────────────────────────

def _task_screenshot_checkin(fetcher: LuoguDataFetcher) -> Optional[bytes]:
    return fetcher.screenshot_checkin()


def _task_screenshot_heatmap(fetcher: LuoguDataFetcher) -> Optional[bytes]:
    return fetcher.screenshot_heatmap()


def _task_screenshot_rating(fetcher: LuoguDataFetcher) -> Optional[bytes]:
    return fetcher.screenshot_rating_trend()


def _task_screenshot_profile(fetcher: LuoguDataFetcher) -> Optional[bytes]:
    return fetcher.screenshot_profile_summary()


def _task_screenshot_practice(fetcher: LuoguDataFetcher) -> Optional[bytes]:
    return fetcher.screenshot_practice_difficulty()


# ════════════════════════════════════════════════════════════════
# 登录（同步 Playwright，需在线程中运行）
# ════════════════════════════════════════════════════════════════

def _do_login(username: str, password: str, qq_id: str, save_credentials: bool = False) -> Dict:
    """
    通过 Playwright 登录洛谷，保存 cookies 到文件。
    参数:
        username: 洛谷手机号
        password: 洛谷密码
        qq_id: QQ 号
        save_credentials: 是否保存账号密码到本地（可选，后续可自动登录）
    返回 {'success': bool, 'message': str, 'uid': str|None, 'credentials_saved': bool}
    """
    from playwright.sync_api import sync_playwright
    import json as _json

    cookies_file = str(_cookies_path(qq_id))

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/120.0.0.0 Safari/537.36'
                )
            )
            page = context.new_page()

            # 1. 访问登录页
            page.goto('https://www.luogu.com.cn/auth/login', timeout=20000)
            page.wait_for_load_state('networkidle')
            time.sleep(1)

            # 2. 输入用户名
            page.fill('input[type="text"]', username)
            page.click('button:has-text("下一步")')
            time.sleep(1.5)

            # 3. 输入密码
            page.fill('input[type="password"]', password)
            time.sleep(0.5)

            # 4. 处理验证码（最多5次 OCR 重试）
            captcha_solved = False

            def _close_swal_popup():
                """关闭 sweetalert2 弹窗，使用 JS 兜底，避免元素不可见时卡住"""
                try:
                    # 优先用 JS 点击，无需元素可见
                    page.evaluate("""
                        (() => {
                            const btn = document.querySelector('.swal2-confirm') ||
                                        document.querySelector('.swal2-close');
                            if (btn) btn.click();
                        })()
                    """)
                    time.sleep(0.4)
                except Exception:
                    pass

            def _click_captcha_refresh():
                """点击验证码图片以刷新"""
                try:
                    captcha_img = (
                        page.query_selector('img[src*="captcha"]') or
                        page.query_selector('.captcha-img img') or
                        page.query_selector('img[alt*="验证码"]')
                    )
                    if captcha_img:
                        captcha_img.click()
                        time.sleep(0.6)
                except Exception:
                    pass

            for attempt in range(5):
                logger.info(f'[Luogu] 验证码登录第 {attempt + 1} 次尝试')

                # 关闭可能存在的弹窗
                _close_swal_popup()

                # 每次循环都重新填写密码（验证码错误后密码框可能被清空）
                try:
                    pwd_input = page.query_selector('input[type="password"]')
                    if pwd_input:
                        pwd_input.fill(password)
                except Exception:
                    pass

                # 获取验证码图片并 OCR
                captcha_img = (
                    page.query_selector('img[src*="captcha"]') or
                    page.query_selector('.captcha-img img') or
                    page.query_selector('img[alt*="验证码"]')
                )

                if captcha_img:
                    try:
                        import ddddocr
                        ocr = ddddocr.DdddOcr(show_ad=False)
                        cap_bytes = captcha_img.screenshot()
                        code = ocr.classification(cap_bytes)
                        logger.info(f'[Luogu] 验证码OCR结果: {code}')

                        cap_input = (
                            page.query_selector('input[placeholder*="验证码"]') or
                            page.query_selector('input[type="text"]:not([placeholder*="用户"])')
                        )
                        if cap_input:
                            cap_input.fill('')   # 先清空
                            cap_input.fill(code)
                    except ImportError:
                        logger.warning('[Luogu] ddddocr 未安装，跳过验证码自动识别')
                    except Exception as e:
                        logger.warning(f'[Luogu] 验证码识别失败: {e}')

                # 点击登录按钮
                login_btn = (
                    page.query_selector('button:has-text("登录")') or
                    page.query_selector('button[type="submit"]')
                )
                if login_btn:
                    login_btn.click()

                time.sleep(2.5)

                # 检查是否成功（跳出登录页）
                if '/auth/login' not in page.url:
                    captcha_solved = True
                    break

                # 检查错误提示
                error_visible = (
                    page.is_visible('text=验证码错误') or
                    page.is_visible('text=密码错误') or
                    page.is_visible('text=账号或密码')
                )
                if error_visible:
                    # 密码错误则直接失败
                    if page.is_visible('text=密码错误') or page.is_visible('text=账号或密码'):
                        browser.close()
                        return {'success': False, 'message': '账号或密码错误', 'uid': None}
                    # 验证码错误：关闭弹窗，刷新验证码，继续重试
                    logger.info(f'[Luogu] 第 {attempt + 1} 次验证码识别错误，关闭弹窗并刷新验证码...')
                    _close_swal_popup()
                    _click_captcha_refresh()

            if not captcha_solved:
                browser.close()
                return {'success': False, 'message': '登录失败（验证码多次识别错误）', 'uid': None}

            # 登录成功，保存 cookies
            cookies = context.cookies()
            uid = None
            for c in cookies:
                if c.get('name') in ('__uid', '_uid'):
                    uid = str(c['value'])
                    break

            # 保存 Playwright 格式的 cookies
            cookie_data = {'cookies': cookies}
            Path(cookies_file).write_text(
                _json.dumps(cookie_data, ensure_ascii=False, indent=2),
                encoding='utf-8'
            )

            # 可选：保存账号密码
            credentials_saved = False
            if save_credentials:
                credentials_saved = _save_credentials(qq_id, username, password)

            # 更新绑定表
            if uid:
                bindings = _load_bindings()
                bindings[qq_id] = uid
                _save_bindings(bindings)
                _uid_file(qq_id).write_text(uid)

            # 登录成功后，自动获取并保存所有信息
            logger.info(f'[Luogu] 登录成功，开始获取用户数据...')
            try:
                # 使用新登录的 context 创建 fetcher 获取数据
                from luogu.data_fetcher import LuoguDataFetcher
                
                # 创建临时 fetcher（复用同一个 context）
                temp_fetcher = LuoguDataFetcher(cookies_file, user_id=uid, headless=True)
                temp_fetcher._playwright = pw
                temp_fetcher.browser = browser
                temp_fetcher.context = context
                temp_fetcher.page = page
                
                # 获取所有数据
                logger.info(f'[Luogu] 正在获取个人主页数据...')
                profile = temp_fetcher.fetch_profile_stats()
                logger.info(f'[Luogu] 个人主页数据获取完成: {profile.get("name", "未知用户")}')
                
                logger.info(f'[Luogu] 正在获取练习数据...')
                practice = temp_fetcher.fetch_practice_data()
                logger.info(f'[Luogu] 练习数据获取完成: 已通过{practice.get("total_passed", 0)}题')
                
                # 保存到用户数据文件
                user_data_file = DATA_DIR / f'userdata_{qq_id}.json'
                user_data = {
                    'uid': uid,
                    'profile': profile,
                    'practice': practice,
                    'last_updated': time.strftime('%Y-%m-%d %H:%M:%S'),
                }
                user_data_file.write_text(
                    json.dumps(user_data, ensure_ascii=False, indent=2),
                    encoding='utf-8'
                )
                logger.info(f'[Luogu] ✅ 用户数据已保存到 {user_data_file}')
                
                # 返回 OK emoji 标记获取成功
                return {'success': True, 'message': '登录成功', 'uid': uid, 'data_saved': True, 'credentials_saved': credentials_saved}
            except Exception as e:
                logger.warning(f'[Luogu] 自动获取用户数据失败: {e}')
                return {'success': True, 'message': '登录成功(部分数据获取失败)', 'uid': uid, 'data_saved': False, 'credentials_saved': credentials_saved}

            # 不关闭浏览器，让 fetcher 继续使用
            # browser.close()
            return {'success': True, 'message': '登录成功', 'uid': uid}

    except Exception as e:
        logger.error(f'[Luogu] 登录异常: {traceback.format_exc()}')
        return {'success': False, 'message': f'登录异常: {e}', 'uid': None}


# ════════════════════════════════════════════════════════════════
# 格式化回复函数
# ════════════════════════════════════════════════════════════════

DIFFICULTY_ORDER = [
    '暂无评定', '入门', '普及−', '普及/提高−', '普及+/提高',
    '提高+/省选−', '省选/NOI−', 'NOI/NOI+/CTSC'
]


def _fmt_practice(data: Dict) -> str:
    lines = [
        f"📚 练习情况",
        f"  已通过：{data.get('total_passed', 0)} 题",
        f"  未通过：{data.get('total_unpassed', 0)} 题",
        "",
        "按难度分布（已通过）："
    ]
    by_diff = data.get('passed_by_difficulty', {})
    for diff in DIFFICULTY_ORDER:
        pids = by_diff.get(diff, [])
        if pids:
            # 只显示前10题，过多则截断
            pids_str = ' '.join(pids[:10])
            if len(pids) > 10:
                pids_str += f' ...共{len(pids)}题'
            lines.append(f"  {diff}：{pids_str}")
    return '\n'.join(lines)


def _fmt_profile(profile: Dict) -> str:
    """格式化个人主页信息为文字版"""
    lines = [
        f"👤 {profile.get('name', profile.get('uid', '未知用户'))}",
        f"   UID: {profile.get('uid', 'N/A')}",
        f"",
        f"📊 做题统计",
        f"   通过：{profile.get('passed', 0)} 题",
        f"   提交：{profile.get('submitted', 0)} 次",
        f"",
        f"🏆 等级分",
        f"   当前等级分：{profile.get('rating', 0)}",
        f"   评定比赛：{profile.get('contests', 0)} 场",
        f"   排名：#{profile.get('rank', 'N/A')}",
        f"",
        f"💎 咕值构成",
    ]
    
    # 咕值构成详情
    guzhi = profile.get('guzhi_detail', {})
    if guzhi and guzhi.get('total', 0) > 0:
        lines.append(f"   总咕值：{guzhi.get('total', 0)}")
        # 显示各构成部分
        scores = guzhi.get('scores', {})
        if scores:
            score_items = []
            if scores.get('basic'):
                score_items.append(f"基础信用 {scores.get('basic')}")
            if scores.get('practice'):
                score_items.append(f"练习情况 {scores.get('practice')}")
            if scores.get('contest'):
                score_items.append(f"比赛情况 {scores.get('contest')}")
            if scores.get('social'):
                score_items.append(f"社区贡献 {scores.get('social')}")
            if scores.get('prize'):
                score_items.append(f"获得成就 {scores.get('prize')}")
            if score_items:
                lines.append("   " + " | ".join(score_items))
    else:
        lines.append(f"   总咕值：{profile.get('csr', 0)}")
    
    # 评定比赛列表
    contest_names = profile.get('contest_names', [])
    if contest_names:
        lines.append(f"")
        lines.append(f"📋 评定比赛")
        for name in contest_names[:10]:  # 最多显示10场
            lines.append(f"   • {name}")
        if len(contest_names) > 10:
            lines.append(f"   ... 等共 {len(contest_names)} 场")
    
    return '\n'.join(lines)


def _fmt_checkin(result: Dict) -> str:
    if result.get('success'):
        if result.get('already_checked'):
            msg = f"✅ 今日已打卡"
        else:
            msg = f"🎉 打卡成功！"
        streak = result.get('streak', 0)
        fortune = result.get('fortune', '')
        if streak:
            msg += f"\n连续打卡 {streak} 天"
        if fortune:
            msg += f"\n今日运势：{fortune}"
    else:
        msg = f"❌ 打卡失败：{result.get('message', '未知错误')}"
    return msg


# ════════════════════════════════════════════════════════════════
# /jump 题库跳转：5步状态机会话
# ════════════════════════════════════════════════════════════════

async def _jump_session_flow(
    context: Optional[Context],
    event: AstrMessageEvent,
    cookies_file: str,
    *,
    requested_count: int = 1,
):
    """
    多轮题库跳转（5步状态机）。

    状态流转：
      difficulty → tags → keyword → result → [选题] → result

    关键设计：
    - 单一 ProblemFetcher 实例贯穿整个会话
    - 专用单线程 ThreadPoolExecutor：所有 Playwright Sync API 调用
      必须在同一线程中执行，asyncio.to_thread() 每次分配不同线程
      会导致 "Cannot switch to a different thread" 的 greenlet 报错。
      解决方案：创建 max_workers=1 的专用 executor，所有 Playwright
      操作通过 loop.run_in_executor(executor, fn) 提交到固定线程。
    """
    import astrbot.api.message_components as Comp
    _cookies = cookies_file
    qq_id = str(event.get_sender_id())

    cookie_ready = await ensure_jump_cookie_ready(
        cookies_file=cookies_file,
        qq_id=qq_id,
        send_text=lambda text: event.send(event.plain_result(text)),
        check_cookie_valid=_check_cookie_valid,
        load_credentials=_load_credentials,
        do_login=_do_login,
    )
    if not cookie_ready:
        return

    # --- 专用单线程 executor（所有 Playwright 操作必须在同一线程） ---
    _pw_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='pw_jump')

    async def _run_in_pw(fn):
        """在专用 Playwright 线程中执行同步函数。"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_pw_executor, fn)

    # --- 状态初始化 ---
    state = build_jump_initial_state(
        requested_count,
        clamp_count=clamp_luogu_request_count,
    )
    step = ['difficulty']

    # --- 单一 ProblemFetcher 实例（贯穿整个会话） ---
    fetcher: ProblemFetcher = None

    async def _send_text(text: str):
        mr = event.make_result()
        mr.chain = [Comp.Plain(text)]
        await event.send(mr)

    async def _send_img(img_path: str):
        mr = event.make_result()
        mr.chain = [Comp.Image(file=img_path)]
        await event.send(mr)

    async def _show_current_step():
        s = step[0]
        if s == 'result' and state.get('batch_summaries'):
            await _send_text(format_jump_batch_preview(state['batch_summaries']))
            return
        await _send_text(render_jump_step(s, state))

    async def _parse_natural_language_intent(text: str) -> Optional[Dict[str, Any]]:
        if not context or not text.strip():
            return None
        if looks_like_jump_commandish_input(text):
            return None
        intent = await parse_jump_natural_language(context, event, text, HOT_TAGS)
        if intent:
            logger.info(f'[Luogu jump] 自然语言意图: {intent}')
        return intent

    async def _handle_jump_intent_control_action(
        controller: SessionController,
        action: str,
    ) -> bool:
        if action == 'help':
            await _send_text(JUMP_HELP_TEXT)
            controller.keep(timeout=180, reset_timeout=True)
            return True

        if action == 'quit':
            await _send_text('✅ 已退出题库跳转，下次见！')
            controller.stop()
            return True

        if action == 'restart':
            move_jump_to_difficulty_step(state)
            step[0] = 'difficulty'
            await _send_text('← 已重置筛选条件，我们从头开始。')
            await _send_text(render_jump_step('difficulty', state))
            controller.keep(timeout=180, reset_timeout=True)
            return True

        if action == 'back':
            if step[0] in ('result', 'waiting_md', 'keyword'):
                move_jump_to_keyword_step(state)
                step[0] = 'keyword'
                await _send_text('← 返回关键词筛选步骤（保留难度和标签）')
                await _show_current_step()
            else:
                move_jump_to_difficulty_step(state)
                step[0] = 'difficulty'
                await _send_text('← 返回难度筛选步骤')
                await _send_text(render_jump_step('difficulty', state))
            controller.keep(timeout=180, reset_timeout=True)
            return True

        return False

    async def _handle_jump_intent_display_action(
        controller: SessionController,
        action: str,
    ) -> bool:
        if action not in ('show_image', 'show_screenshot'):
            return False
        if step[0] not in ('waiting_md', 'result') or not state.get('current_pid'):
            await _send_text('先选出一道题，我再帮你渲染题面图片。')
            controller.keep(timeout=180, reset_timeout=True)
            return True
        if action == 'show_screenshot':
            await _send_text('📸 正在截取洛谷网页截图，请稍候...')
            await _render_and_send_problem_image(mode='screenshot')
        else:
            await _send_text('🖼️ 正在渲染题面图片，请稍候...')
            await _render_and_send_problem_image(mode='rendered')
        step[0] = 'waiting_md'
        controller.keep(timeout=180, reset_timeout=True)
        return True

    async def _handle_jump_intent_lookup_action(
        controller: SessionController,
        intent: Mapping[str, Any],
        action: str,
    ) -> bool:
        intent_has_filters = (
            intent.get('difficulty') is not None
            or bool(intent.get('tags'))
            or bool(intent.get('keyword'))
        )

        if action not in ('search', 'random', 'select'):
            return False

        if action in ('random', 'select') and state.get('total') and not intent_has_filters:
            if action == 'random':
                await _show_random_problem()
            else:
                await _show_selected_problem(int(intent.get('index') or 0))
            controller.keep(timeout=180, reset_timeout=True)
            return True

        if intent_has_filters:
            unresolved_notice = apply_jump_search_intent_filters(
                state,
                difficulty=intent.get('difficulty'),
                tags=list(intent.get('tags') or []),
                keyword=intent.get('keyword'),
                normalize_tags=normalize_jump_tag_list_with_meta,
            )
            if unresolved_notice:
                await _send_text(unresolved_notice)

        ok = await _apply_filters_and_present_results(
            loading_text='🔍 正在按你的描述筛题，请稍候...',
            action=action,
            select_index=int(intent.get('index') or 0),
        )
        if not ok:
            controller.keep(timeout=180, reset_timeout=True)
            return True

        controller.keep(timeout=180, reset_timeout=True)
        return True

    async def _handle_natural_language_intent(
        controller: SessionController,
        intent: Optional[Dict[str, Any]],
    ) -> bool:
        if not intent:
            return False

        action = intent.get('action')
        if intent.get('count') is not None:
            state['requested_count'] = clamp_luogu_request_count(intent.get('count'))
        if intent.get('need_clarification'):
            await _send_text(intent.get('clarification') or '我还差一点条件才能开始筛题。')
            controller.keep(timeout=180, reset_timeout=True)
            return True

        reply = intent.get('reply')
        if reply:
            await _send_text(reply)

        if await _handle_jump_intent_control_action(controller, action):
            return True

        if await _handle_jump_intent_display_action(controller, action):
            return True

        if await _handle_jump_intent_lookup_action(controller, intent, action):
            return True

        return False

    async def _apply_filters() -> bool:
        nonlocal fetcher
        try:
            fetcher, r = await apply_jump_filters_via_fetcher(
                fetcher=fetcher,
                state=state,
                cookies_file=_cookies,
                run_in_pw=_run_in_pw,
            )
            if not r.get('success'):
                await _send_text(f'❌ 筛选失败：{r.get("message", "未知错误")}')
                return False
            missing_tags = r.get('missing_tags') or []
            applied_tags = r.get('applied_tags')
            if applied_tags is not None:
                state['tags'] = applied_tags
            if missing_tags:
                await _send_text(
                    '⚠️ 以下标签未找到，已自动忽略：'
                    + '、'.join(missing_tags)
                )
            remember_jump_filter_result(state, r)
            logger.info(f'[Luogu jump] 筛选完成: total={state["total"]}, page_size={state["page_size"]}, list_url={state["list_url"]}')
            return True
        except Exception as e:
            logger.error(f'[Luogu jump] 筛选异常: {traceback.format_exc()}')
            await _send_text(f'❌ 筛选出错：{e}')
            return False

    async def _refresh_batch_summaries(batch_count: int) -> list[Dict[str, Any]]:
        nonlocal fetcher
        try:
            fetcher, summaries = await refresh_jump_batch_summaries(
                state=state,
                fetcher=fetcher,
                cookies_file=_cookies,
                run_in_pw=_run_in_pw,
                batch_count=batch_count,
            )
            state['batch_summaries'] = summaries
            return state['batch_summaries']
        except Exception as e:
            logger.error(f'[Luogu jump] 批量候选提取异常: {traceback.format_exc()}')
            await _send_text(f'❌ 批量读取候选题目出错：{e}')
            state['batch_summaries'] = []
            return []

    async def _show_problem_batch(positions: list[int]):
        nonlocal fetcher
        try:
            if not positions:
                await _send_text('❌ 没有可展示的题目。')
                return
            fetcher, items = await load_jump_problem_batch(
                state=state,
                fetcher=fetcher,
                cookies_file=_cookies,
                run_in_pw=_run_in_pw,
                positions=positions,
            )
            state['batch_summaries'] = items
            clear_jump_selection_state(state)
            state['batch_summaries'] = items
            step[0] = 'result'
            await _show_current_step()
        except Exception as e:
            logger.error(f'[Luogu jump] 批量选题异常: {traceback.format_exc()}')
            await _send_text(f'❌ 批量选题出错：{e}')

    async def _show_random_problem():
        positions = choose_jump_random_positions(
            state.get('total') or 0,
            int(state.get('requested_count') or 1),
        )
        if not positions:
            await _send_text('❌ 当前没有可选题目。')
            return
        if len(positions) > 1:
            await _send_text(f'🎲 随机挑出 {len(positions)} 道题。')
            await _show_problem_batch(positions)
            return
        pos = positions[0]
        await _send_text(f'🎲 随机选题（第 {pos} / {state["total"]}）')
        await _show_problem(pos)

    async def _apply_filters_and_present_results(
        *,
        loading_text: str,
        action: str = 'search',
        select_index: Optional[int] = None,
    ) -> bool:
        await _send_text(loading_text)
        ok = await _apply_filters()
        if not ok:
            return False

        step[0] = 'result'
        if state['total'] == 0:
            await _send_text(render_no_result_prompt(state))
            return True

        if action == 'random':
            await _show_random_problem()
            return True

        if action == 'select':
            await _show_selected_problem(
                int(select_index or 0),
                show_current_step_on_error=True,
            )
            return True

        requested_count = int(state.get('requested_count') or 1)
        if requested_count > 1:
            await _refresh_batch_summaries(requested_count)
        await _show_current_step()
        return True

    async def _show_selected_problem(index: int, *, show_current_step_on_error: bool = False) -> None:
        target_pid, target_position, selection_error = resolve_jump_selection_target(
            state.get('batch_summaries') or [],
            int(index or 0),
            int(state.get('total') or 0),
        )
        if target_pid:
            await _show_problem(pid=target_pid)
            return
        if target_position:
            await _show_problem(target_position)
            return
        await _send_text(selection_error or '⚠️ 暂时无法打开这道题。')
        if show_current_step_on_error:
            await _show_current_step()

    async def _handle_result_step_input(
        controller: SessionController,
        text: str,
        lower: str,
    ) -> bool:
        if state['total'] == 0:
            if is_jump_back_to_difficulty_command(lower):
                move_jump_to_difficulty_step(state)
                step[0] = 'difficulty'
                await _send_text('← 重置所有条件，返回难度筛选步骤')
                await _send_text(render_jump_step('difficulty', state))
                controller.keep(timeout=180, reset_timeout=True)
                return True
            await _send_text('输入 back-diff 重新开始，quit 退出')
            controller.keep(timeout=180, reset_timeout=True)
            return True

        if is_jump_random_command(lower):
            await _show_random_problem()
            controller.keep(timeout=180, reset_timeout=True)
            return True

        if is_jump_back_to_difficulty_command(lower):
            move_jump_to_difficulty_step(state)
            step[0] = 'difficulty'
            await _send_text('← 重置所有条件，返回难度筛选步骤')
            await _send_text(render_jump_step('difficulty', state))
            controller.keep(timeout=180, reset_timeout=True)
            return True

        if is_jump_back_to_keyword_command(lower):
            move_jump_to_keyword_step(state)
            step[0] = 'keyword'
            await _send_text('← 返回关键词筛选步骤（保留难度和标签）')
            await _show_current_step()
            controller.keep(timeout=180, reset_timeout=True)
            return True

        if text.isdigit():
            await _show_selected_problem(int(text))
            controller.keep(timeout=180, reset_timeout=True)
            return True

        if await _handle_natural_language_intent(
            controller, await _parse_natural_language_intent(text)
        ):
            return True

        await _show_current_step()
        controller.keep(timeout=180, reset_timeout=True)
        return True

    async def _handle_difficulty_step_input(
        controller: SessionController,
        text: str,
        lower: str,
    ) -> bool:
        if is_jump_help_command(lower):
            await _send_text(render_jump_step('difficulty', state))
            controller.keep(timeout=180, reset_timeout=True)
            return True

        difficulty_message = apply_jump_difficulty_input(state, text)
        if difficulty_message:
            await _send_text(difficulty_message)
            step[0] = 'tags'
            await _show_current_step()
            controller.keep(timeout=180, reset_timeout=True)
            return True

        if await _handle_natural_language_intent(
            controller, await _parse_natural_language_intent(text)
        ):
            return True

        await _send_text('❓ 请输入数字 0-8，或直接说出你的需求，例如「来一道提高+/省选− 的 DP 题」。')
        controller.keep(timeout=180, reset_timeout=True)
        return True

    async def _handle_tags_step_input(
        controller: SessionController,
        text: str,
        lower: str,
    ) -> bool:
        if is_jump_done_command(lower) or is_jump_skip_command(lower):
            step[0] = 'keyword'
            await _show_current_step()
            controller.keep(timeout=180, reset_timeout=True)
            return True

        tag_messages = apply_jump_tag_update(state, text)
        if tag_messages is not None:
            for message in tag_messages:
                await _send_text(message)
            controller.keep(timeout=180, reset_timeout=True)
            return True

        if is_jump_status_command(lower):
            await _send_text(render_jump_step('tags', state))
            controller.keep(timeout=180, reset_timeout=True)
            return True

        if await _handle_natural_language_intent(
            controller, await _parse_natural_language_intent(text)
        ):
            return True

        typo_command = suggest_jump_step_command(text, ('done', 'skip'))
        if typo_command:
            await _send_text(
                f'❓ 你是不是想输入 `{typo_command}`？\n'
                f'{render_selected_tags_update(state)}'
            )
            controller.keep(timeout=180, reset_timeout=True)
            return True

        await _send_text(
            f'❓ 无法理解输入\n'
            f'{render_selected_tags_update(state)}\n\n'
            f'输入 +标签 添加，-标签 移除，done 确认，\n'
            f'也可以直接说「来一道图论最短路题」。'
        )
        controller.keep(timeout=180, reset_timeout=True)
        return True

    async def _handle_keyword_step_input(
        controller: SessionController,
        text: str,
        lower: str,
    ) -> bool:
        await _send_text(apply_jump_keyword_input(state, text, lower))

        ok = await _apply_filters_and_present_results(
            loading_text='🔍 正在应用筛选条件，请稍候...',
        )
        if not ok:
            controller.keep(timeout=180, reset_timeout=True)
            return True
        controller.keep(timeout=180, reset_timeout=True)
        return True

    async def _handle_waiting_md_step_input(
        controller: SessionController,
        text: str,
        lower: str,
    ) -> bool:
        if is_jump_show_image_command(lower):
            await _send_text('🖼️ 正在渲染题面图片，请稍候...')
            await _render_and_send_problem_image(mode='rendered')
            step[0] = 'waiting_md'
            controller.keep(timeout=180, reset_timeout=True)
            return True

        if is_jump_show_screenshot_command(lower):
            await _send_text('📸 正在截取洛谷网页截图，请稍候...')
            await _render_and_send_problem_image(mode='screenshot')
            step[0] = 'waiting_md'
            controller.keep(timeout=180, reset_timeout=True)
            return True

        if is_jump_random_command(lower):
            await _show_random_problem()
            controller.keep(timeout=180, reset_timeout=True)
            return True

        if is_jump_back_to_keyword_command(lower):
            move_jump_to_keyword_step(state)
            step[0] = 'keyword'
            await _send_text('← 返回关键词筛选步骤（保留难度和标签）')
            await _show_current_step()
            controller.keep(timeout=180, reset_timeout=True)
            return True

        if is_jump_back_to_difficulty_command(lower):
            move_jump_to_difficulty_step(state)
            step[0] = 'difficulty'
            await _send_text('← 重置所有条件，返回难度筛选步骤')
            await _send_text(render_jump_step('difficulty', state))
            controller.keep(timeout=180, reset_timeout=True)
            return True

        if is_jump_quit_command(lower):
            await _send_text('✅ 已退出题库跳转，下次见！')
            controller.stop()
            return True

        if await _handle_natural_language_intent(
            controller, await _parse_natural_language_intent(text)
        ):
            return True

        step[0] = 'result'
        controller.keep(timeout=180, reset_timeout=True)
        return True

    async def _handle_jump_global_input(
        controller: SessionController,
        text: str,
        lower: str,
    ) -> bool:
        if is_jump_quit_command(lower):
            await _send_text('✅ 已退出题库跳转，下次见！')
            controller.stop()
            return True

        if is_jump_help_command(lower):
            await _send_text(JUMP_HELP_TEXT)
            controller.keep(timeout=180, reset_timeout=True)
            return True

        direct_pid = _extract_direct_problem_id(text)
        if direct_pid:
            await _send_text(f'🔎 直接定位题号：{direct_pid}')
            await _show_problem(pid=direct_pid)
            controller.keep(timeout=180, reset_timeout=True)
            return True

        return False

    def _extract_direct_problem_id(text: str) -> Optional[str]:
        if not text or text.startswith('+') or text.startswith('-'):
            return None
        return extract_problem_id(text)

    async def _show_problem(position: int = None, pid: str = None):
        """
        展示题目：先发送 Markdown + 点击指令，用户点击后再渲染图片。
        
        流程：
        1. 跳转并获取题目信息
        2. 发送题目摘要（标题、难度、链接）
        3. 发送 Markdown 题面文本 + 点击指令
        4. 用户输入「看图」或点击按钮后，发送渲染图片
        """
        nonlocal fetcher
        try:
            fetcher, pid, detail, md_content, error = await load_jump_problem_detail(
                fetcher=fetcher,
                state=state,
                cookies_file=_cookies,
                run_in_pw=_run_in_pw,
                position=position,
                pid=pid,
            )

            if pid is None:
                await _send_text(error or '❌ 跳转题目失败')
                return

            remember_jump_problem_artifact(
                state,
                pid=pid,
                title=(detail or {}).get('title'),
                md_content=md_content,
            )

            # ── 题目摘要（头部信息） ──
            header = render_problem_header(pid, detail or {})

            # ── 构建合并转发节点 ──
            sender_id = event.message_obj.self_id if hasattr(event, 'message_obj') and hasattr(event.message_obj, 'self_id') else '10000'
            sender_name = '洛谷助手'
            footer = render_problem_footer()
            nodes = build_jump_problem_forward_nodes(
                Comp.Node,
                Comp.Plain,
                sender_id=str(sender_id),
                sender_name=sender_name,
                header=header,
                md_content=md_content or '',
                footer=footer,
            )

            # 尝试合并转发，失败则降级为普通消息
            try:
                mr = event.make_result()
                mr.chain = [Comp.Nodes(nodes)]
                await event.send(mr)
            except Exception as forward_err:
                logger.warning(f'[Luogu jump] 合并转发失败，降级为普通消息: {forward_err}')
                for message in build_jump_problem_fallback_messages(header, md_content or '', footer):
                    await _send_text(message)

            # 切换到 waiting_md 状态，等待用户输入「看图」指令
            step[0] = 'waiting_md'

        except Exception as e:
            logger.error(f'[Luogu jump] 展示题目异常: {traceback.format_exc()}')
            await _send_text(f'❌ 展示题目出错：{e}')

    async def _render_and_send_problem_image(mode: str = 'rendered'):
        """
        `看图` 与 `截图` 当前统一发送洛谷网页截图。
        """
        nonlocal fetcher
        try:
            pid = state.get('current_pid')
            if not pid:
                await _send_text('❌ 没有可渲染的题目')
                return

            if mode == 'rendered':
                await _send_text('ℹ️ 当前已临时关闭 Markdown 长图渲染，改为发送更稳定的网页截图。')

            fetcher = await ensure_jump_fetcher(
                fetcher=fetcher,
                cookies_file=_cookies,
                run_in_pw=_run_in_pw,
            )
            img_bytes = await screenshot_jump_problem(
                fetcher=fetcher,
                pid=str(pid),
                run_in_pw=_run_in_pw,
            )

            img_path = _ensure_image_path(img_bytes) if img_bytes else None

            if img_path:
                if mode == 'screenshot':
                    await _send_text('📸 正在发送洛谷网页截图...')
                else:
                    await _send_text('🖼️ 正在发送洛谷题面截图...')
                await _send_img(img_path)
            else:
                await _send_text('❌ 截图失败')

        except Exception as e:
            logger.error(f'[Luogu jump] 渲染截图异常: {traceback.format_exc()}')
            await _send_text(f'❌ 渲染截图出错：{e}')

    @session_waiter(timeout=180, record_history_chains=False)
    async def jump_waiter(controller: SessionController, ev: AstrMessageEvent):
        nonlocal state
        text = ev.message_str.strip()
        lower = text.lower()
        if await _handle_jump_global_input(controller, text, lower):
            return

        step_handlers = {
            'difficulty': _handle_difficulty_step_input,
            'tags': _handle_tags_step_input,
            'keyword': _handle_keyword_step_input,
            'result': _handle_result_step_input,
            'waiting_md': _handle_waiting_md_step_input,
        }
        handler = step_handlers.get(step[0])
        if handler:
            await handler(controller, text, lower)
            return

    try:
        await _send_text(render_jump_step('difficulty', state))
        await jump_waiter(event)
    except TimeoutError:
        yield event.plain_result('⏰ 会话超时（3分钟无操作），已退出题库跳转')
    except Exception as e:
        logger.error(f'[Luogu jump] 会话异常: {traceback.format_exc()}')
        yield event.plain_result(f'❌ 会话异常：{e}')
    finally:
        # 清理：关闭 ProblemFetcher（释放浏览器资源）
        if fetcher is not None:
            try:
                await _run_in_pw(fetcher.close)
                logger.info('[Luogu jump] ProblemFetcher 已关闭')
            except Exception:
                pass
        # 关闭专用 executor
        _pw_executor.shutdown(wait=False)


HELP_TEXT = """洛谷助手指令：

/luogu bind <手机号> <密码> [-s|--save]
  绑定洛谷账号
  可选参数:
    -s, --save   保存账号密码到本地（加密存储，后续自动登录）
                注意：账号密码仅保存在本设备，不会上传

/luogu info
  查看个人统计卡片
  (含通过/提交/等级分/咕值/排名)

/luogu checkin
  每日打卡（已打卡则返回打卡结果）

/luogu heatmap
  做题热度日历图（近26周）

/luogu elo
  比赛等级分趋势图

/luogu practice
  练习情况（按难度分类）

/luogu jump
  题库跳转，按难度/标签筛选后随机或指定题目
  支持多轮对话，可持续选题

/luogu help
  显示本帮助"""


# ════════════════════════════════════════════════════════════════
# AstrBot 插件类
# ════════════════════════════════════════════════════════════════

GLOBAL_TOOL_HELP_NOTE = (
    "\n\n"
    "补充说明：\n"
    "  - 普通聊天中，主 LLM 会按阶段调用 3 个洛谷工具：`luogu_problem_search`（筛题/选题）、`luogu_problem_statement`（发题面）、`luogu_problem_image`（发题图/截图）。\n"
    "  - 对同一轮普通聊天选题结果，还可以继续说“总共有多少道”“随便来一道”“第 3 题”“转发题面”“看图/截图”。\n"
    "  - `back` 这类显式回退步骤仍然只在 `/luogu jump` 中处理。\n"
    "  - 使用全局 LLM 工具需要 AstrBot 版本 >= 4.5.7。"
)


if _ASTRBOT:
    @register(
        "astrbot_plugin_luogu",
        "洛谷助手",
        "洛谷账号绑定与数据爬取插件",
        "0.2.0",
    )
    class LuoguPlugin(Star):

        def __init__(self, context: Context):
            super().__init__(context)
            self._luogu_llm_sessions: dict[str, dict[str, Any]] = {}
            logger.info('[LuoguPlugin] 插件已加载')

        def _luogu_llm_session_keys(self, event: AstrMessageEvent) -> list[str]:
            keys: list[str] = []
            unified = str(getattr(event, "unified_msg_origin", "") or "").strip()
            fallback = f'{event.get_platform_name()}:{event.get_group_id() or "private"}:{event.get_sender_id()}'
            if unified:
                keys.append(unified)
            if fallback and fallback not in keys:
                keys.append(fallback)
            return keys

        def _get_luogu_llm_session(self, event: AstrMessageEvent) -> Optional[Dict[str, Any]]:
            for key in self._luogu_llm_session_keys(event):
                session = self._luogu_llm_sessions.get(key)
                if session is not None:
                    return session
            return None

        def _set_luogu_llm_session(self, event: AstrMessageEvent, session_data: Dict[str, Any]) -> None:
            for key in self._luogu_llm_session_keys(event):
                self._luogu_llm_sessions[key] = session_data

        def _append_luogu_session_event(self, session_data: Dict[str, Any], event_type: str, **payload: Any) -> None:
            append_session_event(session_data, event_type, **payload)

        async def _send_luogu_problem_forward(
            self,
            event: AstrMessageEvent,
            cfile: str,
            pid: str,
        ) -> str:
            artifact = await run_problem_async(
                cfile,
                lambda fetcher, pid: {
                    "detail": fetcher.get_problem_detail(pid),
                    "md_content": fetcher.extract_markdown_content(pid),
                },
                pid=pid,
            )
            detail = artifact.get("detail") or {}
            md_content = artifact.get("md_content") or ""
            normalized_pid = str(detail.get("pid") or pid).strip().upper()
            if not normalized_pid.startswith("P"):
                normalized_pid = f'P{normalized_pid}'

            header = render_problem_header(normalized_pid, detail)
            sender_id = (
                event.message_obj.self_id
                if hasattr(event, "message_obj") and hasattr(event.message_obj, "self_id")
                else "10000"
            )
            sender_name = "洛谷助手"
            footer = "─────────────────────\n💡 普通聊天里可以继续说“看图”“截图”“再来一道”“总共有多少道”"
            nodes = build_jump_problem_forward_nodes(
                Node,
                Plain,
                sender_id=str(sender_id),
                sender_name=sender_name,
                header=header,
                md_content=md_content,
                footer=footer,
            )

            try:
                mr = event.make_result()
                mr.chain = [Nodes(nodes)]
                await event.send(mr)
            except Exception as exc:
                logger.warning(f'[Luogu LLM] 合并转发失败，降级为普通消息: {exc}')
                for message in build_jump_problem_fallback_messages(header, md_content, footer):
                    await event.send(event.plain_result(message))

            session = self._get_luogu_llm_session(event) or {}
            session["current_pid"] = normalized_pid
            session["current_title"] = detail.get("title") or normalized_pid
            session["current_md"] = md_content
            self._append_luogu_session_event(
                session,
                EVENT_STATEMENT_SENT,
                pid=normalized_pid,
                title=detail.get("title") or normalized_pid,
                markdown=md_content,
            )
            self._set_luogu_llm_session(event, session)
            return f"已将 {normalized_pid} 的题面通过合并消息转发到当前会话。"

        async def _send_luogu_problem_image(
            self,
            event: AstrMessageEvent,
            cfile: str,
            pid: str,
            *,
            mode: str,
        ) -> str:
            img_bytes = await run_problem_async(
                cfile,
                lambda fetcher, pid: fetcher.screenshot_problem(pid),
                pid=pid,
            )
            img_path = _ensure_image_path(img_bytes)
            if not img_path:
                return f"{pid} 的题面截图发送失败。"
            await event.send(event.plain_result("ℹ️ 当前普通聊天仍使用更稳定的网页截图路径。"))
            await event.send(event.image_result(img_path))
            session = self._get_luogu_llm_session(event) or {}
            self._append_luogu_session_event(session, EVENT_IMAGE_SENT, pid=pid, mode=mode)
            self._set_luogu_llm_session(event, session)
            return f"已发送 {pid} 的题面截图。"

        @filter.on_llm_request(priority=110)
        async def on_llm_request(self, event, req):
            message = getattr(event, "message_str", "") or ""
            luogu_session = self._get_luogu_llm_session(event)
            request_plan = await plan_luogu_llm_request(
                context=self.context,
                event=event,
                message=message,
                session_data=luogu_session,
                session_snapshot=format_luogu_session_snapshot(luogu_session),
                classify_intent=classify_luogu_routing_intent,
            )
            if not request_plan:
                return
            if request_plan.classifier_routed:
                logger.info(
                    "[Luogu LLM] classifier routed request to luogu_problem_search: confidence=%s reason=%s matched=%s",
                    (request_plan.classifier_decision or {}).get("confidence"),
                    (request_plan.classifier_decision or {}).get("reason"),
                    request_plan.scope_hits,
                )

            tool_mgr = self.context.get_llm_tool_manager()
            policy = request_plan.policy
            follow_up = policy.follow_up
            direct_pid = policy.direct_pid
            workflow_plan = policy.workflow_plan

            if workflow_plan:
                logger.info(
                    "[Luogu Workflow] planned request: intent=%s state=%s commands=%s",
                    workflow_plan.intent.intent.value,
                    workflow_plan.workflow_state.value,
                    [command.name for command in workflow_plan.commands],
                )

            removed_parts = enforce_luogu_request(
                context=self.context,
                tool_manager=tool_mgr,
                req=req,
                request_plan=request_plan,
                text_part_cls=TextPart,
                toolset_cls=ToolSet,
            )
            if request_plan.quoted_image_context:
                logger.info('[Luogu LLM] sanitized quoted-image request parts: removed=%s', removed_parts)
            logger.info(
                '[Luogu LLM] enforced luogu toolset for current request: tools=%s follow_up=%s direct_pid=%s quoted_image=%s',
                req.func_tool.names() if req.func_tool else [],
                follow_up,
                direct_pid,
                request_plan.quoted_image_context,
            )

        # ── /luogu ────────────────────────────────────────────

        @filter.llm_tool(name="luogu_problem_search")
        async def luogu_problem_search(self, event: AstrMessageEvent, query: str = "", limit: int = 10) -> str:
            """只负责普通聊天里的洛谷筛题、续筛、总数追问和选题。

            Args:
                query (str): 用户的自然语言筛题/追问文本；缺失时会回退到 `event.message_str`。
                limit (int): 候选列表最多返回多少道题，范围 1-20。
            """
            qq_id = str(event.get_sender_id())
            cfile, cookie_error = resolve_luogu_bound_cookie_file(_cookies_path(qq_id))
            if cookie_error:
                return cookie_error

            query = (query or '').strip()
            if not query:
                query = (getattr(event, "message_str", "") or "").strip()
                if query:
                    logger.info("[Luogu LLM] recovered missing query from event.message_str")
            if not query:
                return "缺少选题需求，请给出自然语言描述，例如“来一道提高组图论题”。"

            limit = max(1, min(int(limit or 10), 20))
            result, updated_session = await execute_luogu_lookup_turn(
                context=self.context,
                event=event,
                cfile=cfile,
                query=query,
                limit=limit,
                session_data=self._get_luogu_llm_session(event),
            )
            self._set_luogu_llm_session(event, updated_session)
            return result

        @filter.llm_tool(name="luogu_problem_statement")
        async def luogu_problem_statement(self, event: AstrMessageEvent, pid: str = "") -> str:
            """只负责根据题号或当前 session 发送题面。

            Args:
                pid (str): 目标题号；省略时读取当前 Luogu session 的 `current_pid`。
            """

            qq_id = str(event.get_sender_id())
            cfile, resolved_pid, error = prepare_luogu_problem_display_target(
                cookie_file=_cookies_path(qq_id),
                requested_pid=pid,
                event_message=getattr(event, "message_str", "") or "",
                session_data=self._get_luogu_llm_session(event),
            )
            if error:
                return error
            return await self._send_luogu_problem_forward(event, cfile, resolved_pid or "")

        @filter.llm_tool(name="luogu_problem_image")
        async def luogu_problem_image(
            self,
            event: AstrMessageEvent,
            pid: str = "",
            mode: str = "rendered",
        ) -> str:
            """只负责根据题号或当前 session 发送题图/截图。

            Args:
                pid (str): 目标题号；省略时读取当前 Luogu session 的 `current_pid`。
                mode (str): `rendered` 发送渲染图，`screenshot` 发送网页截图。
            """

            qq_id = str(event.get_sender_id())
            cfile, resolved_pid, error = prepare_luogu_problem_display_target(
                cookie_file=_cookies_path(qq_id),
                requested_pid=pid,
                event_message=getattr(event, "message_str", "") or "",
                session_data=self._get_luogu_llm_session(event),
            )
            if error:
                return error

            normalized_mode = normalize_luogu_image_mode(
                mode,
                getattr(event, "message_str", "") or "",
            )
            return await self._send_luogu_problem_image(
                event,
                cfile,
                resolved_pid or "",
                mode=normalized_mode,
            )

        @filter.command("luogu", priority=999)
        async def cmd_luogu(self, event: AstrMessageEvent):
            event.stop_event()
            args = event.message_str.strip().split()
            sub = args[1].lower() if len(args) > 1 else 'help'
            qq_id = str(event.get_sender_id())

            if sub == 'help':
                yield event.plain_result(HELP_TEXT + GLOBAL_TOOL_HELP_NOTE)
                return

            if sub == 'bind':
                # 解析参数：支持 /luogu bind <手机号> <密码> [-s|--save]
                if len(args) < 3:
                    yield event.plain_result("用法：/luogu bind <手机号> <密码> [-s|--save]\n"
                                            "可选参数 -s: 保存账号密码到本地（加密存储）\n"
                                            "请注意在私聊中使用以保护密码安全")
                    return

                username = args[2]
                password = None
                save_credentials = False

                # 检查是否有 -s 或 --save 参数
                raw_args = event.message_str.strip()
                save_credentials = '-s' in raw_args or '--save' in raw_args

                # 查找密码参数（可能在 -s 之前或之后）
                for i, arg in enumerate(args[3:], start=3):
                    if arg not in ('-s', '--save'):
                        password = arg
                        break

                if not password:
                    yield event.plain_result("用法：/luogu bind <手机号> <密码> [-s|--save]\n"
                                            "请提供密码参数")
                    return

                logger.info(f'[Luogu] 用户 {qq_id} 开始登录流程，保存账号密码: {save_credentials}')
                yield event.plain_result("🔐 正在登录洛谷，请稍候（约10~30秒）...")
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None, lambda: _do_login(username, password, qq_id, save_credentials)
                )
                if result['success']:
                    uid = result.get('uid', '未知')
                    logger.info(f'[Luogu] 用户 {qq_id} 登录成功，UID: {uid}，数据已保存')
                    if result.get('data_saved'):
                        yield event.chain_result([Face(id=124), Plain(f" 绑定成功！洛谷 UID：{uid}")])
                    else:
                        yield event.chain_result([Face(id=123), Plain(f" 绑定成功！洛谷 UID：{uid}，部分数据获取失败")])
                    if result.get('credentials_saved'):
                        yield event.plain_result("✅ 账号密码已加密保存在本地（仅本设备可用）")
                else:
                    logger.warning(f'[Luogu] 用户 {qq_id} 登录失败: {result["message"]}')
                    yield event.chain_result([Face(id=100), Plain(f" 绑定失败：{result['message']}")])
                return

            # 以下指令需要先绑定
            cfile, cookie_error = resolve_luogu_bound_cookie_file(_cookies_path(qq_id))
            if cookie_error:
                yield event.plain_result("请先用 /luogu bind 绑定账号")
                return

            if sub == 'checkin':
                logger.info(f'[Luogu] 用户 {qq_id} 请求打卡')
                yield event.plain_result("📸 正在截取打卡页面...")
                try:
                    # 截图打卡页面
                    logger.info(f'[Luogu] 开始截取打卡截图...')
                    img_bytes = await _run_async(cfile, qq_id, _task_screenshot_checkin)
                    img_path = _ensure_image_path(img_bytes)
                    if img_path:
                        logger.info(f'[Luogu] 打卡截图成功，准备发送...')
                        yield event.image_result(img_path)
                    else:
                        logger.warning(f'[Luogu] 打卡截图获取失败')
                        yield event.plain_result("❌ 无法获取打卡截图")
                except Exception as e:
                    logger.error(f'[Luogu] checkin error: {traceback.format_exc()}')
                    yield event.plain_result(f"❌ 打卡出错：{e}")
                return

            if sub == 'info':
                force_refresh = '-f' in args[1:]
                logger.info(f'[Luogu] 用户 {qq_id} 请求 info (force={force_refresh})')

                # 尝试读取已保存的数据
                userdata_file = _userdata_path(qq_id)
                cached_profile = None
                if not force_refresh and userdata_file.exists():
                    try:
                        import json as _json
                        with open(userdata_file, 'r', encoding='utf-8') as f:
                            userdata = _json.load(f)
                            cached_profile = userdata.get('profile')
                            if cached_profile:
                                logger.info(f'[Luogu] 使用已缓存的 profile 数据')
                    except Exception:
                        pass

                if cached_profile:
                    text = _fmt_profile(cached_profile)
                    yield event.plain_result(text)
                else:
                    yield event.plain_result("📊 正在获取个人数据...")
                    try:
                        logger.info(f'[Luogu] 开始获取个人主页数据...')
                        profile = await _run_async(cfile, qq_id, _task_profile)
                        if not profile:
                            logger.warning(f'[Luogu] 用户 {qq_id} 获取数据失败')
                            yield event.plain_result("❌ 获取数据失败，请检查账号是否有效")
                            return
                        logger.info(f'[Luogu] 数据获取完成，准备格式化...')
                        text = _fmt_profile(profile)
                        logger.info(f'[Luogu] info 命令执行完成')
                        yield event.plain_result(text)
                    except Exception as e:
                        logger.error(f'[Luogu] info error: {traceback.format_exc()}')
                        yield event.plain_result(f"❌ 获取数据出错：{e}")
                return

            if sub == 'heatmap':
                logger.info(f'[Luogu] 用户 {qq_id} 请求 heatmap')
                yield event.plain_result("📈 正在截取热度图...")
                try:
                    logger.info(f'[Luogu] 开始截取热度图...')
                    img_bytes = await _run_async(cfile, qq_id, _task_screenshot_heatmap)
                    img_path = _ensure_image_path(img_bytes)
                    if img_path:
                        logger.info(f'[Luogu] 热度图截图成功，准备发送...')
                        yield event.image_result(img_path)
                    else:
                        logger.warning(f'[Luogu] 热度图截图获取失败')
                        yield event.plain_result("❌ 无法获取热度图，请确认账号有做题数据")
                except Exception as e:
                    logger.error(f'[Luogu] heatmap error: {traceback.format_exc()}')
                    yield event.plain_result(f"❌ 生成热度图出错：{e}")
                return

            if sub == 'elo':
                logger.info(f'[Luogu] 用户 {qq_id} 请求 elo')
                yield event.plain_result("📉 正在生成等级分趋势图...")
                try:
                    logger.info(f'[Luogu] 开始获取等级分数据...')
                    # 获取等级分数据
                    profile = await _run_async(cfile, qq_id, _task_profile)
                    elo_history = profile.get('elo_history', [])
                    
                    if elo_history:
                        logger.info(f'[Luogu] 等级分历史: {len(elo_history)} 条，开始生成趋势图...')
                        # 使用生成方案
                        username = profile.get('name', '')
                        img_bytes = await asyncio.get_event_loop().run_in_executor(
                            None, 
                            lambda: generate_elo_trend(elo_history, username=username)
                        )
                        img_path = _ensure_image_path(img_bytes)
                        if img_path:
                            logger.info(f'[Luogu] 趋势图生成成功，准备发送...')
                            yield event.image_result(img_path)
                        else:
                            logger.warning(f'[Luogu] 趋势图生成失败')
                            yield event.plain_result("❌ 生成趋势图失败")
                    else:
                        logger.warning(f'[Luogu] 用户 {qq_id} 无等级分数据')
                        yield event.plain_result("❌ 暂无等级分数据，请确认账号有参加比赛记录")
                except Exception as e:
                    logger.error(f'[Luogu] elo error: {traceback.format_exc()}')
                    yield event.plain_result(f"❌ 生成趋势图出错：{e}")
                return

            if sub == 'jump':
                logger.info(f'[Luogu] 用户 {qq_id} 请求题库跳转')
                jump_count = 1
                if len(args) > 2:
                    try:
                        jump_count = clamp_luogu_request_count(int(args[2]))
                    except Exception:
                        jump_count = 1
                async for result in _jump_session_flow(
                    self.context,
                    event,
                    cfile,
                    requested_count=jump_count,
                ):
                    yield result
                return

            if sub == 'practice':
                force_refresh = '-f' in args[1:]  # 检查是否有 -f 参数
                logger.info(f'[Luogu] 用户 {qq_id} 请求 practice (force={force_refresh})')

                # 尝试读取已保存的数据
                userdata_file = _userdata_path(qq_id)
                cached_practice = None
                if not force_refresh and userdata_file.exists():
                    try:
                        import json as _json
                        with open(userdata_file, 'r', encoding='utf-8') as f:
                            userdata = _json.load(f)
                            cached_practice = userdata.get('practice')
                            if cached_practice:
                                logger.info(f'[Luogu] 使用已缓存的练习数据，已通过 {cached_practice.get("total_passed", 0)} 题')
                    except Exception:
                        pass

                if cached_practice:
                    # 使用缓存数据
                    text = _fmt_practice(cached_practice)
                    yield event.plain_result(text)

                    # 生成难度分布卡片
                    passed_data = {d: len(pids) for d, pids in cached_practice.get('passed_by_difficulty', {}).items() if pids}
                    if passed_data:
                        card_bytes = await asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda: generate_difficulty_cards(passed_data, username=cached_practice.get('name', ''))
                        )
                        card_path = _ensure_image_path(card_bytes)
                        if card_path:
                            yield event.image_result(card_path)
                else:
                    # 需要重新获取
                    yield event.plain_result("📚 正在获取练习数据...")
                    try:
                        logger.info(f'[Luogu] 开始获取练习数据...')
                        practice = await _run_async(cfile, qq_id, _task_practice)
                        logger.info(f'[Luogu] 练习数据获取完成，已通过 {practice.get("total_passed", 0)} 题')
                        text = _fmt_practice(practice)
                        yield event.plain_result(text)

                        # 生成难度分布卡片
                        passed_data = {d: len(pids) for d, pids in practice.get('passed_by_difficulty', {}).items() if pids}
                        if passed_data:
                            card_bytes = await asyncio.get_event_loop().run_in_executor(
                                None,
                                lambda: generate_difficulty_cards(passed_data, username=practice.get('name', ''))
                            )
                            card_path = _ensure_image_path(card_bytes)
                            if card_path:
                                yield event.image_result(card_path)
                    except Exception as e:
                        logger.error(f'[Luogu] practice error: {traceback.format_exc()}')
                        yield event.plain_result(f"❌ 获取练习数据出错：{e}")
                return

            yield event.plain_result(HELP_TEXT + GLOBAL_TOOL_HELP_NOTE)


# ════════════════════════════════════════════════════════════════
# 独立运行（命令行测试）
# ════════════════════════════════════════════════════════════════

def _standalone_test():
    """命令行测试入口：直接用已有 cookies 文件测试所有功能"""
    import argparse

    parser = argparse.ArgumentParser(description='洛谷插件命令行测试')
    parser.add_argument('--cookies', default='cookies/cookies_19738806113.json',
                        help='cookies 文件路径')
    parser.add_argument('--uid', default=None, help='手动指定 UID（可选）')
    parser.add_argument('--action',
                        choices=['all', 'profile', 'practice', 'checkin',
                                 'heatmap', 'elo', 'card'],
                        default='all')
    parser.add_argument('--save-dir', default='screenshots', help='图表保存目录')
    args = parser.parse_args()

    os.makedirs(args.save_dir, exist_ok=True)
    print(f'使用 cookies: {args.cookies}')

    with LuoguDataFetcher(args.cookies, user_id=args.uid) as fetcher:

        if args.action in ('all', 'checkin'):
            print('\n── 打卡 ──')
            r = fetcher.checkin()
            print(_fmt_checkin(r))

        if args.action in ('all', 'profile', 'heatmap', 'elo', 'card'):
            print('\n── 个人主页数据 ──')
            profile = fetcher.fetch_profile_stats()
            print(f"  UID:   {profile.get('uid')}")
            print(f"  用户名: {profile.get('name')}")
            print(f"  通过:  {profile.get('passed')} 题")
            print(f"  提交:  {profile.get('submitted')} 次")
            print(f"  等级分:{profile.get('rating')}")
            print(f"  咕值:  {profile.get('csr')}")
            print(f"  排名:  #{profile.get('rank')}")
            print(f"  评定比赛: {profile.get('contests')}")
            dc = profile.get('daily_counts', {})
            print(f"  热度图数据: {len(dc)} 天")
            print(f"  等级分历史: {len(profile.get('elo_history', []))} 条")

        if args.action in ('all', 'card'):
            print('\n── 生成统计卡片 ──')
            card_path = f'{args.save_dir}/summary_card.png'
            generate_summary_card(profile, save_path=card_path)
            print(f'  已保存: {card_path}')

        if args.action in ('all', 'heatmap'):
            print('\n── 生成热度图 ──')
            dc = profile.get('daily_counts', {})
            if dc:
                hm_path = f'{args.save_dir}/heatmap.png'
                generate_heatmap(dc, username=profile.get('name', ''),
                                  save_path=hm_path)
                print(f'  已保存: {hm_path}')
            else:
                print('  无热度图数据')

        if args.action in ('all', 'elo'):
            print('\n── 生成等级分趋势图 ──')
            elo = profile.get('elo_history', [])
            if elo:
                elo_path = f'{args.save_dir}/elo_trend.png'
                generate_elo_trend(elo, username=profile.get('name', ''),
                                   save_path=elo_path)
                print(f'  已保存: {elo_path}')
            else:
                print('  无等级分历史数据')

        if args.action in ('all', 'practice'):
            print('\n── 练习情况 ──')
            practice = fetcher.fetch_practice_data()
            print(_fmt_practice(practice))

            by_diff = practice.get('passed_by_difficulty', {})
            bar_data = {d: len(pids) for d, pids in by_diff.items() if pids}
            if bar_data:
                bar_path = f'{args.save_dir}/practice_bar.png'
                generate_bar_chart(
                    bar_data,
                    title=f"{practice.get('total_passed', 0)} 题按难度分布",
                    ylabel='题数', color='#1890ff',
                    save_path=bar_path
                )
                print(f'  柱状图已保存: {bar_path}')

    print('\n✅ 测试完成')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    _standalone_test()
