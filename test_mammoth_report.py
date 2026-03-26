"""测试 mammoth 报告生成功能"""
import asyncio
import sys
from pathlib import Path

# 添加 src 到路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.services.plagiarism.agent import PlagiarismAgent


async def test_mammoth_report():
    """测试 mammoth 报告生成"""
    
    # 查找测试用的 DOCX 文件
    data_dir = Path("../data/查重用例Word文档")
    docx_files = list(data_dir.glob("*.docx"))
    
    if len(docx_files) < 2:
        print(f"找到 {len(docx_files)} 个 DOCX 文件，需要至少 2 个")
        return
    
    # 使用前两个文件
    doc1_path = docx_files[0]
    doc2_path = docx_files[1]
    
    print(f"测试文件 1: {doc1_path}")
    print(f"测试文件 2: {doc2_path}")
    
    # 读取文件
    doc1_bytes = doc1_path.read_bytes()
    doc2_bytes = doc2_path.read_bytes()
    
    # 创建 agent
    agent = PlagiarismAgent(
        threshold=0.5,
        threshold_high=0.8,
        threshold_medium=0.5,
        debug=True,  # 启用 debug 模式以生成报告
    )
    
    # 准备文件列表
    files = [
        (doc1_path.name, doc1_bytes),
        (doc2_path.name, doc2_bytes),
    ]
    
    # 准备文件路径字典（用于 mammoth 报告）
    file_paths = {
        doc1_path.name: str(doc1_path),
        doc2_path.name: str(doc2_path),
    }
    
    print("\n开始查重...")
    result = await agent.check(files, file_paths)
    
    print(f"\n查重完成!")
    print(f"总对数: {result.total_pairs}")
    print(f"高相似度: {len(result.high_similarity)} 对")
    print(f"中等相似度: {len(result.medium_similarity)} 对")
    print(f"低相似度: {len(result.low_similarity)} 对")
    
    # 检查生成的报告文件
    debug_dir = Path("debug_plagiarism")
    html_report = debug_dir / "plagiarism_report.html"
    mammoth_report = debug_dir / "plagiarism_report_mammoth.html"
    
    print(f"\n生成的报告文件:")
    print(f"  - 普通报告: {html_report} ({html_report.exists()})")
    print(f"  - Mammoth报告: {mammoth_report} ({mammoth_report.exists()})")
    
    if mammoth_report.exists():
        content = mammoth_report.read_text(encoding="utf-8")
        has_table = "<table" in content
        has_hit = "class=\"hit\"" in content or 'class="hit"' in content
        print(f"\nMammoth 报告检查:")
        print(f"  - 包含表格: {has_table}")
        print(f"  - 包含高亮标记: {has_hit}")
        
        if has_table:
            # 统计表格数量
            table_count = content.count("<table")
            print(f"  - 表格数量: {table_count}")
    
    print("\n测试完成!")


if __name__ == "__main__":
    asyncio.run(test_mammoth_report())
