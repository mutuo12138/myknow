# Icon Guide

## 当前最新版

公开仓库当前采用 2026-08-25 生成的“Viewfinder / 取景框”视觉作为 myknow 主品牌图标：

- 源图：`packaging/assets/icon-redesign-20260825/myknow-icon-viewfinder-v1.png`
- GitHub README 展示：同一张 PNG
- Windows 应用图标：`packaging/assets/myknow.ico`
- ICO 尺寸：16、32、48、64、128、256

旧的文件夹/素材卡片方向仍保留在历史素材中，但不再作为公开 README 的主展示图标。

## 重新生成 ICO

先安装打包依赖，再运行：

```powershell
python -m pip install -r packaging/requirements-packaging.txt
python packaging/update_icon.py
```

脚本从最新版 PNG 生成多尺寸 ICO，不修改原始 PNG。更新后请运行 `git diff --check`、前端构建和 Windows 打包验收。

## 更新规则

- README、Windows 打包配置和发布说明必须引用同一套主品牌图标。
- 不要把影楼特供版专用资产混入普通版公开仓库。
- 新图标先保留带日期的源文件目录，再更新生成后的 `myknow.ico`，方便回溯来源。
- 图标不放置 API Key、用户素材或机器路径等敏感信息。
