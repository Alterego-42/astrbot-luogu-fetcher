"""
洛谷数据提取核心模块
整合所有页面数据提取逻辑
"""
import re
import json
import time
import os
import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from playwright.sync_api import sync_playwright, Page


# 难度映射
DIFFICULTY_MAP = {
    0: '暂无评定', 1: '入门', 2: '普及−', 3: '普及/提高−',
    4: '普及+/提高', 5: '提高+/省选−', 6: '省选/NOI−', 7: 'NOI/NOI+/CTSC'
}


def _extract_injected_data(html: str) -> Optional[Dict]:
    """
    提取洛谷页面内嵌的 JSON 数据（位于第二个 <script> 块中）。
    格式: {"instance":"main","template":"user.show","data":{...}}
    """
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
    for s in scripts:
        s = s.strip()
        if s.startswith('{') and '"instance"' in s and '"data"' in s:
            try:
                return json.loads(s)
            except Exception:
                pass
    return None


def _extract_json_array(html: str, key: str) -> List[Dict]:
    """
    从 HTML 文本中提取指定 key 的 JSON 数组。
    使用括号配对解析，避免截断。
    """
    key_pos = html.find(f'"{key}":')
    if key_pos < 0:
        return []

    arr_start = html.find('[', key_pos)
    if arr_start < 0:
        return []

    depth = 0
    in_string = False
    escape = False
    i = arr_start

    while i < len(html):
        c = html[i]
        if escape:
            escape = False
        elif c == '\\':
            escape = True
        elif c == '"':
            in_string = not in_string
        elif not in_string:
            if c == '[':
                depth += 1
            elif c == ']':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(html[arr_start:i + 1])
                    except Exception:
                        return []
        i += 1
    return []


