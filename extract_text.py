import sys
from docx import Document

def extract_text(filepath):
    doc = Document(filepath)
    text = []
    # Dump tables
    for i, table in enumerate(doc.tables):
        if i == 3:
            for j, row in enumerate(table.rows):
                row_text = " | ".join([cell.text.replace('\n', ' ') for cell in row.cells])
                print(f"Row {j}: {row_text[:100]}")

pids = ["c06665dd2b8a4fd7b853c7adbc0805bd", "666cce99e92c4ddf9c78dbcd6744b4cf", "24858c17a8284d1f84f18da65f305010", "98440df4e0344e26b638f58f719c9ba6"]

for pid in pids:
    hts_path = f"/home/tdkx/ljh/Tech/data/任务书/{pid}.docx"
    print(f"\n==== {pid} Table 3 ====")
    extract_text(hts_path)

