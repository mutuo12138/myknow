<p align="center">
  <img src="packaging/assets/icon-redesign-20260825/myknow-icon-viewfinder-v1.png" alt="myknow 最新版取景框图标" width="96">
</p>

<h1 align="center">myknow</h1>

<p align="center">本机优先的知识素材库，把网页、图片和灵感保存下来，再在本地整理、检索和复用。</p>

<p align="center">
  <a href="https://github.com/mutuo12138/myknow/actions/workflows/ci.yml"><img src="https://github.com/mutuo12138/myknow/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/mutuo12138/myknow" alt="License"></a>
  <a href="https://github.com/mutuo12138/myknow/issues"><img src="https://img.shields.io/github/issues/mutuo12138/myknow" alt="Issues"></a>
  <a href="https://github.com/mutuo12138/myknow"><img src="https://img.shields.io/badge/platform-Windows%2010%2F11-2f81f7" alt="Platform"></a>
</p>

> 当前仓库是经过脱敏的普通版公开源码。myknow 默认在本机保存数据，不是托管式在线服务；影楼特供版源码不在本仓库公开范围内。

## 这是什么

最新稳定更新：2026-09-06。新增即时 AI 入队、用量与进度、完整提示词复制、视频本地播放和 Windows 照片复制；浏览器扩展升级到 0.7.7。详情见 [更新日志](CHANGELOG.md)。更新扩展后请在 Chrome/Edge 扩展管理页点击“重新加载”，再刷新来源网页。

myknow 是一个本机优先的知识素材库，面向需要长期收集图片、网页、文档和创意参考的人。它把“看到并保存”与“以后找回并使用”连接起来：

- 浏览器扩展主动保存当前网页、图片、视频引用和选中文字
- 本地 SQLite 保存索引，素材默认留在用户自己的磁盘
- 图片按 SHA-256 去重，可导入已有文件夹
- 支持文件夹、标签、颜色/亮度筛选和中文全文检索
- 可选的 OpenAI-compatible 视觉分析，默认关闭
- 原生 Windows 启动器、托盘运行方式和安装包构建脚本

## 快速开始

### 环境要求

- Windows 10/11
- Python 3.11+
- Node.js 20+
- Chrome 或 Edge（如果需要浏览器扩展）

### 从源码启动

```powershell
git clone https://github.com/mutuo12138/myknow.git
Set-Location myknow

py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt

Set-Location desktop-ui
npm ci
npm run build
Set-Location ..

python desktop.py
```

启动后打开 <http://127.0.0.1:8765>。Windows 用户也可以运行根目录下的 `启动素材中枢.ps1`。

### 安装浏览器扩展

1. 先启动 myknow 本机服务。
2. 打开 `chrome://extensions` 或 `edge://extensions`。
3. 开启“开发者模式”。
4. 选择“加载已解压的扩展程序”，指定仓库里的 `extension/` 目录。
5. 扩展只在用户主动点击、右键、拖放或使用快捷键时采集内容。

完整说明见 [`extension/README.md`](extension/README.md)。

## 项目结构

```text
backend/       本地 API、SQLite 访问、任务队列和 AI 适配器
desktop-ui/    React + Vite 桌面工作台
extension/     Chrome/Edge Manifest V3 浏览器扩展
packaging/     PyInstaller、Inno Setup 和便携版构建脚本
tests/         单元测试与合成验收夹具
docs/          架构、开源发布、路线图和维护文档
```

核心数据流：

```text
浏览器扩展 → 本机 API → SQLite 与本地素材 → worker 处理
                                      → React 工作台检索、预览和整理
```

更详细的设计边界见 [`ARCHITECTURE.md`](ARCHITECTURE.md) 和 [`PRODUCT.md`](PRODUCT.md)。

## 构建 Windows 安装包

```powershell
python packaging/build_installer.py
```

构建脚本会构建前端、生成 PyInstaller 应用、启动冻结程序进行健康检查和来源校验，并对输出执行脱敏扫描。安装包和便携包属于 Release 资产，不应提交到源码历史；完整流程见 [`docs/OPEN_SOURCE_RELEASE.md`](docs/OPEN_SOURCE_RELEASE.md)。

## 测试与质量门槛

```powershell
python -m unittest discover -s tests -p "test_*.py"
Set-Location desktop-ui
npm ci
npm run build
```

每次 push 和 Pull Request 都会运行 GitHub Actions，覆盖 Python 测试和前端生产构建。测试夹具使用独立的 `MUSE_VAULT_HOME`，不会写入正式素材库。

## 数据、安全与隐私

- 原始素材、数据库、缩略图、日志和 AI 配置默认保存在用户本机。
- AI 默认关闭；保存配置本身不会自动处理素材或产生请求。
- API Key 使用当前 Windows 用户的 DPAPI 加密保存，不通过浏览器扩展返回。
- 浏览器扩展只响应用户明确操作，不批量爬取、不绕过登录、不下载受保护的视频流。
- 公开仓库不得包含真实素材、数据库、日志、Cookie、API Key 或个人绝对路径。

报告安全问题请阅读 [`SECURITY.md`](SECURITY.md)，不要在公开 Issue 中粘贴凭据或真实用户数据。

## 文档导航

| 文档 | 用途 |
| --- | --- |
| [`docs/README.md`](docs/README.md) | 文档入口和推荐阅读顺序 |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | 模块、数据流、存储和安全边界 |
| [`PRODUCT.md`](PRODUCT.md) | 产品定位、用户目标和设计原则 |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | 当前能力与后续方向 |
| [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) | 本地开发、测试和提交工作流 |
| [`docs/ICON_GUIDE.md`](docs/ICON_GUIDE.md) | 最新品牌图标、尺寸和更新方法 |
| [`docs/OPEN_SOURCE_RELEASE.md`](docs/OPEN_SOURCE_RELEASE.md) | 脱敏、构建、发布和回滚流程 |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | 提交代码、测试和 Pull Request 规则 |
| [`SECURITY.md`](SECURITY.md) | 安全问题报告方式 |
| [`CHANGELOG.md`](CHANGELOG.md) | 版本变更记录 |

## 当前限制

- Windows 桌面启动器和安装包流程是当前公开版本的重点运行环境。
- 浏览器扩展需要用户手动加载解压目录，尚未接入浏览器商店发布流程。
- 安装包目前未做商业代码签名，Windows 可能显示“未知发布者”。
- AI 视觉分析依赖用户主动配置的兼容接口；本仓库不提供模型账号或 API Key。

## 参与贡献

欢迎提交 Bug、功能建议和文档改进。请先阅读 [`CONTRIBUTING.md`](CONTRIBUTING.md)，并使用 GitHub Issue / Pull Request 模板。

## 许可证

本项目采用 [`MIT License`](LICENSE)。软件按“现状”提供，不承担担保责任；再发布时请保留许可证与版权声明。
