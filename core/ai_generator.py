from __future__ import annotations

import json
import re
import uuid
from typing import Any

from core.ai_provider import get_ai_provider
from core.test_generator import validate_steps_json


REQUIREMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "req_key": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "actor": {"type": "string"},
                    "preconditions": {"type": "array", "items": {"type": "string"}},
                    "business_rules": {"type": "array", "items": {"type": "string"}},
                    "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
                    "source_ref": {"type": "string"},
                },
                "required": ["req_key","title","description","actor","preconditions","business_rules","acceptance_criteria","source_ref"],
            },
        }
    },
    "required": ["requirements"],
}

TEST_CASE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "test_cases": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "req_key": {"type": "string"},
                    "title": {"type": "string"},
                    "test_type": {"type": "string"},
                    "priority": {"type": "string"},
                    "preconditions": {"type": "string"},
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "action": {"type": "string"},
                                "page": {"type": "string"},
                                "target": {"type": "string"},
                                "value": {"type": "string"},
                                "expected": {"type": "string"},
                                "description": {"type": "string"},
                            },
                            "required": ["action"],
                        },
                    },
                    "expected_result": {"type": "string"},
                    "source_ref": {"type": "string"},
                    "automation_level": {"type": "string"},
                },
                "required": ["req_key","title","test_type","priority","preconditions","steps","expected_result","source_ref","automation_level"],
            },
        }
    },
    "required": ["test_cases"],
}


def _chunk_text(text: str, max_chars: int = 14000) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        pieces = [paragraph[i:i + max_chars] for i in range(0, len(paragraph), max_chars)] if len(paragraph) > max_chars else [paragraph]
        for piece in pieces:
            if current and len(current) + len(piece) + 2 > max_chars:
                chunks.append(current)
                current = piece
            else:
                current = f"{current}\n\n{piece}".strip()
    if current:
        chunks.append(current)
    return chunks or [text[:max_chars]]


def extract_requirements_with_ai(text: str, source: str = "") -> list[dict[str, Any]]:
    """Use Gemini to extract traceable requirements; never invent missing evidence."""
    if not str(text).strip():
        raise ValueError("Tài liệu không có nội dung văn bản để phân tích.")
    provider = get_ai_provider()
    chunks = _chunk_text(str(text))
    extracted: list[dict[str, Any]] = []
    seen: set[str] = set()
    for chunk_index, chunk in enumerate(chunks, start=1):
        prompt = {
            "task": "Extract explicit, testable business and system requirements from this source excerpt.",
            "source_document": source,
            "chunk": f"{chunk_index}/{len(chunks)}",
            "rules": [
                "Only extract requirements explicitly supported by the supplied text.",
                "Do not turn headings, table-of-contents entries, examples or explanatory prose into requirements.",
                "Preserve original requirement IDs. If an ID is absent, use an empty req_key; do not invent an official ID.",
                "Keep one requirement per item. Merge repeated fragments only when they clearly describe the same requirement.",
                "Write actor, preconditions, business rules and acceptance criteria only when supported by the source; otherwise use empty strings/arrays.",
                "source_ref must be an exact section heading, clause number or short source phrase visible in the excerpt. Never invent page numbers.",
                "Return Vietnamese when the source is Vietnamese. Keep legal/business terminology from the source.",
            ],
            "source_excerpt": chunk,
        }
        data = provider.generate_json(json.dumps(prompt, ensure_ascii=False), REQUIREMENT_SCHEMA, 8192)
        items = data.get("requirements", []) if isinstance(data, dict) else []
        if not isinstance(items, list):
            raise ValueError("Gemini trả về cấu trúc requirements không hợp lệ.")
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            description = str(item.get("description") or "").strip()
            if not title or not description:
                continue
            req_key = str(item.get("req_key") or "").strip()
            normalized = req_key.casefold() if req_key else re.sub(r"\W+", " ", title.casefold()).strip()
            if normalized in seen:
                continue
            seen.add(normalized)
            metadata = {
                "actor": str(item.get("actor") or "").strip(),
                "preconditions": item.get("preconditions") if isinstance(item.get("preconditions"), list) else [],
                "business_rules": item.get("business_rules") if isinstance(item.get("business_rules"), list) else [],
                "acceptance_criteria": item.get("acceptance_criteria") if isinstance(item.get("acceptance_criteria"), list) else [],
                "source_ref": str(item.get("source_ref") or "").strip(),
                "extraction_method": "gemini",
            }
            extracted.append({
                "req_key": req_key,
                "title": title,
                "description": description,
                "source": source,
                "metadata_json": json.dumps(metadata, ensure_ascii=False),
            })
    return extracted


