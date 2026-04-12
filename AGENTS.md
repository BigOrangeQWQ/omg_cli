# AGENTS.md — OMG CLI 贡献者指南

> 面向 AI 编码助手与项目贡献者的快速参考手册。修改代码前，建议重点浏览 **速查表** 与 **常见陷阱**。

---

## 目录

1. [速查表](#速查表)
2. [项目概述](#项目概述)
3. [项目结构](#项目结构)
4. [模块依赖方向](#模块依赖方向)
5. [代码规范](#代码规范)
6. [关键行为约定](#关键行为约定)
7. [常见陷阱](#常见陷阱)

---

## 速查表

### 修改代码前必执行

```bash
uv run ruff check omg_cli/ tests/
uv run pytest tests/ -v
```

### 核心文件定位

| 内容 | 路径 |
|------|------|
| 内置工具（ReadFile / WriteFile / Shell 等） | `omg_cli/tool/tools.py` |
| 工具注册与调用确认逻辑 | `omg_cli/context/tool_manager.py` |
| 聊天上下文核心（消息流、工具调用、事件发射） | `omg_cli/context/chat.py` |
| TUI 主应用 | `omg_cli/shell/app.py` |
| UI 核心组件（消息列表、Composer、ApprovalDialog） | `omg_cli/shell/widgets.py` |
| 斜杠命令定义（`/history`、`/compact` 等） | `omg_cli/shell/command_definitions.py` |
| 适配器抽象基类 | `omg_cli/abstract/__init__.py` |
| 领域模型（Message、Event、Tool 等） | `omg_cli/types/` |
| 配置与持久化 | `omg_cli/config/` |
| 日志入口 | `omg_cli/log.py` |
| 异常定义 | `omg_cli/exception.py` |
| 常量 | `omg_cli/constant.py` |

---

## 项目概述

**一句话定义**：基于大语言模型（LLM）的交互式终端助手，帮助用户在命令行中完成代码编写、调试、重构等软件工程任务。

### 核心理念

| 理念 | 说明 |
|------|------|
| **Tools-first** | 原生支持文件读写、Shell 执行等内置工具，关键操作须经 Approval Dialog 确认。 |
| **可扩展** | 通过 MCP（Model Context Protocol）连接外部服务，动态扩展工具生态。 |
| **会话持久化** | 自动保存聊天 Session，支持随时恢复与历史管理。 |
| **多角色协作** | Channel 模式支持多 Role 子代理并行工作流。 |

### 技术栈

- **语言**: Python ≥3.14
- **TUI**: [Textual](https://textual.textualize.io/)
- **数据验证**: [Pydantic](https://docs.pydantic.dev/)
- **日志**: [Loguru](https://loguru.readthedocs.io/)
- **MCP**: [FastMCP](https://github.com/jlowin/fastmcp)
- **测试**: [pytest](https://docs.pytest.org/) + `pytest-asyncio`
- **代码质量**: [ruff](https://docs.astral.sh/ruff/)
- **包管理**: [uv](https://docs.astral.sh/uv/)

---

## 项目结构

```
omg_cli/
├── __main__.py           # argparse CLI 入口
├── cli.py                # CLI 兼容导出
├── omg.py                # 核心占位类（暂不活跃）
├── llm.py                # LLM 相关兼容导出（遗留）
├── mcp.py                # FastMCP 客户端封装
├── log.py                # Loguru 日志配置
├── config.py             # 全局配置兼容入口（空/遗留）
├── utils.py              # 通用工具函数
├── exception.py          # 项目异常定义
├── constant.py           # 项目常量
│
├── abstract/             # LLM 适配器抽象层
│   ├── __init__.py       # ChatAdapter 抽象基类
│   ├── openai.py         # OpenAI API 适配
│   ├── anthropic.py      # Anthropic API 适配
│   ├── deepseek.py       # DeepSeek API 适配
│   ├── openai_legacy.py  # 兼容 OpenAI 格式的第三方 API
│   ├── none.py           # 空适配器
│   └── utils.py          # 适配器通用工具
│
├── config/               # 配置与持久化管理
│   ├── manager.py        # 用户配置、模型配置读写
│   ├── models.py         # Pydantic 配置模型
│   ├── adapter_manager.py# 适配器生命周期管理
│   ├── role.py           # 角色配置 CRUD
│   ├── channel.py        # Channel 配置管理
│   ├── session_storage.py# Session 元数据与消息持久化
│   ├── history.py        # 终端输入历史管理
│   ├── constants.py      # 默认路径常量
│   └── __init__.py       # 统一对外导出
│
├── context/              # 聊天上下文与运行时管理
│   ├── __init__.py       # ChatContext 等核心类导出
│   ├── chat.py           # 聊天上下文核心（消息流、工具调用、事件发射）
│   ├── role.py           # ChannelContext / ThreadRoleContext
│   ├── meta.py           # MetaContext：角色元上下文
│   ├── command.py        # 上下文内命令路由
│   ├── event_manager.py  # 事件管理器封装
│   ├── mcp_manager.py    # MCP 连接与工具发现
│   └── tool_manager.py   # 工具注册、调用与确认逻辑
│
├── shell/                # TUI 界面实现（Textual）
│   ├── app.py            # ChatTerminalApp：主应用
│   ├── channel_app.py    # ChannelApp：Channel 模式主应用
│   ├── meta_app.py       # MetaApp：元应用容器
│   ├── widgets.py        # 核心 UI 组件（消息列表、Composer、ApprovalDialog）
│   ├── channel_widgets.py# Channel 模式专用组件
│   ├── command_definitions.py # 斜杠命令定义
│   ├── import_wizard.py  # 模型导入向导
│   ├── role_wizard.py    # 角色创建向导
│   ├── autocomplete.py   # 自动补全
│   ├── file_completion.py# 文件路径补全
│   ├── utils.py          # UI 辅助函数
│   ├── styles/           # CSS / 样式定义
│   └── __init__.py       # run_terminal 导出
│
├── tool/                 # 内置工具
│   ├── __init__.py       # 工具注册器与导出
│   ├── tools.py          # 系统工具（ReadFile / WriteFile / StrReplace / Shell）
│   └── todo.py           # TODO 列表工具
│
├── types/                # 领域模型与类型定义
│   ├── message.py        # 消息、Segment、流事件类型
│   ├── event.py          # 应用事件类型
│   ├── tool.py           # Tool / ToolError 定义
│   ├── channel.py        # Channel / Role / Thread 类型
│   ├── skill.py          # Anthropic skill 封装
│   ├── command.py        # 命令类型
│   ├── usage.py          # Token 用量类型
│   ├── metadata.py       # 元数据类型
│   └── constants.py      # 类型层常量
│
└── prompts/              # 系统提示词模板
```

---

## 模块依赖方向

```
types → abstract → config → context → shell
```

- **上层可依赖下层**
- **严禁反向依赖**

---

## 代码规范

### 格式化与 Lint

| 项 | 配置 |
|----|------|
| 行宽 | `120` |
| 格式化 | `ruff format` |
| 导入排序 | `ruff check --select I --fix` |
| 引号 | 双引号优先（ruff `Q` 规则集自动约束） |

### ruff 规则集

```toml
select = [
    "F", "W", "E", "I", "UP", "ASYNC", "C4",
    "T10", "T20", "PYI", "PT", "Q", "TID", "RUF",
]
ignore = [
    "E402", "UP037",
    "RUF001", "RUF002", "RUF003",
    "T201",
]
```

### 异步与测试规范

- 所有异步测试必须加 `@pytest.mark.asyncio`。
- `fixture` 定义**不加括号**：`@pytest.fixture` ✅，不是 `@pytest.fixture()` ❌。

### 日志与异常

- **统一日志入口**: `from omg_cli.log import logger`
- **异常定义文件**: `omg_cli/exception.py`

---

## 关键行为约定

### Approval Dialog

工具调用确认弹窗当前为 **3 选项**：

1. **Approve** — 同意本次调用。
2. **Approve all** — 同意后续全部调用。
3. **Skip** — 跳过本次调用。

**拒绝原因输入机制**：

- 弹窗出现时，底部 `Composer` 自动切换为"输入拒绝原因"模式。
- 用户可直接打字并按 `Enter` 提交。
- 拒绝原因通过 `ToolConfirmationDecision.reason` 传递给 LLM。
- 按 `r` 键可快速将焦点切回底部 Composer。

### Session 管理

- **自动保存**：聊天过程中 Session 自动持久化。
- **退出打印 UUID**：`Ctrl+D` 退出时，终端会打印当前 session 的 UUID。
- **恢复会话**：启动时带 `-r <session_id>` 恢复。

#### 斜杠命令

| 命令 | 作用 |
|------|------|
| `/history` 或 `/history list` | 列出所有保存的 session（带编号） |
| `/history load <uuid_or_number>` | 加载指定 session |
| `/history delete <uuid_or_number>` | 删除指定 session |

### 快捷键

| 快捷键 | 作用 |
|--------|------|
| `Ctrl+C` | 打断当前 LLM 输出 |
| `Ctrl+D` | 退出应用 |

---

## 常见陷阱

| 陷阱 | 正确做法 |
|------|----------|
| `pyproject.toml` 中 `pythonpath = ["omg_cli"]` | 必须写成 `pythonpath = ["."]`。若写成 `"omg_cli"`，会把 `omg_cli/` 暴露到 `sys.path` 根级，导致 `omg_cli/mcp.py` **遮蔽**第三方 `mcp` 包，引发循环导入。 |
| 上层模块导入下层同级/上层模块 | 严格遵守 `types → abstract → config → context → shell` 的依赖方向。 |
| 在代码中随意使用 `print()` | 通过 `from omg_cli.log import logger` 统一输出；`T201` 仅忽略，不代表推荐。 |
| async 测试忘记 `@pytest.mark.asyncio` | 每个 async test function 都必须加。 |
