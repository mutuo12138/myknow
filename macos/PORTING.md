# myknow macOS 适配路线

## 当前状态

本目录提供 Mac 开发环境初始化与启动脚本。业务源码来自 Windows 当前工作副本，尚未在真实 Mac 上运行；以下项目必须逐项完成和验收。

## 第一阶段：让开发版稳定运行

1. 设置目录：把 Windows 的 `%LOCALAPPDATA%` 逻辑改为 `~/Library/Application Support/myknow`。
2. Finder 定位：`backend/main.py` 的非 Windows 分支在 macOS 使用 `open -R <file>`，Linux 才使用 `xdg-open`。
3. 图标：从现有 SVG/PNG 生成 `.icns`，不要把 `.ico` 当作最终 Mac 图标。
4. 菜单栏：验证 `pystray`/PyObjC；关闭窗口、重新打开和彻底退出必须符合 macOS 习惯。
5. 浏览器扩展：在 macOS Chrome/Edge 中验证扩展加载、采集和本机 API 连接。

## 第二阶段：替换 Windows 专用能力

1. `clipboard_bridge.py` 的 CF_HDROP/Win32 剪贴板需要 macOS NSPasteboard 实现。
2. `file_drag.py` 的 OLE/DoDragDrop 不能在 macOS 使用；优先保留“在 Finder 中显示”和标准剪贴板方案。
3. `backend/ai_adapter.py` 当前非 Windows 分支只做 Base64，不满足正式密钥保护要求；改用 macOS Keychain，建议通过 `keyring` 封装。
4. 检查所有 PowerShell、Explorer、Windows 路径、ICO 和 Inno Setup 引用，建立平台分支。

## 第三阶段：打包与分发

1. 在 Mac 上使用 PyInstaller 生成 arm64 `.app`；PyInstaller 不是 Windows 到 macOS 的直接交叉打包器。
2. 先支持 Apple Silicon；确有 Intel 用户后再验证 x86_64 或 universal2，所有二进制依赖必须架构一致。
3. 公开分发使用 Developer ID Application 签名、Hardened Runtime、Apple 公证和 DMG。
4. 验证命令至少包括：`codesign --verify --deep --strict`、`spctl --assess --type execute`、`xcrun stapler validate`。

## 必测功能

- 新建空素材库、导入本地文件夹、复制托管与原位置引用。
- SQLite 建库、缩略图、搜索、回收站、恢复、导出。
- AI 配置保存、Keychain 读取、单图分析和错误日志脱敏。
- Finder 定位、剪贴板复制、原生窗口、菜单栏退出。
- Chrome/Edge 扩展采集、跨站限制和本机 API 健康检查。
- 应用重启、系统重启、路径包含中文和空格、无网络场景。

## 验收边界

当前迁移包只证明文件完整且开发脚本结构有效，不证明 Mac 运行、签名、公证或普通用户安装已经通过。
