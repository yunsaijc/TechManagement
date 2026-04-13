"""从 debug JSON 生成查重 HTML 报告。"""

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.services.plagiarism.report_builder import PlagiarismHtmlReportBuilder


def main() -> None:
    base_dir = BASE_DIR
    debug_path = base_dir / "debug_plagiarism" / "plagiarism_debug.json"
    output_path = base_dir / "debug_plagiarism" / "plagiarism_report.html"

    builder = PlagiarismHtmlReportBuilder()
    builder.build_from_debug_file(debug_path, output_path)
    print(f"[Plagiarism] HTML report generated: {output_path}")


if __name__ == "__main__":
    main()