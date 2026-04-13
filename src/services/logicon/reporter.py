import json

from src.common.models.logicon import LogicOnResult


class LogicOnReporter:
    def build_markdown(self, result: LogicOnResult) -> str:
        lines: list[str] = []
        lines.append("# 文档逻辑一致性核验报告")
        lines.append(f"doc_id: {result.doc_id}")
        lines.append(f"doc_kind: {result.doc_kind}")
        lines.append("")

        if not result.conflicts:
            lines.append("未发现明显逻辑冲突。")
            return "\n".join(lines)

        lines.append(f"发现冲突 {len(result.conflicts)} 条：")
        lines.append("")
        for c in result.conflicts:
            lines.append(f"## {c.conflict_id} {c.severity.value} {c.category.value}")
            lines.append(c.title)
            lines.append(c.description)
            if c.evidence:
                lines.append("")
                lines.append("证据：")
                for e in c.evidence:
                    page = f"页{e.page}" if e.page is not None else ""
                    sec = e.section_title or ""
                    head = " ".join([x for x in [page, sec] if x]).strip()
                    lines.append(f"- {head}")
                    if e.snippet:
                        lines.append(f"  {e.snippet}")
            lines.append("")

        return "\n".join(lines).strip()

    def build_json(self, result: LogicOnResult) -> str:
        return json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2)
