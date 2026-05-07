"""统一材料包构建器测试"""
import zipfile
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


def _write_minimal_docx(path: Path, text: str) -> None:
    """写入最小可解析 docx，供 packet 合并测试使用"""
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body>"
        "</w:document>"
    )
    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types_xml)
        archive.writestr("_rels/.rels", rels_xml)
        archive.writestr("word/document.xml", document_xml)


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


def test_packet_builder_proposal_prefers_sibling_pdf_over_docx_fallback(tmp_path: Path):
    """正文同目录有同名 pdf 时，packet 应优先使用原始 pdf"""
    proposal_docx = tmp_path / "demo.docx"
    proposal_pdf = tmp_path / "demo.pdf"
    _write_minimal_docx(proposal_docx, "这是 docx 正文")
    _write_pdf(proposal_pdf, "这是 pdf 正文")

    builder = EvaluationPacketBuilder()
    assets = builder.build(
        output_dir=tmp_path,
        project_id="demo-project",
        source_file=str(proposal_docx),
        source_name=proposal_docx.name,
        attachments=[],
    )

    assert assets["page_map"][0]["source_file"] == str(proposal_docx)
    assert assets["page_map"][0]["merge_mode"] == "pdf"
    assert assets["page_map"][0]["page_count"] == 1
