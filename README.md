# myknow

本机优先的知识素材库：把网页、图片和其他灵感素材保存到可检索的本地库，支持文件夹、标签、颜色/亮度筛选、浏览器采集和可选的 OpenAI-compatible 视觉分析。

## 特性

- 本地 SQLite 数据库与本地素材存储，默认不上传素材。
- 浏览器扩展主动采集网页、图片和正文快照。
- 图片按 SHA-256 去重，支持导入已有文件夹。
- 支持原生 Windows 桌面启动器、托盘运行和安装包。
- AI 默认关闭；启用后使用用户提供的兼容接口，并把密钥保存在本机加密配置中。
- 前端 React + Vite，后端 Python，测试夹具均为合成数据。

## 快速开始

要求：Windows 10/11、Python 3.11+、Node.js 20+。

```powershell
python -m pip install -r backend/requirements.txt
Set-Location desktop-ui
npm install
npm run build
Set-Location ..
python desktop.py
```

浏览器打开 `http://127.0.0.1:8765`。Windows 用户也可以运行 `启动素材中枢.ps1`。

## 目录结构

```text
backend/       本地 API、任务队列和 AI 适配器
desktop-ui/    React/Vite 界面
extension/     Chrome/Edge Manifest V3 扩展
packaging/     PyInstaller + Inno Setup 构建脚本
tests/         单元测试与合成验收夹具
docs/          开源发布、架构和维护文档
```

## 构建 Windows 安装包

```powershell
python packaging/build_installer.py
```

构建脚本会使用隔离环境、构建前端、生成 onedir 应用、启动冻结程序进行健康/来源校验，并对最终文件执行脱敏扫描。安装器默认安装到用户可选择的 Windows 程序目录；数据目录与安装目录分离。

## 测试

```powershell
python -m unittest discover -s tests -p "test_*.py"
Set-Location desktop-ui; npm run build
```

## 安全和隐私

不要把真实素材、数据库、日志、Cookie、API Key 或用户目录提交到仓库。请先阅读 [SECURITY.md](./SECURITY.md) 和 [开源发布流程](./docs/OPEN_SOURCE_RELEASE.md)。

## 许可证

本项目采用 [MIT License](./LICENSE)，允许个人或商业使用、修改、再发布和销售副本，但需保留许可证与版权声明。软件按“现状”提供，不承担担保责任。
