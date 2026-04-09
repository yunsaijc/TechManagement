
# 启动服务
uv run python -m src.app.main


# 20-review

# 形式审查-单个文件上传
curl -sS -X POST "http://127.0.0.1:8888/api/v1/review" -F "file=@/home/tdkx/workspace/data/审查功能测试用典型项目信息/202520077/1757064464235.pdf" -F "document_type=award_contributor" -F 'metadata={"project_id":"202520077","source":"curl-test"}' -F "enable_llm_analysis=true"

# 形式审查-按照指南代码批量查
curl -sS -X POST "http://127.0.0.1:8888/api/v1/review/batches" \
    -H "Content-Type: application/json" \
    -d '{
      "zxmc": "db832d940a2843e6b3c33970336d0e9e",
      "limit": 3,
      "notice_url":
  "https://kjt.hebei.gov.cn/hebkjt/xwzx15/tzgg35/sttz15/2026021118105729745/index.html"
    }'

# 查重
curl -sS -X POST "http://127.0.0.1:8888/api/v1/plagiarism"     -F "files=@/home/tdkx/workspace/data/查重用例Word文档/相似组1-A.docx"     -F "files=@/home/tdkx/workspace/data/查重用例Word文档/相似组1-B.docx"     -F "threshold=0.5"     -F "threshold_high=0.8"     -F "threshold_medium=0.5"     -F "doc_type=default"     -F "debug=true"

# 查重-批量查重
curl -X POST 'http://127.0.0.1:8888/api/v1/plagiarism/by-guide-codes' \
    -F 'guide_codes=["c2f3b7b1f9534463ad726e6936c91859","959c8e453dd942ddb72f0ef52c07342f","7581bc8d6d564153848fcb5d14b1942e"]' \
    -F 'doc_type=hebei_nsfc_2026' \
    -F 'limit=10' \
    -F 'max_concurrency=3' \
    -F 'debug=true'


# 查重 - 图片查重建库
reset=true; while true; do r=$(curl -s -X POST 'http://127.0.0.1:8888/api/v1/plagiarism/image/corpus/build-batch' \
    -F 'corpus_path=/home/tdkx/workspace/tech/data/corpus_local/sbs_5000' \
    -F 'limit=300' -F "reset_cursor=${reset}"); \
    echo "$r"; has_more=$(echo "$r" | UV_CACHE_DIR=/tmp/.uv-cache uv run python -c "import sys,json;print(json.load(sys.stdin)['data']['has_more'])"); [ "$has_more" = "False" ] && break; reset=false; done


# 查重-批量图片查重
curl -s -X POST 'http://127.0.0.1:8888/api/v1/plagiarism/image/by-guide-codes' \
    -F 'guide_codes=["c2f3b7b1f9534463ad726e6936c91859",
      "959c8e453dd942ddb72f0ef52c07342f",
      "7581bc8d6d564153848fcb5d14b1942e"]' \
    -F 'limit=20' -F 'read_remote_if_missing=true' \
    -F 'top_k_coarse=80' -F 'top_k_final=8' \
    -F 'verify_workers=6' -F 'debug=true'





# 30-grouping

# 分组 - 代码写死了一批数据，对那批数据进行分组，按照每组15个项目分组
curl -sS -X POST http://127.0.0.1:8888/api/v1/grouping/projects     -H 'Content-Type: application/json'     -d '{"max_per_group": 15}'

# 分组 - 按照指南代码分组
curl -sS -X POST 'http://127.0.0.1:8888/api/v1/grouping/projects' \
    -H 'Content-Type: application/json' \
    -d '{
      "guide_codes": [
        "c2f3b7b1f9534463ad726e6936c91859",
        "959c8e453dd942ddb72f0ef52c07342f",
        "7581bc8d6d564153848fcb5d14b1942e"
      ],
      "min_per_group": 3,
      "max_per_group": 15
    }'


# 专家匹配
# 还没做


# 40-evaluation

# 辅助评审
curl -X POST 'http://127.0.0.1:8888/api/v1/evaluation/evaluate/file' -F 'file=@/home/tdkx/workspace/data/申报书正文/8170da049eae4caf88322ef03f410310.pdf' -F 'project_id=8170da049eae4caf88322ef03f410310'  -F 'enable_highlight=true'  -F 'enable_industry_fit=false' -F 'enable_benchmark=false'  -F 'enable_chat_index=false'

# 按照指南代码评审
curl -X POST 'http://127.0.0.1:8888/api/v1/evaluation/by-guide' \
    -H 'Content-Type: application/json' \
    -d '{
      "zndm": "c2f3b7b1f9534463ad726e6936c91859",
      "limit": 10,
      "enable_highlight": true,
      "enable_industry_fit": false,
      "enable_benchmark": false,
      "enable_chat_index": true,
      "concurrency": 3
    }'
