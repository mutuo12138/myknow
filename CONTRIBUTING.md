# 参与贡献

感谢你为 myknow 提交改进。

## 开发约定

1. 先创建 issue 描述问题或提案，再提交小而聚焦的 Pull Request。
2. 不要提交真实素材、数据库、日志、Cookie、API Key、用户目录或构建产物。
3. 修改后运行 `python -m unittest discover -s tests -p "test_*.py"`；涉及界面时再运行 `npm.cmd run build`。
4. 提交信息使用清晰的动词开头，例如 `fix: prevent duplicate import`。

## Pull Request 清单

- 说明问题、方案和潜在兼容性影响。
- 附上测试命令和结果。
- 确认脱敏审计没有发现本机路径、凭据或用户数据。
- 只提交必要文件，不提交 `data/`、`releases/`、`node_modules/` 和日志。