def _extract_profile_stats_from_html(html: str) -> Dict:
    """
    从主页 HTML 提取统计数字。
    优先从内嵌 JSON（Script[1]）提取，正则兜底。
    同时提取热度图数据（dailyCounts）和等级分趋势（elo）。
    """
    stats = {
        'name': None,
        'passed': 0, 'submitted': 0,
        'rating': 0,   # 等级分（最新 elo rating）
        'csr': 0,      # 咕值总分
        'rank': None,  # 等级分排名
        'contests': 0, # 评定比赛数
        # 热度图：{date_str: [提交次数, 当天新通过题数]}
        'daily_counts': {},
        # 等级分趋势：[{date, rating, change, contest}]
        'elo_history': [],
        # 咕值构成
        'guzhi_detail': {
            'total': 0,
            'rating': 0,    # 比赛Rating
            'solving': 0,   # 解题
            'difficulty': 0,# 难度
            'community': 0,# 社区
        },
        # 评定比赛列表（名称）
        'contest_names': [],
    }

    # ── 优先：从内嵌 JSON 提取 ──
    injected = _extract_injected_data(html)
    if injected:
        data = injected.get('data', {})
        user = data.get('user', {})

        if user:
            stats['name']      = user.get('name')
            stats['passed']    = user.get('passedProblemCount', 0)
            stats['submitted'] = user.get('submittedProblemCount', 0)
            stats['rank']      = str(user.get('ranking')) if user.get('ranking') else None

        # 咕值（完整结构）
        gu = data.get('gu', {})
        if gu:
            stats['csr'] = gu.get('rating', 0)
            scores = gu.get('scores', {})
            stats['guzhi_detail'] = {
                'total': gu.get('rating', 0),     # 总咕值
                'basic': scores.get('basic', 0),  # 基础信用
                'practice': scores.get('practice', 0),  # 练习情况
                'contest': scores.get('contest', 0),    # 比赛情况
                'social': scores.get('social', 0),  # 社区贡献
                'prize': scores.get('prize', 0),   # 获得成就
            }

        # 等级分：elo 数组第一条（latest=true）的 rating
        elo_arr = data.get('elo', [])
        for item in elo_arr:
            if item.get('latest') and item.get('rating'):
                stats['rating'] = item['rating']
                break
        if not stats['rating'] and elo_arr:
            stats['rating'] = elo_arr[0].get('rating', 0)

        # 评定比赛数 = elo 数组中 rating > 0 的条目数
        stats['contests'] = sum(1 for e in elo_arr if e.get('rating', 0) > 0)

        # 热度图数据
        daily = data.get('dailyCounts', {})
        if daily:
            stats['daily_counts'] = daily  # {date: [submit_count, new_passed]}

        # 等级分历史（供趋势图使用）
        history = []
        contest_names = []
        for item in elo_arr:
            t = item.get('time', 0)
            dt = datetime.datetime.fromtimestamp(t).strftime('%Y-%m-%d') if t else ''
            contest = item.get('contest', {}) or {}
            contest_name = contest.get('name', '') if isinstance(contest, dict) else ''
            if contest_name:
                contest_names.append(contest_name)
            history.append({
                'date':    dt,
                'rating':  item.get('rating', 0),
                'change':  item.get('prevDiff', 0),
                'contest': contest_name,
            })
        stats['elo_history'] = history
        stats['contest_names'] = contest_names

        return stats

    # ── 兜底：正则提取 ──
    title_m = re.search(r'<title>([^-<]+?)\s*[-–]\s*个人中心', html)
    if title_m:
        stats['name'] = title_m.group(1).strip()

    json_fields = {
        'passed':             (r'"passedProblemCount"\s*:\s*(\d+)', int),
        'submitted':          (r'"submittedProblemCount"\s*:\s*(\d+)', int),
        'csr':                (r'"rating"\s*:\s*(\d+)', int),
        'rank':               (r'"ranking"\s*:\s*(\d+)', str),
        'ratingContestCount': (r'"ratingContestCount"\s*:\s*(\d+)', int),
    }
    for key, (pattern, cast) in json_fields.items():
        m = re.search(pattern, html)
        if m:
            try:
                val = cast(m.group(1))
                if key == 'ratingContestCount':
                    stats['contests'] = val
                else:
                    stats[key] = val
            except (ValueError, UnicodeDecodeError):
                pass

    elo_m = re.search(r'"elo"\s*:\s*\[({[^}]+})', html)
    if elo_m:
        try:
            elo_obj = json.loads(elo_m.group(1))
            stats['rating'] = elo_obj.get('rating', 0)
        except Exception:
            r_m = re.search(r'"elo"\s*:\s*\[.*?"rating"\s*:\s*(\d+)', html)
            if r_m:
                stats['rating'] = int(r_m.group(1))

    return stats




