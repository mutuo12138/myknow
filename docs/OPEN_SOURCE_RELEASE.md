# 开源发布流程

## 发布前脱敏试炼

1. 从源码导出干净目录，不复制 `data/`、`releases/`、`.git/`、`.learnings/`、`.impeccable/`、`work/`、日志和用户素材。
2. 搜索本机路径、用户名、API Key、Cookie、Bearer 凭据和真实业务数据；发现后停止发布并修复。
3. 使用合成测试夹具运行后端测试和前端生产构建。
4. 用临时数据目录启动冻结程序，检查健康接口、来源校验和首页加载。
5. 对安装包和便携包计算 SHA-256，并在 GitHub Release 中发布校验值。

## 版本发布

```powershell
python packaging/build_installer.py
git tag v0.1.1
git push origin main --tags
```

安装包属于 Release 附件，不提交到源码仓库。Release 说明应包含版本、变更摘要、系统要求、SHA-256、已知限制和回滚方式。

## 数据边界

myknow 默认把数据库、索引、缩略图、素材和日志保存在用户本机。AI 配置只有在用户主动填写并触发分析时才使用；公开仓库和构建产物不应包含任何真实凭据或素材。
