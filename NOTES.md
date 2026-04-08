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
uv run ruff check src/
```

### 运行测试
```bash
uv run pytest tests/ -v
```

### 运行特定测试
```bash
uv run pytest tests/context/ -v
```
