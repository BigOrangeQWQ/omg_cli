# 项目笔记

## 键盘快捷键修改

### 2024-04-07
- **Ctrl+C**: 现在用于打断 LLM 输出（之前是退出）
- **Ctrl+D**: 现在用于退出应用（新增）

### 实现细节
1. 在 `ChatContext` 类中添加了 `_interrupt_requested` 标志
2. 添加了 `interrupt()` 方法用于设置中断标志
3. 添加了 `_clear_interrupt()` 方法用于清除中断标志
4. 在 `thinking()` 方法的 stream 循环中检查中断标志
5. 在 `send()` 方法开始时清除中断标志
6. 在 `ChatTerminalApp` 中修改了 BINDINGS，将 `ctrl+c` 映射到 `action_interrupt`，`ctrl+d` 映射到 `action_quit`

## 常用命令

### 代码检查
```bash
uv run ruff check omg_cli/ tests/
```

### 运行测试
```bash
uv run pytest tests/ -v
```

### 运行特定测试
```bash
uv run pytest tests/context/ -v
```

## 启动方式

### 2024-04-09
- `uv run omg-cli` 或安装后直接使用 `omg-cli` 启动应用。
- 恢复会话：`omg-cli -r <session_id>`
- 项目根目录的 `python main.py` 仍然兼容可用。

## Approval Dialog 功能

### 2024-04-09
- `ApprovalDialog` 新增 **"Reject with custom reason..."** 选项
- 选择该选项后会弹出 `Input` 输入框，用户可输入自定义拒绝原因
- 按 `Enter` 提交后，拒绝原因会传递给 LLM（通过 `ToolConfirmationDecision.reason`）
- 支持键盘快捷键 `r` 直接选中自定义拒绝选项

## Session 管理功能

### 2024-04-07
- **退出时显示 Session UUID**: Ctrl+D 退出时会在终端打印当前 session 的 UUID
- **`/history` 命令**: 新增会话历史管理命令
  - `/history` 或 `/history list`: 列出所有保存的 session（带编号）
  - `/history load <uuid_or_number>`: 加载指定 session（支持 UUID 或列表中的编号）
  - `/history delete <uuid_or_number>`: 删除指定 session

### 实现细节
1. `omg_cli/shell/app.py`: `action_quit()` 打印 session UUID；处理 `SessionLoadedEvent` 刷新 UI
2. `omg_cli/shell/command_definitions.py`: 新增 `history_handler` 及相关子命令
3. `omg_cli/types/event.py`: 新增 `SessionLoadedEvent`
4. `omg_cli/context/__init__.py`: `load_session()` 改为 async，加载完成后 emit `SessionLoadedEvent`

## 项目结构迁移（src/ → 根目录）

### 2024-04-09
- 已将 `src/omg_cli/` 移至根目录 `omg_cli/`，删除了 `src/` 目录。
- 迁移后若 `uv run pytest` 出现 **collected 0 items** 或 import error，需检查 `pyproject.toml` 的以下两处配置：

  1. **pytest `pythonpath`** 要从 `"src"` 改为 `"."`：
     ```toml
     [tool.pytest.ini_options]
     pythonpath = ["."]
     ```
     ❌ 不要写成 `pythonpath = ["omg_cli"]`，否则会把 `omg_cli/` 直接暴露到 `sys.path` 根级，导致 `omg_cli/mcp.py` 遮蔽第三方 `mcp` 包，引发循环导入。

  2. **ruff `known-first-party`** 同步更新：
     ```toml
     [tool.ruff.lint.isort]
     known-first-party = ["omg_cli", "tests/*"]
     ```

- 所有源码引用路径同步修正：代码检查命令改为 `uv run ruff check omg_cli/ tests/`。
