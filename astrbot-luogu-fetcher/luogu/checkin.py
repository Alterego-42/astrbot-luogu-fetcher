"""洛谷打卡模块"""
import sys
sys.path.insert(0, '.')

from playwright.sync_api import sync_playwright
import json
import time
from pathlib import Path

class LuoguCheckin:
    """洛谷打卡功能"""
    
    def __init__(self, cookies_file: str = None, cookies_data: list = None):
        """
        初始化打卡模块
        
        Args:
            cookies_file: cookies JSON文件路径
            cookies_data: 直接传入cookies列表
        """
        self.browser = None
        self.context = None
        self.page = None
        self.cookies = cookies_data
        
        if cookies_file and not cookies_data:
            with open(cookies_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.cookies = data['cookies']
    
    def setup(self):
        """初始化浏览器"""
        self.browser = sync_playwright().start().chromium.launch(headless=False)
        self.context = self.browser.new_context()
        
        if self.cookies:
            for cookie in self.cookies:
                self.context.add_cookies([cookie])
        
        self.page = self.context.new_page()
        return self
    
    def checkin(self) -> dict:
        """
        执行打卡
        
        Returns:
            dict: {'success': bool, 'message': str, 'already_checked_in': bool}
        """
        if not self.page:
            self.setup()
        
        # 访问首页
        self.page.goto('https://www.luogu.com.cn/', timeout=15000)
        self.page.wait_for_load_state('networkidle')
        time.sleep(2)
        
        # 查找打卡按钮
        checkin_btn = self.page.query_selector('a[name="punch"]')
        if not checkin_btn:
            checkin_btn = self.page.query_selector('a:has-text("点击打卡")')
        if not checkin_btn:
            checkin_btn = self.page.query_selector('.am-btn-warning')
        
        if not checkin_btn:
            return {
                'success': False,
                'message': '未找到打卡按钮',
                'already_checked_in': False
            }
        
        # 获取打卡前状态
        btn_text_before = checkin_btn.inner_text()
        
        # 检查是否已打卡
        if '已打卡' in btn_text_before or '打卡成功' in btn_text_before:
            return {
                'success': True,
                'message': '今日已打卡',
                'already_checked_in': True
            }
        
        # 点击打卡
        checkin_btn.click()
        time.sleep(3)
        
        # 截图记录
        self.page.screenshot(path='screenshots/checkin_result.png')
        
        # 检查打卡结果
        checkin_btn_after = self.page.query_selector('a[name="punch"]')
        btn_text_after = checkin_btn_after.inner_text() if checkin_btn_after else ''
        
        if '已打卡' in btn_text_after or '打卡成功' in btn_text_after or '已打卡' not in btn_text_before:
            return {
                'success': True,
                'message': '打卡成功',
                'already_checked_in': False
            }
        
        return {
            'success': False,
            'message': f'打卡失败，按钮状态: {btn_text_after}',
            'already_checked_in': False
        }
    
    def close(self):
        """关闭浏览器"""
        if self.browser:
            self.browser.close()
            sync_playwright().stop()
    
    def __enter__(self):
        return self.setup()
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


def checkin_with_cookies(cookies_file: str) -> dict:
    """
    便捷函数：使用cookies文件打卡
    
    Args:
        cookies_file: cookies JSON文件路径
    
    Returns:
        dict: {'success': bool, 'message': str, 'already_checked_in': bool}
    """
    with LuoguCheckin(cookies_file=cookies_file) as checkin:
        return checkin.checkin()


if __name__ == '__main__':
    # 测试打卡
    cookies_file = 'cookies/cookies_19738806113.json'
    
    print('=' * 50)
    print('洛谷打卡测试')
    print('=' * 50)
    
    result = checkin_with_cookies(cookies_file)
    
    print(f"\n结果: {result['message']}")
    print(f"今日是否已打卡: {result['already_checked_in']}")
    print(f"是否成功: {result['success']}")
    
    print("\n截图已保存: screenshots/checkin_result.png")
    
    input('按回车键关闭...')
