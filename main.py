"""
洛谷助手 AstrBot 插件

指令列表：
  /luogu bind <手机号> <密码>   绑定洛谷账号（通过 Playwright 登录并保存 cookie）
  /luogu info [uid]             查看个人主页统计（统计卡片图片）
  /luogu checkin                每日打卡
  /luogu heatmap                做题热度日历图（近26周）
  /luogu elo                    比赛等级分趋势图
  /luogu practice               查看练习情况（按难度分类通过题数）
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
from pathlib import Path
from typing import Optional, Dict, Any

# ── 路径处理 ──────────────────────────────────────────────────
_PLUGIN_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(_PLUGIN_DIR))

# ── AstrBot 导入（可选，独立运行时不可用） ──────────────────────
try:
    from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
    from astrbot.api.star import Context, Star, register
    from astrbot.api import logger
    _ASTRBOT = True
except ImportError:
    _ASTRBOT = False
    import logging
    logger = logging.getLogger('luogu_plugin')
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s [%(levelname)s] %(message)s')

# ── 插件内部模块 ──────────────────────────────────────────────
from luogu.data_fetcher import LuoguDataFetcher
from luogu.chart_generator import (
    generate_summary_card,
    generate_heatmap,
    generate_elo_trend,
    generate_bar_chart,
)

# ── 常量 ──────────────────────────────────────────────────────
COOKIES_DIR   = _PLUGIN_DIR / 'cookies'
DATA_DIR      = _PLUGIN_DIR / 'user_data'
BIND_FILE     = DATA_DIR / 'bindings.json'    # qq_id -> luogu_uid
COOKIES_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)


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


# ════════════════════════════════════════════════════════════════
# 登录（同步 Playwright，需在线程中运行）
# ════════════════════════════════════════════════════════════════

def _do_login(username: str, password: str, qq_id: str) -> Dict:
    """
    通过 Playwright 登录洛谷，保存 cookies 到文件。
    返回 {'success': bool, 'message': str, 'uid': str|None}
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

            # 4. 处理验证码（最多5次 OCR 或直接点提交）
            captcha_solved = False
            for attempt in range(5):
                # 尝试获取验证码图片
                captcha_img = (
                    page.query_selector('img[src*="captcha"]') or
                    page.query_selector('.captcha-img img') or
                    page.query_selector('img[alt*="验证码"]')
                )

                if captcha_img:
                    try:
                        import ddddocr
                        ocr = ddddocr.DdddOcr(show_ad=False)
                        # 截图验证码区域
                        cap_bytes = captcha_img.screenshot()
                        code = ocr.classification(cap_bytes)
                        logger.info(f'[Luogu] 验证码OCR结果: {code}')

                        cap_input = (
                            page.query_selector('input[placeholder*="验证码"]') or
                            page.query_selector('input[type="text"]:not([placeholder*="用户"])')
                        )
                        if cap_input:
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
                    # 验证码错误则刷新重试
                    if captcha_img:
                        captcha_img.click()
                        time.sleep(0.5)

            if not captcha_solved:
                browser.close()
                return {'success': False, 'message': '登录失败（验证码多次识别错误）', 'uid': None}

            # 登录成功，保存 cookies
            cookies = context.cookies()
            uid = None
            for c in cookies:
                if c.get('name') == '__uid':
                    uid = str(c['value'])
                    break

            # 保存 Playwright 格式的 cookies
            cookie_data = {'cookies': cookies}
            Path(cookies_file).write_text(
                _json.dumps(cookie_data, ensure_ascii=False, indent=2),
                encoding='utf-8'
            )

            # 更新绑定表
            if uid:
                bindings = _load_bindings()
                bindings[qq_id] = uid
                _save_bindings(bindings)
                _uid_file(qq_id).write_text(uid)

            browser.close()
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


