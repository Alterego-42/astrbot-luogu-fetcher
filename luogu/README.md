# 已完成核心功能测试

测试脚本验证了登录和基础数据获取功能。

下一步是实现其他功能模块，让我先创建配置文件来存储账号信息：







<｜DSML｜function_calls>
<｜DSML｜invoke name="write_to_file">
<｜DSML｜parameter name="filePath" string="true">c:/Users/Laptop/WorkBuddy/20260323001240/astrbot_plugin_luogu/luogu/config.      if "=" in line:
                key, value = line.strip().split("=")
                config[key] = value
    return config

def main():
    # 读取配置
    config = test_config()
    login = LuoguLogin(config["username"], config["password"])
    
    if login.login():
        print("登录成功")
        
        # 获取数据测试
        data = login.fetch_data("https://www.luogu.com.cn/record/list")
        print(f"获取的数据: {json.dumps(data, ensure_ascii=False, indent=2)}")
    else:
        print("获取数据失败")

if __name__ == "__main__":
    # 测试登录
    if test_login():
        print("登录测试通过")
    else:
        print("登录测试失败")