
# 启动服务
uv run python -m src.app.main


# 20-review

# 形式审查
curl -sS -X POST "http://127.0.0.1:8888/api/v1/review" -F "file=@/home/tdkx/workspace/data/审查功能测试用典型项目信息/202520077/1757064464235.pdf" -F "document_type=award_contributor" -F 'metadata={"project_id":"202520077","source":"curl-test"}' -F "enable_llm_analysis=true"

# 查重
curl -sS -X POST "http://127.0.0.1:8888/api/v1/plagiarism"     -F "files=@/home/tdkx/workspace/data/查重用例Word文档/相似组1-A.docx"     -F "files=@/home/tdkx/workspace/data/查重用例Word文档/相似组1-B.docx"     -F "threshold=0.5"     -F "threshold_high=0.8"     -F "threshold_medium=0.5"     -F "doc_type=default"     -F "debug=true"


# 30-grouping

# 分组
curl -sS -X POST http://127.0.0.1:8888/api/v1/grouping/projects     -H 'Content-Type: application/json'     -d '{"max_per_group": 15}'

# 专家匹配
# 还没做


# 40-evaluation

# 辅助评审
curl -X POST 'http://127.0.0.1:8888/api/v1/evaluation/evaluate/file' -F 'file=@/home/tdkx/workspace/data/申报书正文/8170da049eae4caf88322ef03f410310.pdf' -F 'project_id=8170da049eae4caf88322ef03f410310'  -F 'enable_highlight=true'  -F 'enable_industry_fit=false' -F 'enable_benchmark=false'  -F 'enable_chat_index=false'
