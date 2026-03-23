# PerfCheck 最小测试样本

这组样本用于验证 PerfCheck 的最小闭环能力：

1. 核心指标缩水
2. 研究内容删减
3. 预算大类挪移

## 文件说明

- declaration.txt: 人工构造的申报书文本
- task.txt: 人工构造的任务书文本
- request.json: 可直接用于 compare-text 接口的请求体

## 预期命中

使用该样本时，理论上应命中以下规则：

1. R-IND-001: 论文指标由 10 篇降到 6 篇
2. R-IND-001: 营收指标由 1000 万元降到 600 万元
3. R-RSCH-001: 研究内容删减
4. R-BUD-001: 设备费、管理费等预算比例明显变动
5. R-BUD-002: 管理费异常上升
6. R-BUD-003: 预算结构相似度偏低

## 调用示例

```bash
curl -X POST "http://localhost:8000/api/v1/perfcheck/compare-text" \
  -H "Content-Type: application/json" \
  -d @tests/fixtures/perfcheck/request.json
```

## 说明

当前最稳妥的最小测试方式是 compare-text。

原因：现有文件接口依赖 PDF/DOCX 解析器，而这组样本是人工构造文本，适合先验证 PerfCheck 核心规则链路是否跑通。
