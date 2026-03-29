"""
洛谷数据存储模块

功能：
1. 存储用户账号信息
2. 存储cookies
3. 存储用户数据（做题记录、咕值等）
4. 定时更新数据
"""

import json
import os
import time
from datetime import datetime
from typing import Dict, Any, List, Optional

class LuoguDataStorage:
    """洛谷数据存储类"""
    
    def __init__(self, storage_dir: str = "./luogu_data"):
        self.storage_dir = storage_dir
        self._ensure_storage_dir()
    
    def _ensure_storage_dir(self):
        """确保存储目录存在"""
        if not os.path.exists(self.storage_dir):
            os.makedirs(self.storage_dir)
    
    def _get_user_dir(self, uid: str) -> str:
        """获取用户数据目录"""
        user_dir = os.path.join(self.storage_dir, f"user_{uid}")
        if not os.path.exists(user_dir):
            os.makedirs(user_dir)
        return user_dir
    
    def save_account(self, uid: str, username: str, password: str = ""):
        """保存用户账号信息"""
        user_dir = self._get_user_dir(uid)
        account_file = os.path.join(user_dir, "account.json")
        
        account_data = {
            "uid": uid,
            "username": username,
            "password": password,  # 实际应用中应加密存储
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        
        with open(account_file, "w", encoding="utf-8") as f:
            json.dump(account_data, f, ensure_ascii=False, indent=2)
        
        print(f"账号信息已保存: {account_file}")
    
    def load_account(self, uid: str) -> Optional[Dict[str, Any]]:
        """加载用户账号信息"""
        user_dir = self._get_user_dir(uid)
        account_file = os.path.join(user_dir, "account.json")
        
        if not os.path.exists(account_file):
            return None
        
        try:
            with open(account_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"加载账号信息失败: {e}")
            return None
    
    def save_cookies(self, uid: str, cookies: Dict[str, str]):
        """保存cookies"""
        user_dir = self._get_user_dir(uid)
        cookies_file = os.path.join(user_dir, "cookies.json")
        
        cookies_data = {
            "cookies": cookies,
            "saved_at": datetime.now().isoformat()
        }
        
        with open(cookies_file, "w", encoding="utf-8") as f:
            json.dump(cookies_data, f, ensure_ascii=False, indent=2)
        
        print(f"Cookies已保存: {cookies_file}")
    
    def load_cookies(self, uid: str) -> Optional[Dict[str, str]]:
        """加载cookies"""
        user_dir = self._get_user_dir(uid)
        cookies_file = os.path.join(user_dir, "cookies.json")
        
        if not os.path.exists(cookies_file):
            return None
        
        try:
            with open(cookies_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("cookies")
        except Exception as e:
            print(f"加载Cookies失败: {e}")
            return None
    
    def save_user_data(self, uid: str, data_type: str, data: Any):
        """保存用户数据（做题记录、咕值等）"""
        user_dir = self._get_user_dir(uid)
        data_file = os.path.join(user_dir, f"{data_type}.json")
        
        data_obj = {
            "data": data,
            "updated_at": datetime.now().isoformat()
        }
        
        with open(data_file, "w", encoding="utf-8") as f:
            json.dump(data_obj, f, ensure_ascii=False, indent=2)
        
        print(f"{data_type}数据已保存: {data_file}")
    
    def load_user_data(self, uid: str, data_type: str) -> Optional[Any]:
        """加载用户数据"""
        user_dir = self._get_user_dir(uid)
        data_file = os.path.join(user_dir, f"{data_type}.json")
        
        if not os.path.exists(data_file):
            return None
        
        try:
            with open(data_file, "r", encoding="utf-8") as f:
                data_obj = json.load(f)
                return data_obj.get("data")
        except Exception as e:
            print(f"加载{data_type}数据失败: {e}")
            return None
    
    def save_screenshot(self, uid: str, screenshot_type: str, image_data: bytes):
        """保存截图数据"""
        user_dir = self._get_user_dir(uid)
        screenshot_dir = os.path.join(user_dir, "screenshots")
        
        if not os.path.exists(screenshot_dir):
            os.makedirs(screenshot_dir)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        screenshot_file = os.path.join(
            screenshot_dir, 
            f"{screenshot_type}_{timestamp}.png"
        )
        
        with open(screenshot_file, "wb") as f:
            f.write(image_data)
        
        print(f"截图已保存: {screenshot_file}")
        return screenshot_file
    
    def list_all_users(self) -> List[str]:
        """列出所有已保存的用户"""
        if not os.path.exists(self.storage_dir):
            return []
        
        users = []
        for item in os.listdir(self.storage_dir):
            if item.startswith("user_"):
                uid = item.replace("user_", "")
                users.append(uid)
        
        return users


# 全局存储实例
_storage = None

def get_storage() -> LuoguDataStorage:
    """获取全局存储实例"""
    global _storage
    if _storage is None:
        _storage = LuoguDataStorage()
    return _storage
