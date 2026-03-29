"""
洛谷登录核心功能

实现以下功能：
1. 自动登录洛谷
2. 处理图片验证码
3. 保存cookies
4. 获取个人数据
"""

import requests
import json
import base64
import io
from PIL import Image
from typing import Optional, Dict, Any

# 洛谷API地址
LUOGU_BASE_URL = "https://www.luogu.com.cn"
LUOGU_LOGIN_URL = f"{LUOGU_BASE_URL}/auth/login"
LUOGU_CAPTCHA_URL = f"{LUOGU_BASE_URL}/auth/captcha"

class LuoguLogin:
    """洛谷登录核心类"""
    
    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.cookies = {}
        self.logged_in = False
        self.uid = None
        
    def get_captcha(self) -> Optional[bytes]:
        """获取验证码图片"""
        try:
            response = self.session.get(LUOGU_CAPTCHA_URL)
            if response.status_code == 200:
                return response.content
        except Exception as e:
            print(f"获取验证码失败: {e}")
        return None
    
    def solve_captcha(self, image_data: bytes) -> str:
        """识别验证码（需要ddddocr库）"""
        try:
            import ddddocr
            ocr = ddddocr.DdddOcr()
            result = ocr.classification(image_data)
            return result
        except ImportError:
            print("ddddocr未安装，请运行: pip install ddddocr")
            return ""
        except Exception as e:
            print(f"验证码识别失败: {e}")
            return ""
    
    def login_with_auto_captcha(self) -> bool:
        """自动识别验证码登录"""
        # 1. 获取验证码
        captcha_data = self.get_captcha()
        if not captcha_data:
            print("无法获取验证码")
            return False
        
        # 2. 识别验证码
        captcha_text = self.solve_captcha(captcha_data)
        if not captcha_text:
            print("验证码识别失败")
            return False
        
        # 3. 提交登录
        login_data = {
            "username": self.username,
            "password": self.password,
            "captcha": captcha_text
        }
        
        try:
            response = self.session.post(
                f"{LUOGU_LOGIN_URL}/login",
                json=login_data,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get("code") == 200:
                    self.cookies = self.session.cookies.get_dict()
                    self.logged_in = True
                    self.uid = result.get("uid")
                    print(f"登录成功! UID: {self.uid}")
                    return True
                else:
                    print(f"登录失败: {result.get('msg', '未知错误')}")
                    return False
        except Exception as e:
            print(f"登录请求失败: {e}")
            return False
        
        return False
    
    def login_with_manual_captcha(self, captcha_text: str) -> bool:
        """手动输入验证码登录（用于转发到QQ让用户填写）"""
        login_data = {
            "username": self.username,
            "password": self.password,
            "captcha": captcha_text
        }
        
        try:
            response = self.session.post(
                f"{LUOGU_LOGIN_URL}/login",
                json=login_data,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get("code") == 200:
                    self.cookies = self.session.cookies.get_dict()
                    self.logged_in = True
                    self.uid = result.get("uid")
                    return True
        except Exception as e:
            print(f"登录请求失败: {e}")
        
        return False
    
    def save_cookies(self, filepath: str = "luogu_cookies.json"):
        """保存cookies到文件"""
        if self.cookies:
            with open(filepath, "w") as f:
                json.dump(self.cookies, f)
            print(f"Cookies已保存到: {filepath}")
    
    def load_cookies(self, filepath: str = "luogu_cookies.json") -> bool:
        """从文件加载cookies"""
        try:
            with open(filepath, "r") as f:
                self.cookies = json.load(f)
                # 设置cookies到session
                for key, value in self.cookies.items():
                    self.session.cookies.set(key, value)
                return True
        except FileNotFoundError:
            print("Cookies文件不存在")
            return False
        except Exception as e:
            print(f"加载Cookies失败: {e}")
            return False


class LuoguDataFetcher:
    """洛谷数据获取类"""
    
    def __init__(self, session: requests.Session):
        self.session = session
    
    def get_user_profile(self, uid: str) -> Optional[Dict[str, Any]]:
        """获取用户基本信息"""
        try:
            response = self.session.get(f"{LUOGU_BASE_URL}/user/{uid}")
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"获取用户信息失败: {e}")
        return None
    
    def get_problem_trend(self, uid: str) -> Optional[Dict[str, Any]]:
        """获取做题趋势数据"""
        try:
            response = self.session.get(
                f"{LUOGU_BASE_URL}/fe/api/problem/trend/{uid}"
            )
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"获取做题趋势失败: {e}")
        return None
    
    def get_contest_rating(self, uid: str) -> Optional[Dict[str, Any]]:
        """获取比赛评分趋势"""
        try:
            response = self.session.get(
                f"{LUOGU_BASE_URL}/fe/api/contest/rating/{uid}"
            )
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"获取比赛评分失败: {e}")
        return None
    
    def get_solved_problems(self, uid: str) -> Optional[Dict[str, Any]]:
        """获取已解决的题目列表"""
        try:
            response = self.session.get(
                f"{LUOGU_BASE_URL}/fe/api/problem/solved/{uid}"
            )
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"获取已解决题目失败: {e}")
        return None


if __name__ == "__main__":
    # 测试登录
    print("请输入洛谷账号信息:")
    username = input("用户名/手机号: ")
    password = input("密码: ")
    
    login = LuoguLogin(username, password)
    if login.login_with_auto_captcha():
        print("登录成功!")
        
        # 保存cookies
        login.save_cookies()
        
        # 获取数据
        fetcher = LuoguDataFetcher(login.session)
        profile = fetcher.get_user_profile(login.uid)
        print(f"用户信息: {json.dumps(profile, ensure_ascii=False, indent=2)}")
    else:
        print("登录失败")
