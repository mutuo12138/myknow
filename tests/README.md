# Muse Vault 永久验收资产

本目录是项目证据，不是临时 QA 目录，不得在验收后删除。

- `test_p0_integrity.py`：P0-A 数据完整性回归测试。
- `acceptance/generate_fixtures.py`：确定性生成图片、网页、PDF 和视频引用样本。
- `acceptance/fixtures-manifest.json`：4 类 × 5 条样本清单。
- `acceptance/runs/`：每次完整验收的隔离数据库、日志和结果摘要。

所有测试必须设置独立的 `MUSE_VAULT_HOME`，禁止写入项目正式 `data/`。
