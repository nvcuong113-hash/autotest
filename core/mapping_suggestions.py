from __future__ import annotations

import re
import unicodedata
from typing import Any


def _slug(value: Any, fallback: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return (text[:60] or fallback).strip("_")


def build_mapping_suggestions(
    inspection: dict[str, Any] | None,
    page_id: str,
) -> list[dict[str, Any]]:
    """Build deterministic, explicitly unverified mapping drafts from observed DOM only.

    This helper does not infer business behavior and does not mark any locator verified.
    Every locator is based on an Inspector-provided selector or observed accessible label,
    placeholder, role/name, or visible text.
    """
    inspection = inspection or {}
    rows: list[dict[str, Any]] = []
    used_ids: set[str] = set()

    def add(
        *,
        element_type: str,
        label: str,
        target_hint: str,
        strategy: str,
        locator_value: str,
        locator_name: str = "",
        evidence: str,
    ) -> None:
        if not locator_value:
            return
        base = f"{page_id}.{element_type}.{_slug(target_hint, 'element')}"
        target_id = base
        suffix = 2
        while target_id in used_ids:
            target_id = f"{base}_{suffix}"
            suffix += 1
        used_ids.add(target_id)
        rows.append({
            "include": True,
            "target_id": target_id,
            "element_type": element_type,
            "element_label": label[:180],
            "locator_by": strategy,
            "locator_value": locator_value[:500],
            "locator_name": locator_name[:180],
            "verified": False,
            "evidence": evidence[:700],
        })

    for item in inspection.get("inputs", []) or []:
        if not isinstance(item, dict) or item.get("disabled"):
            continue
        tag = str(item.get("tag") or "input").lower()
        input_type = str(item.get("type") or "").lower()
        if input_type in {"hidden", "password", "submit", "button", "reset"}:
            continue
        selector = str(item.get("suggested_selector") or "").strip()
        labels = item.get("labels") or []
        label = str(
            item.get("aria_label")
            or (labels[0] if labels else "")
            or item.get("placeholder")
            or item.get("name")
            or item.get("id")
            or f"{tag}_{item.get('index', '')}"
        ).strip()
        if selector:
            strategy, locator_value, locator_name = "css", selector, ""
        elif item.get("aria_label"):
            strategy, locator_value, locator_name = "label", str(item["aria_label"]), ""
        elif labels:
            strategy, locator_value, locator_name = "label", str(labels[0]), ""
        elif item.get("placeholder"):
            strategy, locator_value, locator_name = "placeholder", str(item["placeholder"]), ""
        else:
            continue
        hint = item.get("name") or item.get("id") or item.get("aria_label") or (labels[0] if labels else "") or item.get("placeholder") or f"{tag}_{item.get('index', '')}"
        evidence = (
            f"Inspector observed input tag={tag}, type={input_type}, "
            f"id={item.get('id','')}, name={item.get('name','')}, "
            f"placeholder={item.get('placeholder','')}, aria_label={item.get('aria_label','')}, "
            f"labels={labels}; URL={inspection.get('final_url','')}"
        )
        add(
            element_type="field",
            label=label,
            target_hint=hint,
            strategy=strategy,
            locator_value=locator_value,
            locator_name=locator_name,
            evidence=evidence,
        )

    for item in inspection.get("buttons", []) or []:
        if not isinstance(item, dict) or item.get("disabled"):
            continue
        tag = str(item.get("tag") or "button").lower()
        visible_text = str(item.get("aria_label") or item.get("text") or item.get("title") or "").strip()
        selector = str(item.get("suggested_selector") or "").strip()
        if selector:
            strategy, locator_value, locator_name = "css", selector, ""
        elif item.get("aria_label") or item.get("text") or item.get("title"):
            strategy, locator_value, locator_name = "role", "button", visible_text
        else:
            continue
        hint = visible_text or item.get("type") or f"button_{item.get('index', '')}"
        evidence = (
            f"Inspector observed button tag={tag}, text={item.get('text','')}, "
            f"aria_label={item.get('aria_label','')}, title={item.get('title','')}, "
            f"type={item.get('type','')}; URL={inspection.get('final_url','')}"
        )
        add(
            element_type="button",
            label=visible_text or tag,
            target_hint=hint,
            strategy=strategy,
            locator_value=locator_value,
            locator_name=locator_name,
            evidence=evidence,
        )

    return rows
