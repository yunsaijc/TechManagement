import asyncio
import json
import os
import sys

# 设置路径，确保能导入 src
sys.path.append(os.path.abspath("/home/tdkx/ljh/Tech"))

from src.services.perfcheck import get_perfcheck_service

async def test_perfcheck():
    # 读取测试数据
    with open("/home/tdkx/ljh/Tech/tests/perfcheck/request.json", "r", encoding="utf-8") as f:
        request_data = json.load(f)
    
    service = get_perfcheck_service()
    
    print("Starting PerfCheck comparison...")
    result = await service.compare_text(
        project_id=request_data["project_id"],
        declaration_text=request_data["declaration_text"],
        task_text=request_data["task_text"],
        budget_shift_threshold=request_data.get("budget_shift_threshold", 0.10)
    )
    
    print("\n=== PerfCheck Result ===")
    print(f"Project ID: {result.project_id}")
    print(f"Task ID: {result.task_id}")
    print(f"Overall Score: {result.overall_score:.2f}")
    
    print("\n--- Metrics Risks ---")
    for m in result.metrics_risks:
        print(f"[{m.risk_level}] {m.type}: {m.apply_value} -> {m.task_value} | {m.reason}")
        
    print("\n--- Content Risks ---")
    for c in result.content_risks:
        print(f"[{c.risk_level}] Content: {c.apply_text[:50]}... | Coverage: {c.coverage_score:.2%} | {c.reason}")
        
    print("\n--- Budget Risks ---")
    for b in result.budget_risks:
        print(f"[{b.risk_level}] {b.type}: {b.apply_ratio:.1%} -> {b.task_ratio:.1%} | {b.reason}")

if __name__ == "__main__":
    asyncio.run(test_perfcheck())
