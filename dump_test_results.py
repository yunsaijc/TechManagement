import asyncio
import sys
import os
from src.services.perfcheck.parser import PerfCheckParser

async def test_extraction(project_id, out_dir):
    sbs_path = f"/home/tdkx/ljh/Tech/data/perfcheck_samples_2025_docx/sbs/{project_id}.docx"
    hts_path = f"/home/tdkx/ljh/Tech/data/perfcheck_samples_2025_docx/hts/{project_id}.docx"

    parser = PerfCheckParser()

    print(f"====== Processing Project: {project_id} ======")
    try:
        with open(sbs_path, "rb") as f:
            sbs_data = f.read()
        sbs_res = await parser.parse_to_schema(sbs_data, "docx", doc_kind="declaration")
    except Exception as e:
        print(f"Failed to parse SBS: {e}")
        sbs_res = None

    try:
        with open(hts_path, "rb") as f:
            hts_data = f.read()
        hts_res = await parser.parse_to_schema(hts_data, "docx", doc_kind="task")
    except Exception as e:
        print(f"Failed to parse HTS: {e}")
        hts_res = None

    out_lines = []
    out_lines.append(f"# Project: {project_id}\n")

    if sbs_res:
        out_lines.append("## 1. SBS (申报书) Extracted")
        out_lines.append("### 1.1 Metrics (指标)")
        for m in sbs_res.performance_targets:
            out_lines.append(f"- {m.type}: {m.value} {m.unit} ({m.text})")
        
        out_lines.append("\n### 1.2 Research Contents (研究内容)")
        for rc in sbs_res.research_contents:
            text = rc.text.replace("\n", " ")
            out_lines.append(f"- {text[:300]}...")
            
        out_lines.append("\n### 1.3 Budgets (预算)")
        if sbs_res.budget:
            for b in sbs_res.budget.items:
                out_lines.append(f"- {b.type}: {b.amount}")
                
        out_lines.append("\n### 1.4 Team Members (团队成员)")
        if sbs_res.basic_info and sbs_res.basic_info.team_members:
            for t in sbs_res.basic_info.team_members:
                out_lines.append(f"- {t.name}, {t.duty}")

    if hts_res:
        out_lines.append("\n## 2. HTS (任务书) Extracted")
        out_lines.append("### 2.1 Metrics (指标)")
        for m in hts_res.performance_targets:
            out_lines.append(f"- {m.type}: {m.value} {m.unit} ({m.text})")
            
        out_lines.append("\n### 2.2 Research Contents (研究内容)")
        for rc in hts_res.research_contents:
            text = rc.text.replace("\n", " ")
            out_lines.append(f"- {text[:300]}...")
            
        out_lines.append("\n### 2.3 Budgets (预算)")
        if hts_res.budget:
            for b in hts_res.budget.items:
                out_lines.append(f"- {b.type}: {b.amount}")
                
        out_lines.append("\n### 2.4 Team Members (团队成员)")
        if hts_res.basic_info and hts_res.basic_info.team_members:
            for t in hts_res.basic_info.team_members:
                out_lines.append(f"- {t.name}, {t.duty}")

    out_file = os.path.join(out_dir, f"{project_id}.md")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n".join(out_lines))
    print(f"Saved to {out_file}")

async def main():
    manifest_path = "/home/tdkx/ljh/Tech/data/perfcheck_samples_2025_docx/manifest.txt"
    out_dir = "/home/tdkx/ljh/Tech/debug_perfcheck/test_results_10_samples"
    
    with open(manifest_path, "r") as f:
        projects = [line.strip() for line in f if line.strip()]
        
    for pid in projects:
        await test_extraction(pid, out_dir)

if __name__ == "__main__":
    asyncio.run(main())
