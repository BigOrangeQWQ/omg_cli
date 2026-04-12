# OMG CLI 项目笔记

## Lint / Type Check / Test 命令

```bash
# 代码风格与静态检查
uv run ruff check omg_cli/ tests/

# 运行测试
uv run pytest tests/ -v
```

修改代码前，请先执行上述命令确保全部通过。