def generate_cases_with_ai(requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Draft requirement-linked cases using semantic targets, not CSS/XPath selectors."""
    if not requirements:
        return []
    provider = get_ai_provider()
    enriched_requirements: list[dict[str, Any]] = []
    for requirement in requirements:
        enriched = dict(requirement)
        metadata_raw = enriched.get("metadata_json")
        if isinstance(metadata_raw, str) and metadata_raw.strip():
            try:
                metadata = json.loads(metadata_raw)
                if isinstance(metadata, dict):
                    enriched.update(metadata)
            except json.JSONDecodeError:
                pass
        enriched_requirements.append(enriched)
    # Small batches reduce free-tier quota spikes and keep each answer reviewable.
    batches = [enriched_requirements[i:i + 5] for i in range(0, len(enriched_requirements), 5)]
    generated: list[dict[str, Any]] = []
    for batch_index, batch in enumerate(batches, start=1):
        prompt = {
            "task": "Design traceable software test cases from the supplied reviewed requirements.",
            "batch": f"{batch_index}/{len(batches)}",
            "rules": [
                "Do not invent behavior, role names, data values, endpoints or UI elements.",
                "Cover positive, negative, boundary, authorization, integration and state-transition paths where relevant to the requirement.",
                "Every case must cite exactly one or more supplied req_key values and retain source_ref evidence.",
                "Use Vietnamese titles and steps when the requirement is Vietnamese.",
                "Each step must use the semantic action model. Never write CSS, XPath, DOM selectors or locator strings.",
                "A target is a stable business identifier such as 'guarantee.create_button' or 'guarantee.amount'.",
                "Use action='navigate' with page='ccm.guarantee.list' for route navigation when supported by the requirements.",
                "If a UI target, route or expected state is not evidenced, use action='manual' and state what must be mapped or confirmed.",
                "Use \u0024{data.field_name} placeholders instead of fabricated customer, contract, account or monetary data.",
                "automation_level must be 'automatable', 'partially_automatable' or 'manual'. Mark automatable only if every needed target and assertion is explicit and mappable; otherwise choose partially_automatable or manual.",
                "Allowed semantic actions: navigate, click, fill, select_option, check, uncheck, expect_visible, expect_hidden, expect_text, expect_url, wait_for, assert_state, manual.",
                "A test case must have at least one step and a concrete expected_result. Avoid generic filler cases.",
            ],
            "requirements": batch,
        }
        data = provider.generate_json(json.dumps(prompt, ensure_ascii=False), TEST_CASE_SCHEMA, 8192)
        items = data.get("test_cases", []) if isinstance(data, dict) else []
        if not isinstance(items, list):
            raise ValueError("Gemini trả về cấu trúc test_cases không hợp lệ.")
        for item in items:
            if not isinstance(item, dict):
                continue
            req_key = str(item.get("req_key") or "").strip()
            if req_key not in {str(req.get("req_key") or "") for req in batch}:
                continue
            try:
                steps = validate_steps_json(item.get("steps", []))
            except (ValueError, TypeError):
                steps = [{"action": "manual", "description": "Rà soát và chuẩn hóa các bước nghiệp vụ trước khi thực thi."}]
            # Guardrail: AI-generated cases are semantic. Reject selector leakage.
            if any(step.get("selector") or step.get("xpath") or step.get("css") for step in steps):
                steps = [{"action": "manual", "description": "Bước sinh ra có chứa selector trực tiếp; cần chuyển sang semantic target đã được xác minh."}]
            automation_level = str(item.get("automation_level") or "manual").lower()
            if automation_level not in {"automatable", "partially_automatable", "manual"}:
                automation_level = "manual"
            if any(step.get("action") == "manual" for step in steps) and automation_level == "automatable":
                automation_level = "partially_automatable"
            generated.append({
                "case_key": f"AI-{uuid.uuid4().hex[:10].upper()}",
                "req_key": req_key,
                "title": str(item.get("title") or "Test Case cần rà soát"),
                "test_type": str(item.get("test_type") or "Functional"),
                "priority": str(item.get("priority") or "Medium"),
                "preconditions": str(item.get("preconditions") or ""),
                "steps": steps,
                "expected_result": str(item.get("expected_result") or ""),
                "source_ref": str(item.get("source_ref") or ""),
                "automation_level": automation_level,
            })
    return generated
