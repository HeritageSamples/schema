"""Shared helpers for SKOS lexical properties (UI arrays and internal maps)."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_DISPLAY_LANG = "en"


def is_lang_key(tag: Any) -> bool:
    return isinstance(tag, str) and tag.strip() != ""


def _stripped(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _as_bool(value: Any) -> bool:
    return value is True or value == "true"


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


def terms_to_lexical_maps(
    terms: Optional[List[dict]],
) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    pref_label: Dict[str, str] = {}
    alt_label: Dict[str, List[str]] = {}

    if not isinstance(terms, list):
        return pref_label, alt_label

    for term in terms:
        if not isinstance(term, dict):
            continue
        lang = _stripped(term.get("lang"))
        label = _stripped(term.get("label"))
        if not lang or not label:
            continue
        if _as_bool(term.get("isAlternative")):
            alt_label.setdefault(lang, [])
            if label not in alt_label[lang]:
                alt_label[lang].append(label)
        elif lang not in pref_label:
            pref_label[lang] = label

    return pref_label, alt_label


def lexical_maps_to_terms(
    pref_label: Optional[dict],
    alt_label: Optional[dict] = None,
) -> List[dict]:
    terms: List[dict] = []

    for lang in sorted(key for key in (pref_label or {}) if is_lang_key(key)):
        text = _stripped((pref_label or {}).get(lang))
        if text:
            terms.append({"label": text, "lang": lang.strip(), "isAlternative": False})

    for lang in sorted(key for key in (alt_label or {}) if is_lang_key(key)):
        values = (alt_label or {}).get(lang)
        if not isinstance(values, list):
            continue
        seen = set()
        for value in values:
            if isinstance(value, dict):
                text = _stripped(value.get("label"))
            else:
                text = _stripped(value)
            if not text or text in seen:
                continue
            seen.add(text)
            terms.append({"label": text, "lang": lang.strip(), "isAlternative": True})

    return terms


def descriptions_to_maps(
    descriptions: Optional[List[dict]],
) -> Tuple[Dict[str, str], Dict[str, str]]:
    definition: Dict[str, str] = {}
    scope_note: Dict[str, str] = {}

    if not isinstance(descriptions, list):
        return definition, scope_note

    for item in descriptions:
        if not isinstance(item, dict):
            continue
        lang = _stripped(item.get("lang"))
        text = _stripped(item.get("description"))
        if not lang or not text:
            continue
        kind = _stripped(item.get("kind")) or "definition"
        if kind == "scopeNote":
            scope_note[lang] = text
        else:
            definition[lang] = text

    return definition, scope_note


def maps_to_descriptions(
    definition: Optional[dict],
    scope_note: Optional[dict] = None,
) -> List[dict]:
    descriptions: List[dict] = []

    for lang in sorted(key for key in (definition or {}) if is_lang_key(key)):
        text = _stripped((definition or {}).get(lang))
        if text:
            descriptions.append(
                {"description": text, "lang": lang.strip(), "kind": "definition"}
            )

    for lang in sorted(key for key in (scope_note or {}) if is_lang_key(key)):
        text = _stripped((scope_note or {}).get(lang))
        if text:
            descriptions.append(
                {"description": text, "lang": lang.strip(), "kind": "scopeNote"}
            )

    return descriptions


def sanitize_terms(terms: Optional[List[dict]]) -> Optional[List[dict]]:
    pref, alt = terms_to_lexical_maps(terms if isinstance(terms, list) else None)
    cleaned = lexical_maps_to_terms(pref, alt)
    return cleaned or None


def sanitize_descriptions(descriptions: Optional[List[dict]]) -> Optional[List[dict]]:
    definition, scope_note = descriptions_to_maps(
        descriptions if isinstance(descriptions, list) else None
    )
    cleaned = maps_to_descriptions(definition, scope_note)
    return cleaned or None


def content_to_lexical_maps(content: dict) -> Dict[str, Any]:
    """Read canonical SKOS lexical map fields from content."""
    if not isinstance(content, dict):
        return {}

    pref_label = sanitize_lang_string_map(content.get("prefLabel")) or {}
    alt_entries = sanitize_lang_alt_label_map(content.get("altLabel")) or {}
    definition = sanitize_lang_string_map(content.get("definition")) or {}
    scope_note = sanitize_lang_string_map(content.get("scopeNote")) or {}

    maps: Dict[str, Any] = {}
    if pref_label:
        maps["prefLabel"] = pref_label
    if alt_entries:
        maps["altLabel"] = alt_entries
    if definition:
        maps["definition"] = definition
    if scope_note:
        maps["scopeNote"] = scope_note
    return maps


def apply_lexical_maps_to_canonical_content(content: dict, maps: Dict[str, Any]) -> None:
    """Write SKOS lexical maps directly onto content (canonical storage shape)."""
    if not isinstance(content, dict):
        return

    pref = sanitize_lang_string_map(maps.get("prefLabel"))
    alt = sanitize_lang_alt_label_map(maps.get("altLabel"))
    definition = sanitize_lang_string_map(maps.get("definition"))
    scope_note = sanitize_lang_string_map(maps.get("scopeNote"))

    if pref:
        content["prefLabel"] = pref
    else:
        content.pop("prefLabel", None)

    if alt:
        content["altLabel"] = alt
    else:
        content.pop("altLabel", None)

    if definition:
        content["definition"] = definition
    else:
        content.pop("definition", None)

    if scope_note:
        content["scopeNote"] = scope_note
    else:
        content.pop("scopeNote", None)

    for legacy in ("terms", "descriptions"):
        content.pop(legacy, None)


def sanitize_lexical_maps(content: dict) -> None:
    """Sanitize canonical SKOS lexical map fields in place."""
    if not isinstance(content, dict):
        return

    for field, sanitizer in (
        ("prefLabel", sanitize_lang_string_map),
        ("altLabel", sanitize_lang_alt_label_map),
        ("definition", sanitize_lang_string_map),
        ("scopeNote", sanitize_lang_string_map),
    ):
        cleaned = sanitizer(content.get(field))
        if cleaned:
            content[field] = cleaned
        else:
            content.pop(field, None)


def apply_lexical_maps_to_content(content: dict, maps: Dict[str, Any]) -> None:
    if not isinstance(content, dict):
        return

    pref = sanitize_lang_string_map(maps.get("prefLabel")) or {}
    alt_raw = sanitize_lang_alt_label_map(maps.get("altLabel")) or {}
    alt = {
        lang: [entry["label"] for entry in entries if isinstance(entry, dict) and entry.get("label")]
        for lang, entries in alt_raw.items()
    }
    definition = sanitize_lang_string_map(maps.get("definition")) or {}
    scope_note = sanitize_lang_string_map(maps.get("scopeNote")) or {}

    terms = lexical_maps_to_terms(pref, alt)
    if terms:
        content["terms"] = terms
    else:
        content.pop("terms", None)

    descriptions = maps_to_descriptions(definition, scope_note)
    if descriptions:
        content["descriptions"] = descriptions
    else:
        content.pop("descriptions", None)

    for legacy in ("prefLabel", "altLabel", "definition", "scopeNote"):
        content.pop(legacy, None)


def display_label_from_terms(terms: Optional[List[dict]]) -> str:
    pref_label, _ = terms_to_lexical_maps(terms if isinstance(terms, list) else None)
    return display_label(pref_label)


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


def main_title_from_terms(
    terms: Optional[List[dict]],
    *,
    notation: Optional[str] = None,
) -> str:
    title = display_label_from_terms(terms)
    notation_text = _stripped(notation)
    if notation_text:
        return f"{title} ({notation_text})" if title else f"({notation_text})"
    return title


def main_title_from_content(content: dict) -> str:
    notation = _stripped(content.get("notation")) or _stripped(content.get("label"))
    pref_label = sanitize_lang_string_map(content.get("prefLabel")) or {}
    title = display_label(pref_label)
    if notation:
        return f"{title} ({notation})" if title else f"({notation})"
    return title


def parse_skos_lang_text(value: Any) -> Dict[str, str]:
    """Parse skos:definition, skos:scopeNote, or skos:prefLabel JSON-LD values."""
    return parse_skos_pref_label(value)


def parse_skos_alt_label(value: Any) -> Dict[str, List[dict]]:
    """Parse skos:altLabel JSON-LD into a language map of {label} entries."""
    if isinstance(value, str):
        text = _stripped(value)
        return {"en": [{"label": text}]} if text else {}

    if isinstance(value, dict):
        if "@value" in value or "@language" in value:
            lang = _stripped(value.get("@language")) or "en"
            text = _stripped(value.get("@value"))
            return {lang: [{"label": text}]} if text else {}

        cleaned: Dict[str, List[dict]] = {}
        for lang, labels in value.items():
            if not is_lang_key(lang):
                continue
            if isinstance(labels, list):
                entries = []
                for item in labels:
                    if isinstance(item, dict):
                        text = _stripped(item.get("label") or item.get("@value"))
                    else:
                        text = _stripped(item)
                    if text:
                        entries.append({"label": text})
                if entries:
                    cleaned[lang] = entries
            else:
                text = _stripped(labels)
                if text:
                    cleaned[lang] = [{"label": text}]
        return cleaned

    if isinstance(value, list):
        merged: Dict[str, List[dict]] = {}
        for item in value:
            for lang, entries in parse_skos_alt_label(item).items():
                if lang not in merged:
                    merged[lang] = []
                seen = {entry["label"] for entry in merged[lang]}
                for entry in entries:
                    if entry["label"] not in seen:
                        merged[lang].append(entry)
                        seen.add(entry["label"])
        return merged

    return {}


def lexical_maps_equal(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def concept_lexical_maps_equal(a: dict, b: dict) -> bool:
    """Compare concept lexical maps for merge conflict detection."""
    maps_a = content_to_lexical_maps(a if isinstance(a, dict) else {})
    maps_b = content_to_lexical_maps(b if isinstance(b, dict) else {})
    return lexical_maps_equal(maps_a, maps_b)


def build_concept_lexical_content(
    *,
    pref_label: Dict[str, str],
    alt_label: Optional[Dict[str, List[str]]] = None,
    definition: Optional[Dict[str, str]] = None,
    scope_note: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Build canonical SKOS lexical fields for a VocabularyConcept."""
    maps: Dict[str, Any] = {"prefLabel": pref_label}
    if alt_label:
        maps["altLabel"] = {
            lang: [{"label": label} for label in labels]
            for lang, labels in alt_label.items()
        }
    if definition:
        maps["definition"] = definition
    if scope_note:
        maps["scopeNote"] = scope_note

    content: Dict[str, Any] = {}
    apply_lexical_maps_to_canonical_content(content, maps)
    return content


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


def pref_label_maps_to_terms(pref_label: Dict[str, str]) -> List[dict]:
    return lexical_maps_to_terms(pref_label)
