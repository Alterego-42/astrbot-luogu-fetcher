# AstrBot 洛谷助手插件

一款基于 Playwright 的洛谷（Luogu） AstrBot 插件，支持账号绑定、自动打卡、数据爬取、热度图截图等功能。

## 功能特性

| 指令 | 功能 |
|------|------|
| `/luogu bind <手机号> <密码>` | 绑定洛谷账号（支持 ddddocr 自动识别验证码） |
| `/luogu info` | 查看个人统计卡片 |
| `/luogu info -f` | 强制从洛谷重新拉取数据 |
| `/luogu checkin` | 每日打卡截图 |
| `/luogu heatmap` | 做题热度图（洛谷原版截图） |
| `/luogu elo` | 比赛等级分趋势图 |
| `/luogu practice` | 练习情况（按难度分类） |
| `/luogu practice -f` | 强制重新获取练习数据 |
| `/luogu help` | 显示帮助信息 |

### 可获取的数据

- **个人主页**: 用户名、UID、排名、Rating、通过数、提交数
- **咕值分解**: 基础信用、练习分、比赛分、社区贡献、成就
- **评定比赛**: 参与评定的比赛名称与日期
- **做题热度**: 近 26 周每日做题数和最大难度
- **题目列表**: 已通过题目，按难度分类（暂无评定/入门/普及−/普及/提高−/普及+/提高/提高+/省选−/省选/NOI−/NOI/NOI+/CTSC）

## 安装

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

主要依赖：
- `playwright` - 网页自动化
- `matplotlib` - 图表生成
- `ddddocr` - 验证码识别（可选，未安装时跳过自动识别）

安装 Playwright 浏览器：
```bash
playwright install chromium
```

### 2. 安装插件

将插件目录放入 AstrBot 的插件目录即可。

## 使用方法

### 绑定账号

私聊发送（保护密码安全）：
```
/luogu bind 你的手机号 你的密码
```

绑定成功后会自动获取并缓存个人主页和练习数据。

### 查看统计

```
/luogu info          # 使用缓存数据
/luogu info -f       # 强制从洛谷重新拉取
```

返回包含以下内容：
- 通过数 / 提交数 / 等级分 (Rating)
- 咕值 (CSR) 及其构成明细
- 排名、评定比赛数
- 评定比赛名称列表

### 每日打卡

```
/luogu checkin
```

返回洛谷打卡页面截图，包含连续打卡天数、今日运势等信息。

### 做题热度图

```
/luogu heatmap
```

返回洛谷原版热度图截图，每格颜色代表当天通过的最大难度（灰→红→橙→黄→绿→蓝→紫→黑）。

### 等级分趋势

```
/luogu elo
```

返回比赛等级分趋势折线图，标注每场分数及变化量。

### 练习情况

```
/luogu practice          # 使用缓存数据
/luogu practice -f       # 强制重新获取
```

返回按难度分类的已通过题目数量，并附难度分布卡片图。

## 技术亮点

- **Retina 级别截图** — `device_scale_factor=2`，物理分辨率翻倍，文字图表清晰锐利
- **智能缓存** — 登录时自动缓存个人数据，支持 `-f` 强制刷新
- **验证码容错** — 识别失败后自动重试（最多 5 次），JS 方式关闭弹窗不卡死
- **异步架构** — Playwright 在线程池中运行，不阻塞 AstrBot 事件循环

## 项目结构

```
astrbot_plugin_luogu/
├── main.py                 # 插件主入口
├── requirements.txt        # 依赖列表
├── metadata.yaml           # 插件元数据
├── luogu/
│   ├── __init__.py
│   ├── data_fetcher.py    # 数据提取 + 截图模块
│   ├── chart_generator.py # 图表生成模块
│   ├── screenshot.py      # 网页截图（备用）
│   └── models.py          # 数据模型
├── cookies/               # 登录 Cookie（不提交到 Git）
└── user_data/             # 用户绑定数据（不提交到 Git）
```

## 注意事项

1. **隐私保护**: Cookie 文件包含敏感登录信息，已加入 `.gitignore`，请勿提交到 Git
2. **验证码**: 首次登录可能需要验证码，ddddocr 可自动识别；未安装则需手动输入
3. **Cookie 有效期**: 洛谷 Cookie 有有效期限制，长时间不使用可能需要重新绑定
4. **推荐私聊使用**: `/luogu bind` 包含密码，请在私聊中发送避免泄露

## 更新日志

### v1.0.0 (2026-03-25)
- 正式稳定版发布
- 支持 6 条核心指令 + `-f` 强制刷新
- Retina 级别高清截图
- 验证码识别自动重试机制

## License

MIT License
