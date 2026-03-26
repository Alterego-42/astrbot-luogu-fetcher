# 2026-03-27 Release Notes

本轮变更聚焦于 `/luogu jump` 的题面获取稳定性、题面展示体验，以及“普通聊天中的全局自然语言选题”能力。

## 主要变化

- 修复 `/luogu jump` 中题面 Markdown 获取链路，优先走可用的 Markdown 内容而不是直接整页截图。
- 拆分 `看图` 与 `截图`：
  - `看图` 优先发送基于 Markdown 渲染的长图。
  - `截图` 保留官方网页截图路径。
- 优化截图容器定位，优先锁定题面主体区域，减少截到整页或错误区域的概率。
- Markdown 长图渲染增加多语言字体与 LaTeX 支持。
- `/luogu jump` 在 `看图` / `截图` 后会保留当前题目上下文，便于继续 `random`、`back` 或切换图片模式。
- 自然语言选题标签来源切换为洛谷官方标签快照，避免手写标签集过时。
- 去掉过宽的标签别名收缩，例如“次小生成树”不再直接扩成“生成树”。
- 新增全局 AstrBot LLM 工具 `luogu_problem_search`：
  - 供主 LLM 在普通聊天中按需调用。
  - 支持自然语言检索、列候选、随机挑题、带条件的序号选题。
  - 不覆盖 `/luogu jump` 的显式多轮流程。

## 边界行为

- `看图`、`截图`、`back`、`restart`、`quit` 这类多轮操作仍然只在 `/luogu jump` 中处理。
- 全局工具遇到无法确认的意图时，会返回安全提示，而不是默认搜整站。
- 全局工具不会假装记住上一轮候选列表；如果只给“第 3 题”而没有筛选条件，会提示改用 `/luogu jump` 或补充条件。

## 版本要求

- `metadata.yaml` 已将 AstrBot 版本要求提升到 `>=4.5.7`，因为 `@filter.llm_tool(...)` 需要较新的 AstrBot 版本。

## 已完成的本地验证

- `python -m compileall main.py luogu`
- 基于工作区 cookie 的脚本 smoke test：
  - `ICPC` 条件检索可返回候选列表
  - 随机选题可跳转到具体题目
  - 指定序号选题可跳转到对应题目
  - 全局工具的 `unknown` / `show_screenshot` / 无条件 `select` 等边界分支会返回安全提示

## 仍需实机验证

- QQ 侧长图消息的最终阅读体验
- 实际 AstrBot 运行时中主 LLM 对 `luogu_problem_search` 的调用时机与效果
- `/luogu jump` 中 `看图` / `截图` 的真实发送效果是否与本地模拟一致
