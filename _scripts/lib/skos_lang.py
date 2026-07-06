"""Shared helpers for SKOS language-keyed lexical properties."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

DEFAULT_DISPLAY_LANG = "en"


def is_lang_key(tag: Any) -> bool:
    return isinstance(tag, str) and tag.strip() != ""


def _stripped(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def sanitize_lang_string_map(block: Optional[dict]) -> Optional[Dict[str, str]]:
    if not isinstance(block, dict):
        return None

    cleaned: Dict[str, str] = {}
    for lang, value in block.items():
        if not is_lang_key(lang):
            continue
        text = _stripped(value)
        if text:
            cleaned[lang] = text
    return cleaned or None


def sanitize_lang_alt_label_map(block: Optional[dict]) -> Optional[Dict[str, List[dict]]]:
    if not isinstance(block, dict):
        return None

    cleaned: Dict[str, List[dict]] = {}
    for lang, values in block.items():
        if not is_lang_key(lang) or not isinstance(values, list):
            continue
        labels: List[dict] = []
        seen = set()
        for value in values:
            if isinstance(value, dict):
                text = _stripped(value.get("label"))
            else:
                text = _stripped(value)
            if not text or text in seen:
                continue
            seen.add(text)
            labels.append({"label": text})
        if labels:
            cleaned[lang] = labels
    return cleaned or None


def display_label(pref_label: Optional[dict]) -> str:
    if not isinstance(pref_label, dict):
        return ""

    en = _stripped(pref_label.get(DEFAULT_DISPLAY_LANG))
    if en:
        return en

    for lang in sorted(key for key in pref_label if is_lang_key(key)):
        text = _stripped(pref_label.get(lang))
        if text:
            return text
    return ""


def main_title_from_pref_label(
    pref_label: Optional[dict],
    *,
    notation: Optional[str] = None,
) -> str:
    title = display_label(pref_label)
    notation_text = _stripped(notation)
    if notation_text:
        return f"{title} ({notation_text})" if title else f"({notation_text})"
    return title


def parse_skos_pref_label(value: Any) -> Dict[str, str]:
    if isinstance(value, str):
        text = _stripped(value)
        return {"en": text} if text else {}

    if isinstance(value, dict):
        if "@value" in value or "@language" in value:
            lang = _stripped(value.get("@language")) or "en"
            text = _stripped(value.get("@value"))
            return {lang: text} if text else {}

        cleaned = sanitize_lang_string_map(value)
        return cleaned or {}

    if isinstance(value, list):
        merged: Dict[str, str] = {}
        for item in value:
            for lang, text in parse_skos_pref_label(item).items():
                if lang not in merged:
                    merged[lang] = text
        return merged

    return {}
