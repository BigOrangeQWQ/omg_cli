# OMG CLI - AI 驱动的终端助手

## 项目简介

OMG CLI 是一个基于大语言模型（LLM）的交互式终端助手，帮助用户完成软件工程任务。它提供了一个 TUI（文本用户界面），支持多轮对话、工具调用、MCP 协议集成等功能。

## 核心特性

- **多模型支持**：支持 OpenAI、Anthropic、DeepSeek 等多种 LLM 提供商
- **工具调用**：内置文件操作（读/写/替换）、Shell 命令执行等工具
- **MCP 集成**：支持 Model Context Protocol，可连接外部工具服务
- **流式响应**：实时显示 AI 回复，支持 Thinking 模式
- **会话管理**：支持清空会话、上下文压缩等功能

## 项目结构

```
.
├── main.py                 # 程序入口
├── pyproject.toml          # 项目配置
├── src/omg_cli/
│   ├── abstract/           # LLM 适配器抽象层
│   │   ├── openai.py       # OpenAI API 适配
│   │   ├── anthropic.py    # Anthropic API 适配
│   │   ├── deepseek.py     # DeepSeek API 适配
│   │   └── openai_legacy.py # 兼容 OpenAI 格式的 API
│   ├── shell/              # TUI 界面实现
│   │   ├── app.py          # 主应用逻辑
│   │   ├── widgets.py      # UI 组件
│   │   ├── commands.py     # 命令处理
│   │   └── import_wizard.py # 模型导入向导
│   ├── context/            # 聊天上下文管理
│   │   ├── __init__.py     # ChatContext 核心类
│   │   ├── tool_manager.py # 工具管理
│   │   └── mcp_manager.py  # MCP 连接管理
│   ├── config/             # 配置管理
│   │   ├── manager.py      # 配置读写
│   │   └── models.py       # 模型配置定义
│   ├── tool/               # 内置工具
│   │   ├── tools.py        # 文件/Shell 工具
│   │   └── todo.py         # 任务列表工具
│   ├── types/              # 类型定义
│   └── prompts/            # 系统提示词
└── tests/                  # 测试代码
```

## 技术栈

- **Python 3.14+**：主开发语言
- **Textual**：TUI 框架
- **Pydantic**：数据验证和配置管理
- **FastMCP**：MCP 协议实现
- **Loguru**：日志记录

## 代码规范

- 使用 **Ruff** 进行代码格式化和检查
- 行长度限制：120 字符
- 异步优先：工具调用和 API 请求均为异步实现
- 类型注解：全面使用 Python 类型注解

## 常用命令

```bash
# 运行程序
python main.py

# 指定模型运行
python main.py --model gpt-4

# 调试模式
python main.py --debug

# 运行测试
pytest

# 代码格式化
ruff format .
ruff check --fix .
```

## 配置说明

配置文件存储在 `~/.config/omg-cli/`：

- `models.toml`：保存的模型配置（权限 600）
- `config.toml`：用户配置

模型配置包含：名称、提供商、模型名、API 密钥、Base URL 等。

## 开发注意事项

1. **工具注册**：使用 `@register_tool` 装饰器注册新工具
2. **路径处理**：文件操作必须使用绝对路径，`!` 前缀表示项目根目录
3. **错误处理**：工具错误使用 `ToolError` 异常
4. **API 适配**：新增提供商需继承 `ChatAdapter` 抽象类
