# Luogu 语义专家路由方案

## 目标

把“是否进入洛谷工具链、当前语义是什么、该放哪些工具、首个工具应带什么参数”从主 LLM 的自由发挥中拆出来，改成：

1. 轻规则门禁
2. 快速模型语义专家
3. 本地确定性 planner
4. 主 LLM 只负责按限制调用工具并组织回复

## 为什么要这么做

当前痛点不是“主模型完全不会找题”，而是：

- 对普通聊天 follow-up 的识别不稳定
- 主 LLM 看到候选列表后会自己选题，但 session 不一定同步记录
- 像“换一道”“图也来”这样的短追问容易掉回普通闲聊回复

## 第一阶段设计

### 1. `luogu/semantic_expert.py`

新增“洛谷语义分析专家”，职责：

- 判定是否 `route_to_luogu`
- 输出 `intent / target / search_action / tool_candidates`
- 输出 `preferred_after_tools`
- 不直接回答用户，只给结构化 JSON

### 2. 插件配置

新增 `astrbot-luogu-fetcher/_conf_schema.json`：

- `Routing_Models.semantic_provider_id`
- `Routing_Models.semantic_debug_mode`

这样可以在 AstrBot WebUI 里给语义专家单独选择一个更快、更便宜的 provider。

### 3. `main.py` 路由入口

`on_llm_request` 新流程：

1. 先回放当前 Luogu session
2. 调语义专家拿结构化判定
3. 若规则或语义专家认为应该进入 Luogu，就继续走 parser/planner
4. 把语义专家结论和 planner 推荐调用一起注入主 LLM 提示词

### 4. `luogu_problem_search` 增强

新增可选参数：

- `action`
- `index`

用于承接 planner 推荐调用，如：

- `luogu_problem_search(query="来一道线段树紫题", action="random")`
- `luogu_problem_search(query="第3题", action="select", index=3)`
- `luogu_problem_search(query="总共有多少道", action="count")`

### 5. parser / planner 增强

- parser 接收 `preferred_after_tools`
- planner 在 `steps.payload` 中显式给出推荐工具参数
- 主 LLM 提示里展示“推荐的首选工具调用”

## 第一阶段预期收益

- “换一道”能更稳定地落到当前候选集随机换题
- “来一道 xxx 题”可以更自然地走 `action="random"`，避免主 LLM 自己从候选里硬选
- “图也来 / 图呢”这类跟进语句更容易直接锁到 `luogu_problem_image`
- 日志能清楚区分：
  - 语义专家怎么判
  - planner 怎么定工具
  - 工具最终有没有执行

## 还没做完的下一步

- 让 `select` / `random` / `count` 的工具调用完全以 planner payload 为准，而不是仍部分依赖工具内自然语言解析
- 为 `problem_lookup.py` 增加结构化日志
- 为“引用图片追问”加专门的语义示例与回归清单
