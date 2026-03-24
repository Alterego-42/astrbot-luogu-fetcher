"""
洛谷插件配置模块

这个模块用于读取和存储配置信息
"""

import configparser
import os

def test_config():
    """测试配置读取功能"""
    config = configparser.ConfigParser()
    config.read('config.ini')
    
    # 从配置文件读取账号信息
    username = config['luogu']['username']
    password = config['luogu']['password']
    
    print(f"用户名: {username}")
    print(f"密码: {password}")