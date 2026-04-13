"""统一材料包构建器测试"""
from pathlib import Path

import fitz
from PIL import Image

from src.services.evaluation.packet_builder import EvaluationPacketBuilder


def _write_pdf(path: Path, text: str) -> None:
    """写入简单 PDF，供 packet 合并测试使用"""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 96), text, fontsize=14)
    doc.save(path)
    doc.close()


def test_packet_builder_build_creates_packet_pdf_and_viewer(tmp_path: Path):
    """正文与附件应合并成统一 packet，并生成 viewer 资产"""
    source_pdf = tmp_path / "demo.pdf"
    attachment_png = tmp_path / "attachment.png"
    _write_pdf(source_pdf, "这是正文第一页")
    Image.new("RGB", (240, 160), color=(240, 248, 255)).save(attachment_png)

    builder = EvaluationPacketBuilder()
    assets = builder.build(
        output_dir=tmp_path,
        project_id="demo-project",
        source_file=str(source_pdf),
        source_name=source_pdf.name,
        attachments=[
            {
                "file_ref": str(attachment_png),
                "file_name": attachment_png.name,
                "doc_kind": "other_supporting_material",
            }
        ],
    )

    assert assets["packet_file"] == "projects/demo-project/evaluation_packet.pdf"
    assert (tmp_path / assets["packet_file"]).exists()
    assert (tmp_path / assets["page_map_file"]).exists()
    assert assets["viewer_file"] == "projects/demo-project/packet_viewer.html"
    assert (tmp_path / assets["viewer_file"]).exists()
    assert len(assets["page_map"]) == 2
    assert assets["page_map"][0]["source_kind"] == "proposal"
    assert assets["page_map"][1]["source_kind"] == "attachment"
    assert assets["page_map"][0]["start_page"] == 1
    assert assets["page_images"]
