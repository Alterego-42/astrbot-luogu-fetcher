# AstrBot 洛谷助手插件

一款基于 Playwright 的洛谷（Luogu） AstrBot 插件，支持账号绑定、自动打卡、数据爬取、热度图截图等功能。

## 功能特性

| 指令 | 功能 |
|------|------|
| `/luogu bind <手机号> <密码>` | 绑定洛谷账号 |
| `/luogu info` | 查看个人统计卡片 |
| `/luogu checkin` | 每日打卡 |
| `/luogu heatmap` | 做题热度图（洛谷原版截图） |
| `/luogu elo` | 比赛等级分趋势图 |
| `/luogu practice` | 练习情况（按难度分类） |

### 可获取的数据

- **个人主页**: 用户名、UID、排名、Rating、通过数、提交数、AC率
- **咕值分解**: 基础信用、练习分、比赛分、社区贡献、成就
- **比赛记录**: 评定比赛名称、日期、Rating 变化
- **做题热度**: 52 周每日做题数和最大难度
- **题目列表**: 已通过题目，按难度分类（入门/普及/提高/省选等）

## 安装

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

主要依赖：
- `playwright` - 网页自动化
- `matplotlib` - 图表生成
- `ddddocr` - 验证码识别（可选）

安装 Playwright 浏览器：
```bash
playwright install chromium
```

### 2. 安装插件

将插件目录放入 AstrBot 的 `extensions` 目录：

```
AstrBot/
└── extensions/
    └── astrbot_plugin_luogu/
        ├── main.py
        ├── luogu/
        └── ...
```

### 3. 配置 AstrBot

在 AstrBot 配置文件中注册插件（如果需要）。

## 使用方法

### 绑定账号

私聊发送（保护密码安全）：
```
/luogu bind 你的手机号 你的密码
```

### 查看统计

```
/luogu info
```

返回包含以下内容的统计卡片：
- 通过数 / 提交数 / AC率
- 等级分 (Rating)
- 咕值 (CSR) 及其分解
- 排名

### 每日打卡

```
/luogu checkin
```

返回打卡结果和连续打卡天数。

### 做题热度图

```
/luogu heatmap
```

返回洛谷原版热度图截图，每格颜色代表当天通过的最大难度。

### 等级分趋势

```
/luogu elo
```

返回比赛等级分趋势折线图。

### 练习情况

```
/luogu practice
```

返回按难度分类的已通过题目统计。

## 项目结构

```
astrbot_plugin_luogu/
├── main.py                 # 插件主入口
├── requirements.txt        # 依赖列表
├── .gitignore             # Git 忽略配置
├── metadata.yaml           # 插件元数据
├── luogu/
│   ├── __init__.py
│   ├── data_fetcher.py    # 数据提取模块
│   ├── chart_generator.py # 图表生成模块
│   ├── screenshot.py      # 网页截图模块
│   ├── models.py          # 数据模型
│   ├── checkin.py         # 打卡模块
│   ├── storage.py         # 存储模块
│   └── config.py          # 配置模块
├── cookies/               # 登录 Cookie（不提交到 Git）
│   └── .gitkeep
└── user_data/             # 用户绑定数据（不提交到 Git）
```

## 注意事项

1. **隐私保护**: Cookie 文件包含敏感登录信息，已加入 `.gitignore`，请勿提交到 Git
2. **验证码**: 首次登录可能需要验证码，ddddocr 可以自动识别滑块/点选验证码
3. **Cookie 有效期**: 洛谷 Cookie 有有效期限制，长时间不使用可能需要重新登录

## License

MIT License