def _extract_practice_data_from_html(html: str) -> Dict:
    """
    从练习页 HTML 提取完整数据：
    - passed: 已通过的题目列表（含难度）
    - submitted: 尝试过但未通过的题目列表（含难度）
    - difficulty_stats: 尝试过的题目按难度统计
    - 热度图所需的最大难度映射
    """
    passed = _extract_json_array(html, 'passed')
    submitted = _extract_json_array(html, 'submitted')

    passed_pids = {p['pid'] for p in passed}

    # 纯文本提取难度统计（各难度尝试过的总数）
    text = re.sub(r'<[^>]+>', '\n', html)
    text = re.sub(r'\n+', '\n', text)

    difficulty_order = [
        '暂无评定', '入门', '普及−', '普及/提高−', '普及+/提高',
        '提高+/省选−', '省选/NOI−', 'NOI/NOI+/CTSC'
    ]
    difficulty_stats = {}
    for diff in difficulty_order:
        m = re.search(diff + r'[^\d]*?(\d+)题', text)
        if m:
            difficulty_stats[diff] = int(m.group(1))

    # 已通过题目按难度分类（含题号）
    passed_by_diff: Dict[str, List[str]] = {}
    passed_problem_details = []  # [{pid, difficulty, difficulty_name}]
    for p in passed:
        diff_level = p.get('difficulty', 0)
        diff_name = DIFFICULTY_MAP.get(diff_level, '未知')
        pid = p['pid']
        passed_by_diff.setdefault(diff_name, []).append(pid)
        passed_problem_details.append({
            'pid': pid,
            'difficulty': diff_level,
            'difficulty_name': diff_name,
            'passed': True,
        })

    # 未通过题目按难度分类（含题号）
    unpassed_by_diff: Dict[str, List[str]] = {}
    unpassed_problem_details = []  # [{pid, difficulty, difficulty_name}]
    for p in submitted:
        diff_level = p.get('difficulty', 0)
        diff_name = DIFFICULTY_MAP.get(diff_level, '未知')
        pid = p['pid']
        unpassed_by_diff.setdefault(diff_name, []).append(pid)
        unpassed_problem_details.append({
            'pid': pid,
            'difficulty': diff_level,
            'difficulty_name': diff_name,
            'passed': False,
        })

    # 所有做过题目的详情（用于生成最大难度映射等）
    all_problem_details = passed_problem_details + unpassed_problem_details

    return {
        'total_passed': len(passed),
        'total_unpassed': len(submitted),
        'total_submitted': len(passed) + len(submitted),
        # 具体题号列表
        'passed_problems': [p['pid'] for p in passed],
        'unpassed_problems': [p['pid'] for p in submitted],
        # 按难度分类的题号
        'passed_by_difficulty': passed_by_diff,
        'unpassed_by_difficulty': unpassed_by_diff,
        # 难度统计
        'difficulty_stats': difficulty_stats,
        # 详细题目信息
        'passed_details': passed_problem_details,
        'unpassed_details': unpassed_problem_details,
        'all_problems': all_problem_details,
    }


