# AstrBot 插件开发完整文档

> 基于 AstrBot 官方文档整理，适用于 AstrBot v4.x（部分功能需 v4.9.2+）
> 官方文档：https://docs.astrbot.app/dev/star/

---

## 目录

1. [环境准备与插件创建](#一环境准备与插件创建)
2. [插件目录结构](#二插件目录结构)
3. [最小插件示例](#三最小插件示例)
4. [消息事件监听](#四消息事件监听)
5. [消息发送](#五消息发送)
6. [插件配置](#六插件配置)
7. [AI 功能](#七ai-功能)
8. [数据存储](#八数据存储)
9. [HTML 转图片（文转图）](#九html-转图片文转图)
10. [会话控制（多轮对话）](#十会话控制多轮对话)
11. [杂项 API](#十一杂项-api)
12. [发布插件](#十二发布插件)
13. [开发规范与注意事项](#十三开发规范与注意事项)

---

## 一、环境准备与插件创建

### 前置要求
- Python 编程基础
- Git 与 GitHub 基本使用经验
- 开发者 QQ 群：975206796

### 创建插件步骤

**1. 从模板创建 GitHub 仓库**

访问 AstrBot 插件模板：https://github.com/Soulter/helloworld
- 点击右上角 `Use this template` → `Create new repository`
- 填写插件名称（推荐格式：`astrbot_plugin_xxx`，全小写，无空格）

**2. 克隆到本地 AstrBot 插件目录**

```bash
git clone https://github.com/AstrBotDevs/AstrBot
mkdir -p AstrBot/data/plugins
cd AstrBot/data/plugins
git clone 你的插件仓库地址
```

**3. 配置插件元数据**

修改插件目录下的 `metadata.yaml`，这是 AstrBot 识别插件的关键文件。

**4. 调试**

启动 AstrBot，在 WebUI 插件管理处点击「重载插件」即可热重载。

---

## 二、插件目录结构

```
your_plugin_name/
├── main.py              # 插件主入口文件（必须）
├── metadata.yaml        # 插件元数据（必须）
├── _conf_schema.json    # 插件配置 Schema（可选）
├── requirements.txt     # 第三方依赖（可选）
└── logo.png             # 插件图标，推荐 256x256（可选）
```

### metadata.yaml 示例

```yaml
name: astrbot_plugin_example     # 插件名称（与目录名一致）
desc: 这是一个示例插件            # 插件描述
version: v1.0.0                  # 插件版本
author: YourName                 # 作者
repo: https://github.com/...     # 仓库地址

# 可选字段
display_name: 示例插件            # WebUI 展示名称
astrbot_version: ">=4.0.0"       # AstrBot 版本要求
support_platforms:               # 支持的消息平台
  - aiocqhttp
  - qq_official
```

---

## 三、最小插件示例

插件类所在文件**必须命名为 `main.py`**，插件类**必须继承 `Star`**。

```python
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger

class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    @filter.command("helloworld")
    async def helloworld(self, event: AstrMessageEvent):
        '''这是一个 hello world 指令'''   # 描述信息，建议填写
        user_name = event.get_sender_name()
        message_str = event.message_str   # 获取消息纯文本
        logger.info("触发 hello world 指令!")
        yield event.plain_result(f"Hello, {user_name}!")

    async def terminate(self):
        '''插件被卸载/停用时调用，可选实现'''
```

### AstrMessageEvent 常用属性与方法

| 属性/方法 | 说明 |
|-----------|------|
| `event.message_str` | 消息纯文本内容 |
| `event.message_obj` | 原始 `AstrBotMessage` 对象 |
| `event.get_sender_name()` | 获取发送者名称 |
| `event.get_sender_id()` | 获取发送者 ID |
| `event.get_group_id()` | 获取群组 ID（私聊返回 None） |
| `event.get_platform_name()` | 获取平台名称 |
| `event.unified_msg_origin` | 会话唯一标识（用于主动消息） |
| `event.stop_event()` | 停止事件传播 |
| `event.send(result)` | 在会话函数中主动发送消息 |

### AstrBotMessage 结构

```python
message_obj = event.message_obj
message_obj.type          # 消息类型
message_obj.message_str   # 纯文本内容
message_obj.sender        # 发送者信息
message_obj.message       # 消息链（List[BaseMessageComponent]）
message_obj.message_id    # 消息 ID
```

---

## 四、消息事件监听

### 基础导入

```python
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
```

### 指令注册

```python
# 普通指令：用户发送 /helloworld 触发
@filter.command("helloworld")
async def helloworld(self, event: AstrMessageEvent):
    yield event.plain_result("Hello!")

# 带优先级（数字越大优先级越高）
@filter.command("helloworld", priority=10)
async def helloworld(self, event: AstrMessageEvent):
    yield event.plain_result("高优先级!")

# 带参数指令：/add 1 2
@filter.command("add")
async def add(self, event: AstrMessageEvent, a: int, b: int):
    yield event.plain_result(f"结果: {a + b}")
```

### 指令组（多级指令）

```python
# 用法：/math add 1 2
@filter.command_group("math")
def math(self):
    pass

@math.command("add")
async def math_add(self, event: AstrMessageEvent, a: int, b: int):
    yield event.plain_result(f"结果: {a + b}")

@math.command("sub")
async def math_sub(self, event: AstrMessageEvent, a: int, b: int):
    yield event.plain_result(f"结果: {a - b}")
```

### 消息类型过滤

```python
from astrbot.api.event import filter

# 只接收私聊消息
@filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
async def on_private(self, event: AstrMessageEvent):
    yield event.plain_result("收到私聊消息")

# 只接收群聊消息
@filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
async def on_group(self, event: AstrMessageEvent):
    yield event.plain_result("收到群聊消息")
```

### 平台适配器过滤

```python
# 只接收 QQ (aiocqhttp) 平台消息
@filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
async def on_aiocqhttp(self, event: AstrMessageEvent):
    yield event.plain_result("收到 QQ 消息")
```

### 事件钩子

```python
# Bot 初始化完成时触发
@filter.on_astrbot_loaded()
async def on_loaded(self):
    logger.info("AstrBot 初始化完成")

# LLM 请求前触发（可修改请求参数）
@filter.on_llm_request()
async def on_llm_req(self, event: AstrMessageEvent, req: ProviderRequest):
    req.system_prompt += "\n你必须用中文回复。"
```

### 停止事件传播

```python
@filter.command("check")
async def check(self, event: AstrMessageEvent):
    if not self.is_valid():
        yield event.plain_result("检查不通过，停止处理")
        event.stop_event()  # 后续插件不再处理此事件
        return
    yield event.plain_result("检查通过")
```

### 消息链结构

消息链类型 `List[BaseMessageComponent]`，常见消息段类型：

| 类型 | 说明 |
|------|------|
| `Plain` | 纯文本 |
| `At` | @某人 |
| `Image` | 图片 |
| `Record` | 语音 |
| `Video` | 视频 |
| `File` | 文件 |
| `Node` | 合并转发节点 |

---

## 五、消息发送

### 被动回复（yield 方式）

```python
import astrbot.api.message_components as Comp

@filter.command("demo")
async def demo(self, event: AstrMessageEvent):
    # 发送纯文本
    yield event.plain_result("Hello!")

    # 发送图片（本地路径或 URL）
    yield event.image_result("path/to/image.jpg")
    yield event.image_result("https://example.com/image.jpg")

    # 发送消息链（可组合多种元素）
    chain = [
        Comp.At(qq=event.get_sender_id()),            # @发送者
        Comp.Plain("来看这个图："),
        Comp.Image.fromURL("https://example.com/image.jpg"),   # 网络图片
        Comp.Image.fromFileSystem("path/to/image.jpg"),        # 本地图片
        Comp.Plain("这是一个图片。")
    ]
    yield event.chain_result(chain)

    # 可连续 yield 多条消息
    yield event.plain_result("第一条")
    yield event.plain_result("第二条")
```

### 主动推送消息

```python
from astrbot.api.event import MessageChain

@filter.command("push")
async def push(self, event: AstrMessageEvent):
    umo = event.unified_msg_origin   # 保存会话唯一标识
    message_chain = (
        MessageChain()
        .message("Hello!")
        .file_image("path/to/image.jpg")
    )
    await self.context.send_message(umo, message_chain)
```

> `unified_msg_origin` 可持久化保存，用于定时任务等场景的主动推送。

### 富媒体消息组件

```python
import astrbot.api.message_components as Comp

# 文本
Comp.Plain("文字内容")

# @某人（QQ 平台）
Comp.At(qq="123456789")

# 图片
Comp.Image.fromURL("https://example.com/image.jpg")
Comp.Image.fromFileSystem("path/to/image.jpg")

# 文件
Comp.File(file="path/to/file.txt", name="file.txt")

# 语音（仅支持 WAV 格式）
Comp.Record(file="path/to/record.wav")

# 视频
Comp.Video.fromFileSystem(path="test.mp4")
Comp.Video.fromURL(url="https://example.com/video.mp4")

# 合并转发节点（仅 OneBot v11 支持）
from astrbot.api.message_components import Node, Plain, Image
node = Node(
    uin=123456789,
    name="昵称",
    content=[Plain("hi"), Image.fromFileSystem("test.jpg")]
)
yield event.chain_result([node])
```

### 注意事项

- aiocqhttp 适配器中，`Plain` 消息会被 `strip()` 处理，如需保留首尾空格可使用零宽空格 `\u200b`
- 部分消息类型不被所有平台支持，需判断平台后使用
- 视频/文件发送要求协议端与机器人端在同一系统环境

---

## 六、插件配置

### 创建配置 Schema

在插件目录下创建 `_conf_schema.json`，AstrBot 会自动在 WebUI 中生成可视化配置面板。

```json
{
  "api_key": {
    "type": "string",
    "description": "API 密钥",
    "hint": "在服务商官网获取",
    "default": ""
  },
  "max_count": {
    "type": "int",
    "description": "最大数量",
    "default": 10
  },
  "enable_feature": {
    "type": "bool",
    "description": "是否启用某功能",
    "default": false
  },
  "system_prompt": {
    "type": "text",
    "description": "系统提示词（长文本）",
    "default": "你是一个助手",
    "editor_mode": "markdown"
  },
  "allowed_groups": {
    "type": "list",
    "description": "允许使用的群组 ID 列表",
    "default": []
  }
}
```

### 配置类型一览

| type | 说明 | 适用场景 |
|------|------|----------|
| `string` | 单行文本 | API Key、URL 等 |
| `text` | 多行文本 | 提示词、长描述 |
| `int` | 整数 | 数量、超时时间 |
| `float` | 浮点数 | 权重、比例 |
| `bool` | 布尔值 | 开关选项 |
| `list` | 列表 | 白名单、ID 列表 |
| `dict` | 字典 | 键值对配置 |
| `object` | 嵌套对象 | 复杂结构配置 |
| `template_list` | 模板列表 | 多组配置项 |
| `file` | 文件上传（v4.13.0+） | 上传 PDF、图片等 |

### 特殊字段

```json
{
  "provider_id": {
    "type": "string",
    "description": "选择 AI 模型提供商",
    "_special": "provider"
  }
}
```

`_special` 支持的值：
- `"provider"` - 快速选择已配置的 LLM 提供商
- `"persona"` - 快速选择已配置的人格

### 在插件中使用配置

```python
from astrbot.api import AstrBotConfig

class MyPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

    @filter.command("test")
    async def test(self, event: AstrMessageEvent):
        api_key = self.config["api_key"]
        max_count = self.config["max_count"]
        logger.info(f"配置: {self.config}")

        # 修改并保存配置
        self.config["max_count"] = 20
        self.config.save_config()
```

> AstrBot 会在版本更新时自动处理 Schema 变更：为缺失字段填充默认值、移除已删除的字段。

---

## 七、AI 功能

> 需要 AstrBot v4.5.7 及以上版本。

### 获取当前聊天模型 ID

```python
umo = event.unified_msg_origin
provider_id = await self.context.get_current_chat_provider_id(umo=umo)
```

### 直接调用 LLM

```python
llm_resp = await self.context.llm_generate(
    chat_provider_id=provider_id,
    prompt="你好，请介绍一下自己",
)
result_text = llm_resp.completion_text
```

### 注册 LLM Tool（装饰器方式）

```python
@filter.llm_tool(name="get_weather")
async def get_weather(self, event: AstrMessageEvent, location: str):
    '''获取指定地点的天气信息。

    Args:
        location(string): 要查询天气的地点名称
    '''
    # 实现天气查询逻辑
    return f"{location} 今天晴，25°C"
```

### 注册 LLM Tool（类定义方式）

```python
from pydantic import Field
from pydantic.dataclasses import dataclass
from astrbot.api.provider import FunctionTool, AstrAgentContext, ContextWrapper

@dataclass
class WeatherTool(FunctionTool[AstrAgentContext]):
    name: str = "get_weather"
    description: str = "获取天气信息"
    parameters: dict = Field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "location": {"type": "string", "description": "地点名称"}
        },
        "required": ["location"]
    })

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs):
        location = kwargs.get("location", "")
        return f"{location} 今天晴，25°C"

# 在 __init__ 中注册
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.context.add_llm_tools(WeatherTool())
```

### 调用 Agent（工具循环）

```python
from astrbot.api.provider import ToolSet

llm_resp = await self.context.tool_loop_agent(
    event=event,
    chat_provider_id=provider_id,
    prompt="帮我查询北京的天气",
    tools=ToolSet([WeatherTool()]),
    max_steps=30,          # 最大执行步骤
    tool_call_timeout=60,  # 工具调用超时（秒）
)
result_text = llm_resp.completion_text
```

### Multi-Agent 多智能体（agent-as-tool 模式）

```python
# 子 Agent 作为工具注册给主 Agent
@dataclass
class WeatherAgentTool(FunctionTool[AstrAgentContext]):
    name: str = "weather_agent"
    description: str = "专门处理天气相关查询的子智能体"

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs):
        query = kwargs.get("query", "")
        # 调用子 Agent
        resp = await context.agent_context.tool_loop_agent(
            prompt=query,
            tools=ToolSet([WeatherTool()]),
        )
        return resp.completion_text
```

### 对话管理器

```python
conv_mgr = self.context.conversation_manager

# 获取当前对话
uid = event.get_sender_id()
curr_cid = "default"
conversation = await conv_mgr.get_conversation(uid, curr_cid)

# 添加消息记录
from astrbot.api.provider import UserMessageSegment, AssistantMessageSegment, TextPart
await conv_mgr.add_message_pair(
    cid=curr_cid,
    user_message=UserMessageSegment(content=[TextPart(text="用户消息")]),
    assistant_message=AssistantMessageSegment(content=[TextPart(text="助手回复")]),
)

# 新建对话
new_cid = await conv_mgr.new_conversation(uid)

# 切换对话
await conv_mgr.switch_conversation(uid, new_cid)

# 删除对话
await conv_mgr.delete_conversation(uid, curr_cid)
```

### 人格设定管理器

```python
persona_mgr = self.context.persona_manager

# 获取指定人格
persona = persona_mgr.get_persona("default")

# 获取所有人格
all_personas = persona_mgr.get_all_personas()

# 创建人格
persona_mgr.create_persona(
    persona_id="my_persona",
    system_prompt="你是一个友善的助手",
    tools=["get_weather"]
)

# 更新人格
persona_mgr.update_persona(
    persona_id="my_persona",
    system_prompt="你是一个幽默的助手"
)

# 删除人格
persona_mgr.delete_persona("my_persona")
```

---

## 八、数据存储

### KV 简单存储（需 v4.9.2+）

每个插件拥有独立的 KV 存储空间，互不干扰。

```python
class MyPlugin(Star):
    @filter.command("demo")
    async def demo(self, event: AstrMessageEvent):
        # 写入数据（支持任意可序列化对象）
        await self.put_kv_data("user_count", 100)
        await self.put_kv_data("config", {"theme": "dark", "lang": "zh"})
        await self.put_kv_data("greeted", True)

        # 读取数据（第二个参数为默认值）
        count = await self.get_kv_data("user_count", 0)
        config = await self.get_kv_data("config", {})
        greeted = await self.get_kv_data("greeted", False)

        # 删除数据
        await self.delete_kv_data("greeted")
```

### 大文件存储

将大文件存储在插件专属目录中：

```python
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
import os

class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # 获取并确保插件数据目录存在
        self.data_dir = get_astrbot_data_path() / "plugin_data" / self.name
        self.data_dir.mkdir(parents=True, exist_ok=True)

    async def save_file(self, filename: str, content: bytes):
        file_path = self.data_dir / filename
        with open(file_path, "wb") as f:
            f.write(content)

    async def load_file(self, filename: str) -> bytes:
        file_path = self.data_dir / filename
        with open(file_path, "rb") as f:
            return f.read()
```

> 实际存储路径：`data/plugin_data/{plugin_name}/`

---

## 九、HTML 转图片（文转图）

底层基于 Playwright 截图实现。

### 纯文本转图片

```python
@filter.command("text2img")
async def text2img(self, event: AstrMessageEvent, text: str):
    url = await self.text_to_image(text)
    yield event.image_result(url)

# 返回本地路径（而非 URL）
url = await self.text_to_image(text, return_url=False)
```

### HTML + Jinja2 模板转图片

```python
TMPL = '''
<div style="font-family: Arial; font-size: 20px; padding: 20px; background: white;">
    <h1 style="color: #333;">{{ title }}</h1>
    <ul>
    {% for item in items %}
        <li>{{ item }}</li>
    {% endfor %}
    </ul>
</div>
'''

@filter.command("render")
async def render(self, event: AstrMessageEvent):
    data = {
        "title": "待办事项",
        "items": ["吃饭", "睡觉", "写代码"]
    }
    url = await self.html_render(TMPL, data)
    yield event.image_result(url)
```

### html_render 渲染选项

```python
options = {
    "type": "png",            # 图片格式："jpeg" 或 "png"
    "quality": 80,            # JPEG 质量（0-100）
    "omit_background": True,  # 透明背景（仅 PNG）
    "full_page": True,        # 截取完整页面
    "animations": "disabled", # 禁用 CSS 动画："allow" 或 "disabled"
    "scale": "device",        # 缩放：'css' 或 'device'
    "timeout": 30,            # 截图超时（秒）
}
url = await self.html_render(TMPL, data, options=options)
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `type` | `"jpeg"/"png"` | 输出图片格式 |
| `quality` | `int (0-100)` | JPEG 质量 |
| `omit_background` | `bool` | 是否透明背景（PNG 适用） |
| `full_page` | `bool` | 是否截取完整页面 |
| `animations` | `"allow"/"disabled"` | CSS 动画设置 |
| `scale` | `"css"/"device"` | 页面缩放 |
| `timeout` | `float` | 截图超时时间（秒） |
| `clip` | `dict` | 截图后裁切区域 |
| `caret` | `"hide"/"initial"` | 文本光标显示方式 |

---

## 十、会话控制（多轮对话）

用于实现连续多轮对话场景，如成语接龙、问卷填写等。

### 基本用法

```python
import astrbot.api.message_components as Comp
from astrbot.core.utils.session_waiter import session_waiter, SessionController
from astrbot.api.event import AstrMessageEvent

# 定义会话等待函数（在类外部或类内部均可）
@session_waiter(timeout=60, record_history_chains=False)
async def my_waiter(controller: SessionController, event: AstrMessageEvent):
    user_input = event.message_str

    if user_input in ["退出", "exit", "quit"]:
        await event.send(event.plain_result("会话已结束"))
        controller.stop()  # 结束会话
        return

    # 处理用户输入
    await event.send(event.plain_result(f"你说了：{user_input}"))

    # 重置超时并继续等待下一条消息
    controller.keep(timeout=60, reset_timeout=True)


class MyPlugin(Star):
    @filter.command("chat")
    async def start_chat(self, event: AstrMessageEvent):
        yield event.plain_result("已进入多轮对话，发送「退出」结束")
        try:
            await my_waiter(event)
        except TimeoutError:
            yield event.plain_result("会话超时，已自动退出")
        except Exception as e:
            yield event.plain_result(f"会话出错：{e}")
        finally:
            event.stop_event()  # 务必调用，清理会话资源
```

### SessionController 方法

| 方法 | 参数 | 说明 |
|------|------|------|
| `controller.keep(timeout, reset_timeout)` | `timeout`：超时秒数；`reset_timeout`：是否重置计时 | 继续等待下一条消息 |
| `controller.stop()` | 无 | 立即结束会话 |
| `controller.get_history_chains()` | 无 | 获取历史消息链（需开启记录） |

### @session_waiter 参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `timeout` | `int` | 等待超时秒数，超时抛出 `TimeoutError` |
| `record_history_chains` | `bool` | 是否记录历史消息链，默认 `False` |

### 自定义会话 ID（按群组共享会话）

```python
from astrbot.core.utils.session_waiter import SessionFilter

class GroupSessionFilter(SessionFilter):
    def filter(self, event: AstrMessageEvent) -> str:
        # 以群组 ID 作为会话标识（群内所有成员共享同一会话）
        return event.get_group_id() or event.unified_msg_origin

# 调用时传入自定义过滤器
await my_waiter(event, session_filter=GroupSessionFilter())
```

### 注意事项

- 会话等待函数内使用 `await event.send()` 发送消息，**不能使用 yield**
- `finally` 块中**必须调用** `event.stop_event()` 以清理会话资源
- 会话控制器激活后，同一发送人的后续消息优先进入会话处理

---

## 十一、杂项 API

### 获取消息平台实例（v3.4.34+）

```python
from astrbot.api.platform import AiocqhttpAdapter

@filter.command("test")
async def test(self, event: AstrMessageEvent):
    platform = self.context.get_platform(filter.PlatformAdapterType.AIOCQHTTP)
    assert isinstance(platform, AiocqhttpAdapter)
    # 使用 platform.get_client().api.call_action(...)
```

### 调用 QQ 协议端原生 API

```python
@filter.command("delete_msg")
async def delete_msg(self, event: AstrMessageEvent):
    if event.get_platform_name() == "aiocqhttp":
        from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
        assert isinstance(event, AiocqhttpMessageEvent)

        client = event.bot  # 获取协议端客户端
        await client.api.call_action(
            "delete_msg",
            message_id=event.message_obj.message_id
        )
```

相关 API 文档参考：
- Napcat：https://napcat.apifox.cn/
- Lagrange：https://lagrange-onebot.apifox.cn/

### 获取所有已加载插件

```python
# 返回 List[StarMetadata]，包含插件实例、配置等信息
stars = self.context.get_all_stars()
for star in stars:
    logger.info(f"插件名: {star.name}, 版本: {star.version}")
```

### 获取所有已加载平台

```python
from astrbot.api.platform import Platform

platforms = self.context.platform_manager.get_insts()  # List[Platform]
for platform in platforms:
    logger.info(f"平台: {platform.name}")
```

### 日志

```python
from astrbot.api import logger

logger.debug("调试信息")
logger.info("普通信息")
logger.warning("警告信息")
logger.error("错误信息")
```

---

## 十二、发布插件

### 发布流程

1. **推送代码到 GitHub**
   - 确认插件代码和 `metadata.yaml` 正确无误
   - 推送到 GitHub 公开仓库

2. **在插件市场提交**
   - 访问 https://plugins.astrbot.app
   - 点击右下角 `+` 按钮
   - 填写插件基本信息、作者信息、仓库地址等

3. **提交 GitHub Issue**
   - 点击「提交到 GITHUB」，跳转到 AstrBot 仓库的 Issue 页面
   - 确认信息无误后点击「Create」提交

4. **等待审核**
   - 审核通过后插件出现在市场中

### 插件命名规范

- 格式：`astrbot_plugin_xxx`
- 全小写，用下划线分隔，无空格
- 简短明了，体现插件功能

---

## 十三、开发规范与注意事项

### 代码规范

- 使用 `ruff` 格式化代码
- 所有事件处理函数必须是 `async` 函数
- 处理函数前两个参数必须是 `self` 和 `event`
- 建议为每个 handler 编写文档字符串（docstring）
- 逻辑复杂时将具体服务写在外部模块，在 handler 中调用

### 依赖管理

- 将所有第三方依赖写入 `requirements.txt`
- 优先使用异步网络请求库：`aiohttp`、`httpx`
- 不使用同步 IO（如 `requests`），避免阻塞事件循环

### 数据存储规范

- 持久化数据统一存储在 `data/plugin_data/{plugin_name}/` 目录
- 小型数据使用 KV 存储，大文件使用目录存储
- 不要直接写入 AstrBot 根目录

### 异常处理

```python
@filter.command("safe_demo")
async def safe_demo(self, event: AstrMessageEvent):
    try:
        result = await some_async_operation()
        yield event.plain_result(result)
    except SomeSpecificError as e:
        logger.error(f"操作失败: {e}")
        yield event.plain_result("操作失败，请稍后重试")
    except Exception as e:
        logger.exception(f"未预期的错误: {e}")
        yield event.plain_result("发生未知错误")
```

### 插件生命周期

```python
class MyPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        # 在这里做初始化操作
        self.data_dir = get_astrbot_data_path() / "plugin_data" / self.name
        self.data_dir.mkdir(parents=True, exist_ok=True)

    async def terminate(self):
        # 插件卸载/停用时调用，执行清理操作
        # 关闭连接、保存状态等
        logger.info("插件已卸载")
```

### 完整插件模板

```python
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger, AstrBotConfig
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
import astrbot.api.message_components as Comp


class MyPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        # 初始化数据目录
        self.data_dir = get_astrbot_data_path() / "plugin_data" / self.name
        self.data_dir.mkdir(parents=True, exist_ok=True)

    @filter.command("help")
    async def help_cmd(self, event: AstrMessageEvent):
        '''显示帮助信息'''
        help_text = (
            "可用指令：\n"
            "/help - 显示帮助\n"
            "/echo <text> - 回显文字\n"
        )
        yield event.plain_result(help_text)

    @filter.command("echo")
    async def echo_cmd(self, event: AstrMessageEvent, text: str):
        '''回显用户发送的文字'''
        yield event.plain_result(text)

    async def terminate(self):
        '''插件停用时调用'''
        logger.info(f"插件 {self.name} 已停用")
```

---

## 快速参考卡

### 常用导入

```python
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger, AstrBotConfig
import astrbot.api.message_components as Comp
from astrbot.api.event import MessageChain
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
from astrbot.core.utils.session_waiter import session_waiter, SessionController, SessionFilter
```

### 常用 event 方法

```python
event.message_str                     # 纯文本消息内容
event.get_sender_name()               # 发送者名称
event.get_sender_id()                 # 发送者 ID
event.get_group_id()                  # 群组 ID
event.get_platform_name()             # 平台名称（如 "aiocqhttp"）
event.unified_msg_origin              # 会话唯一标识
event.plain_result("文本")            # 构造纯文本回复
event.image_result("path_or_url")     # 构造图片回复
event.chain_result([...])             # 构造消息链回复
event.stop_event()                    # 停止事件传播
await event.send(result)              # 在会话函数中发送消息
```

### 常用 context 方法

```python
self.context.send_message(umo, chain)           # 主动发送消息
self.context.get_platform(type)                 # 获取平台实例
self.context.get_all_stars()                    # 获取所有插件
self.context.platform_manager.get_insts()       # 获取所有平台
self.context.llm_generate(...)                  # 调用 LLM
self.context.tool_loop_agent(...)               # 调用 Agent
self.context.add_llm_tools(...)                 # 注册 LLM 工具
self.context.get_current_chat_provider_id(...)  # 获取当前模型 ID
self.context.conversation_manager              # 对话管理器
self.context.persona_manager                   # 人格管理器
```

### KV 存储

```python
await self.put_kv_data("key", value)      # 写入
value = await self.get_kv_data("key", default)  # 读取
await self.delete_kv_data("key")          # 删除
```

### 文转图

```python
url = await self.text_to_image("文本内容")
url = await self.html_render(html_template, data_dict, options={})
yield event.image_result(url)
```
