# Development Guide

## 环境

- Windows 10/11
- Python 3.11+
- Node.js 20+
- Git

## 初始化

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt
Set-Location desktop-ui
npm ci
Set-Location ..
```

## 日常开发

启动后端和桌面工作台：

```powershell
python desktop.py
```

前端单独调试时，在另一个终端运行：

```powershell
Set-Location desktop-ui
npm run dev
```

浏览器扩展位于 `extension/`，使用 Chrome/Edge 的“加载已解压的扩展程序”进行本地调试。

## 提交前检查

```powershell
python -m unittest discover -s tests -p "test_*.py"
Set-Location desktop-ui
npm run build
npm audit
Set-Location ..
git diff --check
```

测试使用隔离的 `MUSE_VAULT_HOME`，不要让测试写入正式 `data/`。构建产生的 `dist/`、`node_modules/` 和 `releases/` 不应提交。

## Pull Request 工作流

1. 先用 Issue 说明问题、场景和验收标准。
2. 保持每个 Pull Request 小而聚焦，说明兼容性影响。
3. 附上实际运行过的测试命令和结果。
4. 复核没有真实素材、数据库、日志、Cookie、密钥或本机绝对路径。
