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
    from astrbot.core.utils.session_waiter import session_waiter, SessionController
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
from luogu.tags import DIFFICULTY_NAMES, HOT_TAGS, fuzzy_match_tag, DIFFICULTY_COLORS
from luogu.chart_generator import (
    generate_summary_card,
    generate_heatmap,
    generate_elo_trend,
    generate_bar_chart,
    generate_difficulty_cards,
)

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
    检测 cookie 是否有效。
    通过调用洛谷 API 检查是否返回登录用户数据。
    返回 True 表示有效，False 表示已过期。
    """
    import requests

    if not Path(cookies_file).exists():
        return False

    try:
        with open(cookies_file, 'r', encoding='utf-8') as f:
            cookie_data = json.load(f)

        # 转换为 requests 格式
        cookies = {}
        for c in cookie_data.get('cookies', []):
            cookies[c['name']] = c['value']

        if not cookies:
            return False

        # 调用 API 检测
        resp = requests.get(
            'https://www.luogu.com.cn/api/visitor/user',
            cookies=cookies,
            headers={
                'Accept': 'application/json',
                'Referer': 'https://www.luogu.com.cn/',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            },
            timeout=10
        )

        if resp.status_code != 200:
            return False

        data = resp.json()
        # 如果返回了用户数据，说明 cookie 有效
        if data.get('code') == 200 and data.get('user'):
            return True
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

# 题面 HTML 渲染模板（备用：用于 html_render / html_to_pic）
PROBLEM_HTML_TMPL = '''<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    background: #f5f6fa;
    padding: 16px;
  }
  .card {
    background: white;
    border-radius: 10px;
    box-shadow: 0 2px 12px rgba(0,0,0,0.08);
    overflow: hidden;
  }
  .header {
    background: linear-gradient(135deg, #1890ff, #722ed1);
    color: white;
    padding: 14px 20px;
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .pid {
    background: rgba(255,255,255,0.2);
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 13px;
    font-weight: 600;
  }
  .title {
    font-size: 17px;
    font-weight: 600;
    flex: 1;
  }
  .difficulty-badge {
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 12px;
    font-weight: 600;
  }
  .meta {
    padding: 10px 20px;
    border-bottom: 1px solid #f0f0f0;
    display: flex;
    gap: 16px;
    font-size: 13px;
    color: #666;
    flex-wrap: wrap;
  }
  .meta span { display: flex; align-items: center; gap: 4px; }
  .tags {
    padding: 10px 20px;
    border-bottom: 1px solid #f0f0f0;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .tag {
    background: #e6f7ff;
    color: #1890ff;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 12px;
  }
  .content {
    padding: 20px;
    line-height: 1.8;
    font-size: 15px;
    color: #222;
    max-width: 800px;
  }
  .content h3 {
    color: #1890ff;
    margin: 16px 0 8px;
    font-size: 15px;
  }
  .content h3:first-child { margin-top: 0; }
  .content p { margin: 8px 0; }
  .content pre {
    background: #f7f8fa;
    border: 1px solid #e8e8e8;
    border-radius: 6px;
    padding: 12px;
    margin: 10px 0;
    overflow-x: auto;
    font-size: 13px;
    line-height: 1.5;
  }
  .content code {
    font-family: "Fira Code", "Cascadia Code", Consolas, monospace;
    font-size: 13px;
  }
  .content ul, .content ol {
    padding-left: 24px;
    margin: 8px 0;
  }
  .content li { margin: 4px 0; }
  .content table {
    border-collapse: collapse;
    width: 100%;
    margin: 10px 0;
  }
  .content th, .content td {
    border: 1px solid #e8e8e8;
    padding: 6px 12px;
    text-align: left;
    font-size: 13px;
  }
  .content th { background: #f7f8fa; font-weight: 600; }
  .footer {
    padding: 10px 20px;
    border-top: 1px solid #f0f0f0;
    font-size: 12px;
    color: #999;
    text-align: center;
  }
</style>
</head>
<body>
<div class="card">
  <div class="header">
    <span class="pid">{{ pid }}</span>
    <span class="title">{{ title }}</span>
    <span class="difficulty-badge" style="background:{{ diff_bg }};color:{{ diff_color }}">{{ diff_name }}</span>
  </div>
  <div class="meta">
    {% if passed_rate %}<span>📊 通过率 {{ passed_rate }}</span>{% endif %}
    {% if submit_count %}<span>📝 提交 {{ submit_count }}</span>{% endif %}
  </div>
  {% if tags %}
  <div class="tags">
    {% for tag in tags %}
    <span class="tag">{{ tag }}</span>
    {% endfor %}
  </div>
  {% endif %}
  <div class="content">
    {{ content | safe }}
  </div>
  <div class="footer">洛谷题库 · {{ url }}</div>
</div>
</body>
</html>
'''


def _build_problem_html(detail: dict) -> str:
    """用 Jinja2 模板构建题面 HTML（用于 html_render）"""
    diff_name = detail.get('difficulty_name', '暂无评定')
    diff_bg = DIFFICULTY_COLORS.get(diff_name, '#ebedf0')
    # 白色文字用于深色背景
    diff_color = '#fff'

    content = detail.get('content_html', '')
    if not content:
        # 兜底：markdown 转简单 HTML
        content = detail.get('content_md', '')

    return PROBLEM_HTML_TMPL.format(
        pid=detail.get('pid', 'P????'),
        title=detail.get('title', '未知题目'),
        diff_name=diff_name,
        diff_bg=diff_bg,
        diff_color=diff_color,
        passed_rate=detail.get('passed_rate', ''),
        submit_count=detail.get('submit_count', ''),
        tags=detail.get('tags', [])[:10],
        content=content,
        url=detail.get('url', ''),
    )


# ════════════════════════════════════════════════════════════════
# /jump 题库跳转：5步状态机会话
# ════════════════════════════════════════════════════════════════

_JUMP_STEP_TEXT = {
    'difficulty': (
        "━━━ Step 1：难度筛选 ━━━\n\n"
        "请选择题目难度（输入数字 0-8）：\n\n"
        "  0. 跳过（不限难度）\n"
        "  1. 暂无评定\n"
        "  2. 入门\n"
        "  3. 普及−\n"
        "  4. 普及/提高−\n"
        "  5. 普及+/提高\n"
        "  6. 提高+/省选−\n"
        "  7. 省选/NOI−\n"
        "  8. NOI/NOI+/CTSC\n\n"
        "直接发送数字即可，如：2"
    ),
    'tags': (
        "━━━ Step 2：标签筛选 ━━━\n\n"
        "请输入算法/来源/时间/特殊标签：\n\n"
        "  输入 +标签  添加（如 +动规）\n"
        "  输入 -标签  移除（如 -动规）\n"
        "  输入 done  确认筛选\n\n"
        "支持模糊匹配，如：+图论、+DP、+字符串\n\n"
        "当前已选标签：{current_tags}\n\n"
        "示例：\n"
        "  +动规  → 添加「动态规划」\n"
        "  -搜索  → 移除「搜索」\n"
        "  done   → 确认并进入下一步"
    ),
    'keyword': (
        "━━━ Step 3：关键词筛选（可选） ━━━\n\n"
        "请输入标题关键词（直接输入，留空跳过）：\n\n"
        "  输入 skip 跳过此步\n"
        "  或直接输入关键词，如：模拟、贪心\n\n"
        "当前筛选条件：\n"
        "  难度：{difficulty_str}\n"
        "  标签：{tags_str}\n"
        "  关键词：{keyword_str}"
    ),
    'result': (
        "━━━ Step 4：筛选结果 ━━━\n\n"
        "共筛选出 {total} 道题\n\n"
        "  请输入序号（1-{total}）选题\n"
        "  或输入 random 随机选一道\n"
        "  或输入 back 返回修改筛选\n\n"
        "当前筛选条件：\n"
        "  难度：{difficulty_str}\n"
        "  标签：{tags_str}\n"
        "  关键词：{keyword_str}"
    ),
}


def _jump_diff_str(state):
    # state['difficulty'] 是用户选项数字（0=不限, 1=暂无评定, 2=入门, 3=普及-, ...）
    # DIFFICULTY_NAMES 是 0-indexed（0=暂无评定, 1=入门, 2=普及-, ...）
    d = state.get('difficulty')
    if d is None:
        return '不限'
    # 用户选项 1=暂无评定(difficulty=0), 2=入门(difficulty=1), 3=普及-(difficulty=2), ...
    return DIFFICULTY_NAMES[d - 1] if 1 <= d <= 8 else '不限'


def _jump_tags_str(state):
    return '、'.join(state['tags']) if state['tags'] else '无'


def _jump_kw_str(state):
    return state.get('keyword') or '无'


async def _jump_session_flow(event: AstrMessageEvent, cookies_file: str):
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

    # --- 检测 cookie 是否有效 ---
    logger.info(f'[Luogu jump] 检测 cookie 有效性: {cookies_file}')
    cookie_valid = await asyncio.get_event_loop().run_in_executor(
        None, _check_cookie_valid, cookies_file
    )

    # 如果 cookie 无效，检查是否有保存的账密并尝试自动重新登录
    if not cookie_valid:
        logger.warning('[Luogu jump] Cookie 已过期，检查是否有保存的账密...')
        creds = _load_credentials(qq_id)
        if creds:
            username, password = creds
            logger.info(f'[Luogu jump] 发现保存的账密，正在自动登录...')
            yield event.plain_result("🔄 Cookie 已过期，正在使用保存的账密自动重新登录...")
            loop = asyncio.get_event_loop()
            login_result = await loop.run_in_executor(
                None, lambda: _do_login(username, password, qq_id, save_credentials=False)
            )
            if login_result.get('success'):
                logger.info(f'[Luogu jump] 自动登录成功')
                # 重新检测 cookie
                cookie_valid = await asyncio.get_event_loop().run_in_executor(
                    None, _check_cookie_valid, cookies_file
                )
                if not cookie_valid:
                    yield event.plain_result('⚠️ 自动登录成功但 Cookie 仍无效，请重新绑定')
                    return
            else:
                yield event.plain_result(
                    f'⚠️ 自动登录失败：{login_result.get("message", "未知错误")}\n'
                    '请重新绑定账号'
                )
                return
        else:
            logger.warning('[Luogu jump] Cookie 已过期，且无保存的账密')
            yield event.plain_result(
                '⚠️ 登录状态已失效，请重新绑定账号后继续。\n'
                '使用方法：/luogu bind <手机号> <密码>'
            )
            return

    # --- 专用单线程 executor（所有 Playwright 操作必须在同一线程） ---
    _pw_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='pw_jump')

    async def _run_in_pw(fn):
        """在专用 Playwright 线程中执行同步函数。"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_pw_executor, fn)

    # --- 状态初始化 ---
    state = {
        'difficulty': None,
        'tags': [],
        'keyword': None,
        'total': 0,
        'list_url': None,       # 题库列表页 URL（apply_filters 后保存）
        'page_size': 50,        # 每页题数（apply_filters 时动态检测）
    }
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
        if s == 'tags':
            await _send_text(_JUMP_STEP_TEXT['tags'].format(
                current_tags=_jump_tags_str(state) or '（无）'
            ))
        elif s == 'keyword':
            await _send_text(_JUMP_STEP_TEXT['keyword'].format(
                difficulty_str=_jump_diff_str(state),
                tags_str=_jump_tags_str(state),
                keyword_str=_jump_kw_str(state),
            ))
        elif s == 'result':
            await _send_text(_JUMP_STEP_TEXT['result'].format(
                total=state['total'],
                difficulty_str=_jump_diff_str(state),
                tags_str=_jump_tags_str(state),
                keyword_str=_jump_kw_str(state),
            ))

    async def _apply_filters() -> bool:
        nonlocal fetcher
        try:
            # 使用单一实例（所有 Playwright 操作必须在同一线程）
            if fetcher is None:
                fetcher = ProblemFetcher(_cookies)
                await _run_in_pw(fetcher.setup)
            else:
                logger.info('[Luogu jump] 复用已有 ProblemFetcher 实例')

            def _do_apply():
                user_diff = state.get('difficulty')
                url_difficulty = (user_diff - 1) if user_diff is not None else None
                return fetcher.apply_filters(
                    difficulty=url_difficulty,
                    tags=state['tags'] if state['tags'] else None,
                    keyword=state['keyword'] if state['keyword'] else None,
                )

            r = await _run_in_pw(_do_apply)
            if not r.get('success'):
                await _send_text(f'❌ 筛选失败：{r.get("message", "未知错误")}')
                return False
            state['total'] = r.get('total', 0)
            state['list_url'] = r.get('list_url')
            state['page_size'] = r.get('page_size_detected', 50)
            logger.info(f'[Luogu jump] 筛选完成: total={state["total"]}, page_size={state["page_size"]}, list_url={state["list_url"]}')
            return True
        except Exception as e:
            logger.error(f'[Luogu jump] 筛选异常: {traceback.format_exc()}')
            await _send_text(f'❌ 筛选出错：{e}')
            return False

    async def _show_problem(position: int = None):
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
            # 使用同一实例（所有 Playwright 操作必须在同一线程）
            if fetcher is None:
                fetcher = ProblemFetcher(_cookies)
                await _run_in_pw(fetcher.setup)
                # 恢复题库列表页
                if state.get('list_url'):
                    def _goto_list():
                        fetcher.page.goto(state['list_url'], timeout=20000)
                        fetcher.page.wait_for_load_state('domcontentloaded', timeout=15000)
                        import time as _time; _time.sleep(1.5)
                    await _run_in_pw(_goto_list)

            def _do_show():
                if position:
                    # 传入 list_url 用于 page 失效时恢复
                    pid = fetcher.navigate_to_problem(position, list_url=state.get('list_url'))
                    if not pid:
                        return None, None, None, f'❌ 跳转题目失败（page_size={state.get("page_size")}, list_url={state.get("list_url")}）'
                import re as _re
                url = fetcher.page.url
                pid_m = _re.search(r'/problem/(P?\w+)', url, _re.IGNORECASE)
                pid = pid_m.group(1) if pid_m else '???'
                if not pid.upper().startswith('P'):
                    pid = 'P' + pid.upper().lstrip('P')
                detail = fetcher.get_problem_detail(pid)
                # 通过 API 获取原始 Markdown 内容
                md_content = fetcher.extract_markdown_content(pid)
                return pid, detail, md_content, None

            result = await _run_in_pw(_do_show)
            pid = result[0]
            detail = result[1]
            md_content = result[2]

            if pid is None:
                await _send_text(result[3])  # 错误消息
                return

            diff_name = detail.get('difficulty_name', '暂无评定')
            diff_emoji = {
                '暂无评定': '⚪', '入门': '🔴', '普及−': '🟠',
                '普及/提高−': '🟡', '普及+/提高': '🟢', '提高+/省选−': '🔵',
                '省选/NOI−': '🟣', 'NOI/NOI+/CTSC': '⚫',
            }.get(diff_name, '⬜')

            # 保存当前 PID 到 state，供「看图」指令使用
            state['current_pid'] = pid
            state['current_md'] = md_content

            # ── 题目摘要（头部信息） ──
            header = (
                f'📌 {pid}  {detail.get("title", "")}\n'
                f'{diff_emoji} 难度：{diff_name}'
            )
            if detail.get('passed_rate'):
                header += f'\n📊 通过率：{detail.get("passed_rate")}'
            header += f'\n🔗 https://www.luogu.com.cn/problem/{pid}'
            tags_list = detail.get('tags', [])
            if tags_list:
                header += f'\n🏷️ 标签：{"、".join(tags_list[:8])}'

            # ── 构建合并转发节点 ──
            # 将 Markdown 内容按 1500 字分段，每段一个 Node
            # 使用 event.message_obj.self_id 获取 bot 自己的 ID，使合并转发显示为 bot 发送
            sender_id = event.message_obj.self_id if hasattr(event, 'message_obj') and hasattr(event.message_obj, 'self_id') else '10000'
            sender_name = '洛谷助手'

            nodes = []

            # Node 1: 摘要
            nodes.append(Comp.Node(
                uin=sender_id,
                name=sender_name,
                content=[Comp.Plain(header)],
            ))

            # Node 2+: Markdown 内容分段
            MAX_CHUNK = 1500
            if md_content and len(md_content) > 20:
                chunks = [md_content[i:i+MAX_CHUNK] for i in range(0, len(md_content), MAX_CHUNK)]
                for idx, chunk in enumerate(chunks):
                    label = f'📄 题目内容' if idx == 0 else f'📄 题目内容（续{idx}）'
                    if len(chunks) > 1:
                        label += f' [{idx+1}/{len(chunks)}]'
                    nodes.append(Comp.Node(
                        uin=sender_id,
                        name=sender_name,
                        content=[Comp.Plain(f'{label}\n\n{chunk}')],
                    ))
            else:
                nodes.append(Comp.Node(
                    uin=sender_id,
                    name=sender_name,
                    content=[Comp.Plain('📄 题目内容为空或获取失败')],
                ))

            # Node 尾部：操作提示
            footer = (
                '─────────────────────\n'
                '💡 输入「看图」或「截图」查看渲染后题面截图\n'
                '「random」随机下一题  「back」重新选题  「quit」退出'
            )
            nodes.append(Comp.Node(
                uin=sender_id,
                name=sender_name,
                content=[Comp.Plain(footer)],
            ))

            # 尝试合并转发，失败则降级为普通消息
            try:
                mr = event.make_result()
                mr.chain = [Comp.Nodes(nodes)]
                await event.send(mr)
            except Exception as forward_err:
                logger.warning(f'[Luogu jump] 合并转发失败，降级为普通消息: {forward_err}')
                # 降级：仅发摘要 + 前 800 字
                await _send_text(header)
                short_md = md_content[:800] if md_content else '（内容为空）'
                if len(md_content or '') > 800:
                    short_md += '\n\n...（内容过长，输入「看图」查看截图）'
                await _send_text(f'📄 题目内容：\n\n{short_md}')
                await _send_text(footer)

            # 切换到 waiting_md 状态，等待用户输入「看图」指令
            step[0] = 'waiting_md'

        except Exception as e:
            logger.error(f'[Luogu jump] 展示题目异常: {traceback.format_exc()}')
            await _send_text(f'❌ 展示题目出错：{e}')

    async def _render_and_send_screenshot():
        """
        渲染 Markdown 为图片并发送。
        使用题目的 HTML 内容直接截图。
        """
        nonlocal fetcher
        try:
            pid = state.get('current_pid')
            if not pid:
                await _send_text('❌ 没有可渲染的题目')
                return

            def _do_screenshot():
                # 重新访问题目页面并截图
                fetcher.page.goto(f'https://www.luogu.com.cn/problem/{pid}', timeout=20000)
                fetcher.page.wait_for_load_state('domcontentloaded', timeout=15000)
                import time as _time; _time.sleep(1.5)
                img_bytes = fetcher.screenshot_problem(pid)
                return img_bytes

            img_bytes = await _run_in_pw(_do_screenshot)
            img_path = _ensure_image_path(img_bytes) if img_bytes else None

            if img_path:
                await _send_text('🖼️ 正在渲染题面图片...')
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
        s = step[0]

        # ── 全局命令 ──────────────────────────────────────────────
        if lower in ('quit', '退出', 'exit', 'q', '算了'):
            await _send_text('✅ 已退出题库跳转，下次见！')
            controller.stop()
            return

        if lower in ('help', '帮助', '?'):
            await _send_text(
                "📖 题库跳转帮助：\n\n"
                "  数字 0-7   → 选择难度\n"
                "  +标签      → 添加标签（支持模糊匹配）\n"
                "  -标签      → 移除标签\n"
                "  done       → 确认标签，进入下一步\n"
                "  skip       → 跳过当前步骤\n"
                "  random     → 随机选题\n"
                "  看图/截图  → 渲染题目图片（显示题面）\n"
                "  back       → 返回上一步\n"
                "  quit       → 退出"
            )
            controller.keep(timeout=180, reset_timeout=True)
            return

        # ══════════════════════════════════════════════════════════
        # Step 1：难度选择
        # ══════════════════════════════════════════════════════════
        if s == 'difficulty':
            if lower in ('help', '?'):
                await _send_text(_JUMP_STEP_TEXT['difficulty'])
                controller.keep(timeout=180, reset_timeout=True)
                return

            if text.isdigit():
                d = int(text)
                if 0 <= d <= 8:
                    state['difficulty'] = d if d > 0 else None
                    # 用户选项 1→DIFFICULTY_NAMES[0]=暂无评定，2→DIFFICULTY_NAMES[1]=入门...
                    diff_name = DIFFICULTY_NAMES[d - 1] if d > 0 else '不限'
                    await _send_text(f'✅ 已选择难度：{diff_name}')
                    step[0] = 'tags'
                    await _show_current_step()
                    controller.keep(timeout=180, reset_timeout=True)
                    return

            await _send_text('❓ 请输入数字 0-7 选择难度')
            controller.keep(timeout=180, reset_timeout=True)
            return

        # ══════════════════════════════════════════════════════════
        # Step 2：标签筛选（多轮）
        # ══════════════════════════════════════════════════════════
        if s == 'tags':
            if lower == 'done':
                step[0] = 'keyword'
                await _show_current_step()
                controller.keep(timeout=180, reset_timeout=True)
                return

            if lower in ('skip', '跳过'):
                step[0] = 'keyword'
                await _show_current_step()
                controller.keep(timeout=180, reset_timeout=True)
                return

            # +标签
            if text.startswith('+'):
                tag_name = text[1:].strip()
                if not tag_name:
                    await _send_text('❓ 请输入标签名，如 +动规')
                    controller.keep(timeout=180, reset_timeout=True)
                    return

                matched = fuzzy_match_tag(tag_name)
                if matched:
                    tag_full = matched[0]
                    if tag_full in state['tags']:
                        await _send_text(f'「{tag_full}」已在已选列表中')
                    else:
                        state['tags'].append(tag_full)
                        await _send_text(f'✅ 已添加：「{tag_full}」')
                else:
                    if tag_name in state['tags']:
                        await _send_text(f'「{tag_name}」已在已选列表中')
                    else:
                        state['tags'].append(tag_name)
                        await _send_text(f'✅ 已添加：「{tag_name}」（未匹配到精确标签）')

                await _send_text(f'当前已选标签：{_jump_tags_str(state)}')
                controller.keep(timeout=180, reset_timeout=True)
                return

            # -标签
            if text.startswith('-'):
                tag_name = text[1:].strip()
                if tag_name in state['tags']:
                    state['tags'].remove(tag_name)
                    await _send_text(f'✅ 已移除：「{tag_name}」')
                else:
                    await _send_text(f'「{tag_name}」不在已选列表中')
                await _send_text(f'当前已选标签：{_jump_tags_str(state)}')
                controller.keep(timeout=180, reset_timeout=True)
                return

            if lower in ('list', '状态', '当前'):
                await _send_text(_JUMP_STEP_TEXT['tags'].format(
                    current_tags=_jump_tags_str(state) or '（无）'
                ))
                controller.keep(timeout=180, reset_timeout=True)
                return

            await _send_text(
                f'❓ 无法理解输入\n'
                f'当前已选标签：{_jump_tags_str(state)}\n\n'
                f'输入 +标签 添加，-标签 移除，done 确认'
            )
            controller.keep(timeout=180, reset_timeout=True)
            return

        # ══════════════════════════════════════════════════════════
        # Step 3：关键词（可选）
        # ══════════════════════════════════════════════════════════
        if s == 'keyword':
            if lower in ('skip', '跳过', '无'):
                state['keyword'] = None
                await _send_text('✅ 跳过关键词筛选')
            elif text:
                state['keyword'] = text
                await _send_text(f'✅ 已设置关键词：「{text}」')
            else:
                state['keyword'] = None
                await _send_text('✅ 未输入关键词，跳过')

            await _send_text('🔍 正在应用筛选条件，请稍候...')
            ok = await _apply_filters()
            if not ok:
                controller.keep(timeout=180, reset_timeout=True)
                return

            if state['total'] == 0:
                await _send_text(
                    f'🔍 未找到符合条件的题目\n'
                    f'难度：{_jump_diff_str(state)} | 标签：{_jump_tags_str(state)}\n\n'
                    f'输入 back-tags 返回修改标签\n'
                    f'输入 back-diff 重新开始所有筛选\n'
                    f'输入 quit 退出'
                )
                step[0] = 'result'
            else:
                step[0] = 'result'
                await _show_current_step()
            controller.keep(timeout=180, reset_timeout=True)
            return

        # ══════════════════════════════════════════════════════════
        # Step 4：选题
        # ══════════════════════════════════════════════════════════
        if s == 'result':
            if state['total'] == 0:
                if lower == 'back-diff':
                    state['difficulty'] = None
                    state['tags'] = []
                    state['keyword'] = None
                    state['total'] = 0
                    step[0] = 'difficulty'
                    await _send_text('← 重置所有条件，返回难度筛选步骤')
                    await _send_text(_JUMP_STEP_TEXT['difficulty'])
                    controller.keep(timeout=180, reset_timeout=True)
                    return
                await _send_text('输入 back-diff 重新开始，quit 退出')
                controller.keep(timeout=180, reset_timeout=True)
                return

            if lower in ('random', 'r', '随机', 'rand'):
                import random as _rand
                pos = _rand.randint(1, state['total'])
                await _send_text(f'🎲 随机选题（第 {pos} / {state["total"]}）')
                await _show_problem(pos)
                controller.keep(timeout=180, reset_timeout=True)
                return

            if lower == 'back-diff':
                state['difficulty'] = None
                state['tags'] = []
                state['keyword'] = None
                state['total'] = 0
                step[0] = 'difficulty'
                await _send_text('← 重置所有条件，返回难度筛选步骤')
                await _send_text(_JUMP_STEP_TEXT['difficulty'])
                controller.keep(timeout=180, reset_timeout=True)
                return

            if lower in ('back-tags', 'back-keyword', 'back'):
                state['keyword'] = None
                state['total'] = 0
                step[0] = 'keyword'
                await _send_text('← 返回关键词筛选步骤（保留难度和标签）')
                await _show_current_step()
                controller.keep(timeout=180, reset_timeout=True)
                return

            if text.isdigit():
                pos = int(text)
                if 1 <= pos <= state['total']:
                    await _show_problem(pos)
                    controller.keep(timeout=180, reset_timeout=True)
                    return
                else:
                    await _send_text(f'⚠️ 序号超出范围，请输入 1-{state["total"]}')
                    controller.keep(timeout=180, reset_timeout=True)
                    return

            await _show_current_step()
            controller.keep(timeout=180, reset_timeout=True)
            return

        # ══════════════════════════════════════════════════════════
        # waiting_md 状态：等待用户输入「看图」指令
        # ══════════════════════════════════════════════════════════
        if s == 'waiting_md':
            # 「看图」或「截图」指令 - 渲染并发送图片
            if lower in ('看图', '截图', 'render', 'img', 'image', '图片', 'screenshot'):
                await _send_text('🖼️ 正在渲染题面图片，请稍候...')
                await _render_and_send_screenshot()
                step[0] = 'result'
                controller.keep(timeout=180, reset_timeout=True)
                return

            # 继续随机下一题
            if lower in ('random', 'r', '随机', 'rand'):
                import random as _rand
                pos = _rand.randint(1, state['total'])
                await _send_text(f'🎲 随机选题（第 {pos} / {state["total"]}）')
                await _show_problem(pos)
                controller.keep(timeout=180, reset_timeout=True)
                return

            # 返回选题
            if lower in ('back', 'back-tags', 'back-keyword'):
                state['keyword'] = None
                state['total'] = 0
                state['showed_md'] = False
                step[0] = 'keyword'
                await _send_text('← 返回关键词筛选步骤（保留难度和标签）')
                await _show_current_step()
                controller.keep(timeout=180, reset_timeout=True)
                return

            if lower == 'back-diff':
                state['difficulty'] = None
                state['tags'] = []
                state['keyword'] = None
                state['total'] = 0
                state['showed_md'] = False
                step[0] = 'difficulty'
                await _send_text('← 重置所有条件，返回难度筛选步骤')
                await _send_text(_JUMP_STEP_TEXT['difficulty'])
                controller.keep(timeout=180, reset_timeout=True)
                return

            if lower in ('quit', '退出', 'exit', 'q', '算了'):
                await _send_text('✅ 已退出题库跳转，下次见！')
                controller.stop()
                return

            # 其他输入 - 切换回 result 状态继续处理
            step[0] = 'result'
            controller.keep(timeout=180, reset_timeout=True)
            return

    try:
        await _send_text(_JUMP_STEP_TEXT['difficulty'])
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
            logger.info('[LuoguPlugin] 插件已加载')

        # ── /luogu ────────────────────────────────────────────

        @filter.command("luogu")
        async def cmd_luogu(self, event: AstrMessageEvent):
            args = event.message_str.strip().split()
            sub = args[1].lower() if len(args) > 1 else 'help'
            qq_id = str(event.get_sender_id())

            if sub == 'help':
                yield event.plain_result(HELP_TEXT)
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
            cfile = str(_cookies_path(qq_id))
            if not Path(cfile).exists():
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
                if not Path(cfile).exists():
                    yield event.plain_result("请先用 /luogu bind 绑定账号")
                    return
                async for result in _jump_session_flow(event, cfile):
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

            yield event.plain_result(HELP_TEXT)


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