class LuoguDataFetcher:
    """洛谷数据提取器（基于 Playwright）"""

    def __init__(self, cookies_file: str, user_id: str = None, headless: bool = True):
        self.cookies_file = cookies_file
        self.user_id = user_id
        self.headless = headless
        self.browser = None
        self.context = None
        self.page: Optional[Page] = None
        self._playwright = None

    # ── 生命周期 ──────────────────────────────────────────────

    def setup(self) -> 'LuoguDataFetcher':
        self._playwright = sync_playwright().start()
        self.browser = self._playwright.chromium.launch(headless=self.headless)
        self.context = self.browser.new_context()
        self._load_cookies()
        self.page = self.context.new_page()
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

    # ── 工具 ──────────────────────────────────────────────────

    def _load_cookies(self):
        """加载 cookies 到浏览器 context"""
        if not Path(self.cookies_file).exists():
            return
        with open(self.cookies_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for cookie in data.get('cookies', []):
            try:
                self.context.add_cookies([cookie])
            except Exception:
                pass

    def _get_uid(self) -> Optional[str]:
        """获取当前登录用户的 UID（优先使用构造时传入的）"""
        if self.user_id:
            return self.user_id

        # ① 从 cookies 文件直接读取 _uid / __uid cookie
        try:
            with open(self.cookies_file, 'r', encoding='utf-8') as _f:
                _cd = json.load(_f)
            _cookies_list = _cd.get('cookies', _cd) if isinstance(_cd, dict) else _cd
            if isinstance(_cookies_list, list):
                for c in _cookies_list:
                    cname = c.get('name', '')
                    if cname in ('_uid', '__uid', 'uid'):
                        uid = str(c.get('value', '')).strip()
                        if uid.isdigit():
                            self.user_id = uid
                            return uid
        except Exception:
            pass

        # ② 从 uid 缓存文件读取
        uid_file = self.cookies_file.replace('.json', '_uid.txt')
        if os.path.exists(uid_file):
            uid = Path(uid_file).read_text().strip()
            if uid.isdigit():
                self.user_id = uid
                return uid

        # ③ 从 API 获取（需要有效登录态）
        for api_url in [
            'https://www.luogu.com.cn/fe/api/user/current',
            'https://www.luogu.com.cn/api/user/currentUser',
        ]:
            try:
                resp = self.page.request.get(
                    api_url,
                    headers={'x-luogu-type': 'content-only'}
                )
                if resp.ok:
                    data = resp.json()
                    uid = str(
                        (data.get('currentUser') or {}).get('uid') or
                        data.get('uid') or ''
                    )
                    if uid.isdigit():
                        self.user_id = uid
                        Path(uid_file).write_text(uid)
                        return uid
            except Exception:
                pass

        # ④ 通过个人主页 URL 重定向获取 UID
        self.page.goto('https://www.luogu.com.cn/user', timeout=15000)
        self.page.wait_for_load_state('networkidle')
        url = self.page.url
        m = re.search(r'/user/(\d+)', url)
        if m:
            uid = m.group(1)
            self.user_id = uid
            Path(uid_file).write_text(uid)
            return uid

        return None

    def _save_html(self, prefix: str):
        """保存当前页面 HTML，用于调试"""
        html = self.page.content()
        os.makedirs('screenshots', exist_ok=True)
        with open(f'screenshots/{prefix}_main.html', 'w', encoding='utf-8') as f:
            f.write(html)

    # ── 打卡 ──────────────────────────────────────────────────

    def checkin(self) -> Dict:
        """
        执行打卡。
        返回:
          {
            'success': bool,
            'message': str,
            'already_checked': bool,
            'streak': int,      # 连续打卡天数（已打卡时有值）
            'fortune': str,     # 今日运势文字
          }
        """
        self.page.goto('https://www.luogu.com.cn/', timeout=15000)
        self.page.wait_for_load_state('networkidle')
        time.sleep(2)

        html = self.page.content()

        # ── 检查是否已打卡（页面显示"运势"则已打卡）──
        # 已打卡时：.lg-punch 内出现 lg-punch-result，没有 name=punch 按钮
        if 'lg-punch-result' in html:
            streak = 0
            streak_m = re.search(r'连续打卡了?\s*[^\d]*?(\d+)\s*天', html)
            if streak_m:
                streak = int(streak_m.group(1))

            fortune_m = re.search(r'lg-punch-result[^>]*>([^<]+)<', html)
            fortune = fortune_m.group(1).strip() if fortune_m else ''

            return {
                'success': True,
                'message': f'今日已打卡，连续打卡 {streak} 天',
                'already_checked': True,
                'streak': streak,
                'fortune': fortune,
            }

        # ── 未打卡：找按钮并点击 ──
        btn = (
            self.page.query_selector('a[name="punch"]') or
            self.page.query_selector('.am-btn-warning[title]') or
            self.page.query_selector('a:has-text("点击打卡")')
        )

        if not btn:
            return {
                'success': False,
                'message': '未找到打卡按钮',
                'already_checked': False,
                'streak': 0,
                'fortune': '',
            }

        btn.click()
        time.sleep(3)

        # 点击后重新检查
        html_after = self.page.content()
        if 'lg-punch-result' in html_after:
            streak = 0
            streak_m = re.search(r'连续打卡了?\s*[^\d]*?(\d+)\s*天', html_after)
            if streak_m:
                streak = int(streak_m.group(1))

            fortune_m = re.search(r'lg-punch-result[^>]*>([^<]+)<', html_after)
            fortune = fortune_m.group(1).strip() if fortune_m else ''

            return {
                'success': True,
                'message': f'打卡成功！连续打卡 {streak} 天',
                'already_checked': False,
                'streak': streak,
                'fortune': fortune,
            }

        return {
            'success': True,
            'message': '打卡操作已执行',
            'already_checked': False,
            'streak': 0,
            'fortune': '',
        }



    # ── 主页数据 ──────────────────────────────────────────────

    def fetch_profile_stats(self) -> Dict:
        """获取个人主页统计数据"""
        uid = self._get_uid()
        if not uid:
            return {}

        self.page.goto(f'https://www.luogu.com.cn/user/{uid}', timeout=15000)
        self.page.wait_for_load_state('networkidle')
        time.sleep(2)

        html = self.page.content()
        self._save_html('profile')

        stats = _extract_profile_stats_from_html(html)
        stats['uid'] = uid

        # 尝试从 API 补充数据
        api_stats = self._fetch_profile_api(uid)
        stats.update({k: v for k, v in api_stats.items() if v})

        return stats

    def _fetch_profile_api(self, uid: str) -> Dict:
        """通过 API 获取主页数据（更精准），补充 HTML 提取的数据"""
        try:
            resp = self.page.request.get(
                f'https://www.luogu.com.cn/user/{uid}',
                headers={'x-luogu-type': 'content-only'}
            )
            if resp.ok:
                data = resp.json()
                d = data.get('currentData', {}) or data.get('data', {})
                user = d.get('user', {})
                if user:
                    result = {
                        'uid':       str(user.get('uid', uid)),
                        'name':      user.get('name'),
                        'passed':    user.get('passedProblemCount', 0),
                        'submitted': user.get('submittedProblemCount', 0),
                        'rank':      str(user.get('ranking')) if user.get('ranking') else None,
                    }
                    # elo 数据
                    elo_arr = d.get('elo', [])
                    if elo_arr:
                        for item in elo_arr:
                            if item.get('latest') and item.get('rating'):
                                result['rating'] = item['rating']
                                break
                        result['contests'] = sum(1 for e in elo_arr if e.get('rating', 0) > 0)
                    # 咕值
                    gu = d.get('gu', {})
                    if gu:
                        result['csr'] = gu.get('rating', 0)
                    return result
        except Exception:
            pass
        return {}



    # ── 练习数据 ──────────────────────────────────────────────

    def fetch_practice_data(self) -> Dict:
        """获取练习情况标签页数据"""
        uid = self._get_uid()
        if not uid:
            return {}

        self.page.goto(
            f'https://www.luogu.com.cn/user/{uid}/practice',
            timeout=15000
        )
        self.page.wait_for_load_state('networkidle')
        time.sleep(2)

        html = self.page.content()
        self._save_html('practice')

        return _extract_practice_data_from_html(html)

    # ── 获取全部 ──────────────────────────────────────────────

    def fetch_all(self) -> Dict:
        """一次性获取所有数据"""
        uid = self._get_uid()
        return {
            'uid': uid,
            'profile': self.fetch_profile_stats(),
            'practice': self.fetch_practice_data(),
        }


# ── 便捷函数 ──────────────────────────────────────────────────

def fetch_user_data(cookies_file: str, user_id: str = None) -> Dict:
    with LuoguDataFetcher(cookies_file, user_id) as fetcher:
        return fetcher.fetch_all()


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')

    cookies_file = sys.argv[1] if len(sys.argv) > 1 else 'cookies/cookies_19738806113.json'

    print('获取洛谷用户数据...')
    data = fetch_user_data(cookies_file)

    print('\n=== 个人主页统计 ===')
    p = data.get('profile', {})
    print(f"  UID:   {p.get('uid')}")
    print(f"  用户名: {p.get('name')}")
    print(f"  通过:  {p.get('passed')} 题")
    print(f"  提交:  {p.get('submitted')} 次")
    print(f"  等级分:{p.get('rating')}")
    print(f"  咕值:  {p.get('csr')}")
    print(f"  排名:  #{p.get('rank')}")
    print(f"  评定比赛: {p.get('contests')}")

    print('\n=== 练习数据 ===')
    pr = data.get('practice', {})
    print(f"  已通过: {pr.get('total_passed')} 题")
    print(f"  未通过: {pr.get('total_unpassed')} 题")
    for diff, pids in pr.get('passed_by_difficulty', {}).items():
        print(f"    {diff}: {len(pids)} 题")

    with open('user_complete_data.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print('\n已保存到 user_complete_data.json')