HELP_TEXT = """洛谷助手指令：

/luogu bind <手机号> <密码>
  绑定洛谷账号

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
                if len(args) < 4:
                    yield event.plain_result("用法：/luogu bind <手机号> <密码>\n请注意在私聊中使用以保护密码安全")
                    return
                username = args[2]
                password = args[3]
                yield event.plain_result("正在登录洛谷，请稍候（约10~30秒）...")
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, lambda: _do_login(username, password, qq_id))
                if result['success']:
                    uid = result.get('uid', '未知')
                    yield event.plain_result(f"✅ 绑定成功！洛谷 UID：{uid}")
                else:
                    yield event.plain_result(f"❌ 绑定失败：{result['message']}")
                return

            # 以下指令需要先绑定
            cfile = str(_cookies_path(qq_id))
            if not Path(cfile).exists():
                yield event.plain_result("请先用 /luogu bind 绑定账号")
                return

            if sub == 'checkin':
                yield event.plain_result("正在打卡...")
                try:
                    result = await _run_async(cfile, qq_id, _task_checkin)
                    yield event.plain_result(_fmt_checkin(result))
                except Exception as e:
                    logger.error(f'[Luogu] checkin error: {traceback.format_exc()}')
                    yield event.plain_result(f"❌ 打卡出错：{e}")
                return

            if sub == 'info':
                yield event.plain_result("正在获取数据...")
                try:
                    profile = await _run_async(cfile, qq_id, _task_profile)
                    if not profile:
                        yield event.plain_result("❌ 获取数据失败，请检查账号是否有效")
                        return
                    img_bytes = await asyncio.get_event_loop().run_in_executor(None, lambda: generate_summary_card(profile))
                    yield event.image_result(img_bytes)
                except Exception as e:
                    logger.error(f'[Luogu] info error: {traceback.format_exc()}')
                    yield event.plain_result(f"❌ 获取数据出错：{e}")
                return

            if sub == 'heatmap':
                yield event.plain_result("正在生成热度图...")
                try:
                    profile = await _run_async(cfile, qq_id, _task_profile)
                    daily = profile.get('daily_counts', {})
                    username = profile.get('name', '')
                    if not daily:
                        yield event.plain_result("暂无做题热度数据")
                        return
                    img_bytes = await asyncio.get_event_loop().run_in_executor(None, lambda: generate_heatmap(daily, username=username))
                    yield event.image_result(img_bytes)
                except Exception as e:
                    logger.error(f'[Luogu] heatmap error: {traceback.format_exc()}')
                    yield event.plain_result(f"❌ 生成热度图出错：{e}")
                return

            if sub == 'elo':
                yield event.plain_result("正在生成等级分趋势图...")
                try:
                    profile = await _run_async(cfile, qq_id, _task_profile)
                    elo_history = profile.get('elo_history', [])
                    username = profile.get('name', '')
                    if not elo_history:
                        yield event.plain_result("暂无比赛等级分数据")
                        return
                    img_bytes = await asyncio.get_event_loop().run_in_executor(None, lambda: generate_elo_trend(elo_history, username=username))
                    yield event.image_result(img_bytes)
                except Exception as e:
                    logger.error(f'[Luogu] elo error: {traceback.format_exc()}')
                    yield event.plain_result(f"❌ 生成趋势图出错：{e}")
                return

            if sub == 'practice':
                yield event.plain_result("正在获取练习数据...")
                try:
                    practice = await _run_async(cfile, qq_id, _task_practice)
                    text = _fmt_practice(practice)
                    by_diff = practice.get('passed_by_difficulty', {})
                    bar_data = {d: len(pids) for d, pids in by_diff.items() if pids}
                    if bar_data:
                        img_bytes = await asyncio.get_event_loop().run_in_executor(None, lambda: generate_bar_chart(bar_data, title=f"{practice.get('total_passed', 0)} 题按难度分布", ylabel='题数', color='#1890ff'))
                        yield event.plain_result(text)
                        yield event.image_result(img_bytes)
                    else:
                        yield event.plain_result(text)
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
