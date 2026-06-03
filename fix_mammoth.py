import re

path = "/home/tdkx/ljh/Tech/src/services/plagiarism/mammoth_report_builder.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Replace the conflict region with a resolved version
conflict_pattern = re.compile(r"<<<<<<< HEAD\n(.*?)\n=======\n(.*?)\n>>>>>>> main\n", re.DOTALL)

def replacer(match):
    return """            similarity = float(segment.get("similarity_score", segment.get("similarity", 1.0)) or 0.0)
            result = (match_results or {}).get(match_id)
            match_type = segment.get("match_type", "exact")
            locate_mode = result.get("mode") if result else "miss"

            all_sources = segment.get("sources", [])
            unique_docs = []
            seen_docs = set()
            doc_hit_count = {}
            doc_score = {}
            for source in all_sources:
                doc = str(source.get("doc") or "")
                if not doc:
                    continue
                if doc not in seen_docs:
                    unique_docs.append(doc)
                    seen_docs.add(doc)
                doc_hit_count[doc] = int(doc_hit_count.get(doc, 0)) + 1
                score_val = float(source.get("similarity_score", similarity) or 0.0)
                doc_score[doc] = max(float(doc_score.get(doc, 0.0)), score_val)

            source_doc_count = len(unique_docs)
            source_piece_count = len(all_sources)
            top_doc = ""
            if unique_docs:
                top_doc = sorted(
                    unique_docs,
                    key=lambda d: (-float(doc_score.get(d, 0.0)), -int(doc_hit_count.get(d, 0)), d),
                )[0]
            source_info = f"主来源: {html.escape(top_doc)}" if top_doc else "主来源: -"

            source_badge = ""
            if source_doc_count > 1:
                source_badge = f'<span class="pill" style="padding: 2px 6px; font-size: 10px;">{source_doc_count}个来源文档</span>'
            elif source_piece_count > 1:
                source_badge = f'<span class="pill" style="padding: 2px 6px; font-size: 10px;">{source_piece_count}个来源片段</span>'

            type_badge = ""
            if match_type == "similar":
                type_badge = '<span class="pill" style="background:#fff3cd;color:#856404;border-color:#ffeeba">形似</span>'
            
            locate_badge = ""
            if locate_mode == "exact":
                locate_badge = '<span class="pill" style="background:#d4edda;color:#155724;border-color:#c3e6cb">精确定位</span>'
            elif locate_mode == "fuzzy":
                locate_badge = '<span class="pill" style="background:#cce5ff;color:#004085;border-color:#b8daff">模糊定位</span>'
            elif locate_mode == "miss":
                locate_badge = '<span class="pill" style="background:#f8d7da;color:#721c24;border-color:#f5c6cb">定位失败</span>'

            template_badge = '<span class="template-badge">模板</span>' if is_template else ''
            
            cards.append(f'''<button class="nav-item" data-match-id="{match_id}" data-template="{1 if is_template else 0}" data-type="{html.escape(match_type)}" data-locate="{html.escape(locate_mode or '')}">
                <div class="nav-header">#{display_idx} {template_badge} {type_badge} {locate_badge} {source_badge}</div>
                <div class="nav-text">{html.escape(primary_text)}...</div>
                <small>相似度 {similarity:.2f} · {source_info}</small>
            </button>''')
"""

new_content = conflict_pattern.sub(replacer, content)
with open(path, "w", encoding="utf-8") as f:
    f.write(new_content)

print("Fixed conflict.")
