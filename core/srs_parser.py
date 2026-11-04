from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from typing import Any

REQ_ID_RE = re.compile(r"\\b((?:REQ|FR|NFR|BR|UC|US|SRS|BUS)-?[A-Z0-9]+(?:[-_.][A-Z0-9]+)*)\\b", re.I)
KEYWORDS = ("shall", "must", "should", "required", "the system", "phải", "cần",
            "cho phép", "được phép", "không được", "hệ thống", "yêu cầu", "bắt buộc", "tự động")


def read_document(filename: str, content: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
        return "\\n".join(page.extract_text() or "" for page in reader.pages)
    if suffix == ".docx":
        from docx import Document
        doc = Document(io.BytesIO(content))
        lines = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                lines.append(" | ".join(c.text.strip() for c in row.cells))
        return "\\n".join(lines)
    if suffix in {".xlsx", ".xlsm"}:
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(content), data_only=True, read_only=True)
        lines = []
        for ws in wb.worksheets:
            lines.append(f"## {ws.title}")
            for row in ws.iter_rows(values_only=True):
                values = [str(v).strip() for v in row if v is not None and str(v).strip()]
                if values:
                    lines.append(" | ".join(values))
        return "\\n".join(lines)
    if suffix == ".csv":
        return "\\n".join(" | ".join(row) for row in csv.reader(io.StringIO(content.decode("utf-8-sig", errors="replace"))))
    if suffix in {".txt", ".md", ".rst", ".yaml", ".yml", ".json"}:
        return content.decode("utf-8-sig", errors="replace")
    raise ValueError(f"Unsupported file type: {suffix or 'unknown'}")


def extract_requirements(text: str, source: str = "") -> list[dict[str, Any]]:
    lines = [re.sub(r"\\s+", " ", x).strip() for x in text.splitlines()]
    lines = [x for x in lines if x]
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in lines:
        if not 18 <= len(line) <= 2500:
            continue
        match = REQ_ID_RE.search(line)
        bullet = bool(re.match(r"^(?:[-*•]|\\d+[.)])\\s+", line) and len(line) >= 35)
        if not (match or bullet or any(k in line.lower() for k in KEYWORDS)):
            continue
        if re.match(r"^(?:#{1,6}\\s*)?(?:contents|mục lục|revision history)\\b", line, re.I):
            continue
        key = match.group(1).upper().replace("_", "-") if match else f"REQ-{len(found)+1:03d}"
        cleaned = re.sub(r"^(?:[-*•]|\\d+[.)])\\s+", "", line).strip()
        cleaned = REQ_ID_RE.sub("", cleaned, count=1).strip(" :-–—") or line
        if key in seen:
            previous = next((r for r in found if r["req_key"] == key), None)
            if previous and cleaned not in previous["description"]:
                previous["description"] += "\\n" + cleaned
            continue
        seen.add(key)
        title = cleaned[:112].rstrip() + ("…" if len(cleaned) > 115 else "")
        found.append({"req_key": key, "title": title, "description": cleaned, "source": source})
    if not found:
        candidates = [x for x in lines if len(x) >= 55 and not x.startswith(("#", "|", "---"))]
        for i, line in enumerate(candidates[:150], start=1):
            found.append({"req_key": f"REQ-{i:03d}", "title": line[:112] + ("…" if len(line) > 115 else ""),
                          "description": line, "source": source})
    return found


def parse_srs(filename: str, content: bytes) -> tuple[str, list[dict[str, Any]]]:
    raw = read_document(filename, content)
    return raw, extract_requirements(raw, filename)
