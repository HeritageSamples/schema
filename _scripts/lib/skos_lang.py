"""Shared helpers for SKOS lexical properties stored as label/text arrays."""

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


def sanitize_label_array(
    entries: Optional[List[dict]],
    *,
    unique_lang: bool = False,
) -> Optional[List[dict]]:
    if not isinstance(entries, list):
        return None

    cleaned: List[dict] = []
    seen_langs = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        lang = _stripped(entry.get("lang"))
        label = _stripped(entry.get("label"))
        if not lang or not label:
            continue
        if unique_lang:
            if lang in seen_langs:
                continue
            seen_langs.add(lang)
        cleaned.append({"label": label, "lang": lang})
    return cleaned or None


def sanitize_alt_label_array(entries: Optional[List[dict]]) -> Optional[List[dict]]:
    if not isinstance(entries, list):
        return None

    cleaned: List[dict] = []
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        lang = _stripped(entry.get("lang"))
        label = _stripped(entry.get("label"))
        if not lang or not label:
            continue
        key = f"{lang}\0{label}"
        if key in seen:
            continue
        seen.add(key)
        cleaned.append({"label": label, "lang": lang})
    return cleaned or None


def sanitize_text_array(
    entries: Optional[List[dict]],
    *,
    unique_lang: bool = False,
) -> Optional[List[dict]]:
    if not isinstance(entries, list):
        return None

    cleaned: List[dict] = []
    seen_langs = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        lang = _stripped(entry.get("lang"))
        text = _stripped(entry.get("text"))
        if not lang or not text:
            continue
        if unique_lang:
            if lang in seen_langs:
                continue
            seen_langs.add(lang)
        cleaned.append({"text": text, "lang": lang})
    return cleaned or None


def label_array_to_map(entries: Optional[List[dict]]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for entry in sanitize_label_array(entries, unique_lang=True) or []:
        result[entry["lang"]] = entry["label"]
    return result


def map_to_label_array(mapping: Optional[dict]) -> List[dict]:
    if not isinstance(mapping, dict):
        return []
    entries: List[dict] = []
    for lang in sorted(key for key in mapping if is_lang_key(key)):
        label = _stripped(mapping.get(lang))
        if label:
            entries.append({"label": label, "lang": lang.strip()})
    return entries


def alt_label_array_to_map(entries: Optional[List[dict]]) -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = {}
    for entry in sanitize_alt_label_array(entries) or []:
        result.setdefault(entry["lang"], [])
        if entry["label"] not in result[entry["lang"]]:
            result[entry["lang"]].append(entry["label"])
    return result


def map_to_alt_label_array(mapping: Optional[dict]) -> List[dict]:
    entries: List[dict] = []
    if not isinstance(mapping, dict):
        return entries
    for lang in sorted(key for key in mapping if is_lang_key(key)):
        values = mapping.get(lang)
        if isinstance(values, list):
            for value in values:
                if isinstance(value, dict):
                    label = _stripped(value.get("label"))
                else:
                    label = _stripped(value)
                if label:
                    entries.append({"label": label, "lang": lang.strip()})
        else:
            label = _stripped(values)
            if label:
                entries.append({"label": label, "lang": lang.strip()})
    return sanitize_alt_label_array(entries) or []


def text_array_to_map(entries: Optional[List[dict]]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for entry in sanitize_text_array(entries, unique_lang=True) or []:
        result[entry["lang"]] = entry["text"]
    return result


def map_to_text_array(mapping: Optional[dict]) -> List[dict]:
    if not isinstance(mapping, dict):
        return []
    entries: List[dict] = []
    for lang in sorted(key for key in mapping if is_lang_key(key)):
        text = _stripped(mapping.get(lang))
        if text:
            entries.append({"text": text, "lang": lang.strip()})
    return entries


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


def content_to_lexical_maps(content: dict) -> Dict[str, Any]:
    """Derive language-keyed maps from stored SKOS label/text arrays."""
    if not isinstance(content, dict):
        return {}

    pref_label = label_array_to_map(content.get("prefLabel"))
    alt_label = alt_label_array_to_map(content.get("altLabel"))
    definition = text_array_to_map(content.get("definition"))
    scope_note = text_array_to_map(content.get("scopeNote"))

    maps: Dict[str, Any] = {}
    if pref_label:
        maps["prefLabel"] = pref_label
    if alt_label:
        maps["altLabel"] = {
            lang: [{"label": label} for label in labels]
            for lang, labels in alt_label.items()
        }
    if definition:
        maps["definition"] = definition
    if scope_note:
        maps["scopeNote"] = scope_note
    return maps


def apply_lexical_maps_to_canonical_content(content: dict, maps: Dict[str, Any]) -> None:
    """Write SKOS lexical arrays onto content."""
    if not isinstance(content, dict):
        return

    pref = maps.get("prefLabel")
    alt = maps.get("altLabel")
    definition = maps.get("definition")
    scope_note = maps.get("scopeNote")

    pref_array = map_to_label_array(pref if isinstance(pref, dict) else None)
    if pref_array:
        content["prefLabel"] = pref_array
    else:
        content.pop("prefLabel", None)

    alt_array = map_to_alt_label_array(alt if isinstance(alt, dict) else None)
    if alt_array:
        content["altLabel"] = alt_array
    else:
        content.pop("altLabel", None)

    definition_array = map_to_text_array(definition if isinstance(definition, dict) else None)
    if definition_array:
        content["definition"] = definition_array
    else:
        content.pop("definition", None)

    scope_array = map_to_text_array(scope_note if isinstance(scope_note, dict) else None)
    if scope_array:
        content["scopeNote"] = scope_array
    else:
        content.pop("scopeNote", None)

    for legacy in ("terms", "descriptions"):
        content.pop(legacy, None)


def sanitize_lexical_arrays(content: dict) -> None:
    """Sanitize canonical SKOS lexical array fields in place."""
    if not isinstance(content, dict):
        return

    for field, sanitizer, kwargs in (
        ("prefLabel", sanitize_label_array, {"unique_lang": True}),
        ("altLabel", sanitize_alt_label_array, {}),
        ("definition", sanitize_text_array, {"unique_lang": True}),
        ("scopeNote", sanitize_text_array, {"unique_lang": True}),
    ):
        cleaned = sanitizer(content.get(field), **kwargs)
        if cleaned:
            content[field] = cleaned
        else:
            content.pop(field, None)


def display_label_from_pref_label(pref_label: Any) -> str:
    if isinstance(pref_label, list):
        for entry in pref_label:
            if isinstance(entry, dict) and entry.get("lang") == DEFAULT_DISPLAY_LANG:
                text = _stripped(entry.get("label"))
                if text:
                    return text
        for entry in pref_label:
            if isinstance(entry, dict):
                text = _stripped(entry.get("label"))
                if text:
                    return text
        return ""

    if isinstance(pref_label, dict):
        en = _stripped(pref_label.get(DEFAULT_DISPLAY_LANG))
        if en:
            return en
        for lang in sorted(key for key in pref_label if is_lang_key(key)):
            text = _stripped(pref_label.get(lang))
            if text:
                return text
    return ""


def display_label_from_terms(terms: Optional[List[dict]]) -> str:
    pref_label, _ = terms_to_lexical_maps(terms if isinstance(terms, list) else None)
    return display_label_from_pref_label(pref_label)


def display_label(pref_label: Optional[dict]) -> str:
    return display_label_from_pref_label(pref_label)


def main_title_from_content(content: dict) -> str:
    notation = _stripped(content.get("notation")) or _stripped(content.get("label"))
    title = display_label_from_pref_label(content.get("prefLabel"))
    if notation:
        return f"{title} ({notation})" if title else f"({notation})"
    return title


def parse_skos_lang_text(value: Any) -> Dict[str, str]:
    return parse_skos_pref_label(value)


def parse_skos_alt_label(value: Any) -> List[dict]:
    """Parse skos:altLabel JSON-LD into [{label, lang}] entries."""
    if isinstance(value, str):
        text = _stripped(value)
        return [{"label": text, "lang": "en"}] if text else []

    if isinstance(value, dict):
        if "@value" in value or "@language" in value:
            lang = _stripped(value.get("@language")) or "en"
            text = _stripped(value.get("@value"))
            return [{"label": text, "lang": lang}] if text else []
        return map_to_alt_label_array(
            {
                lang: [{"label": label} for label in labels]
                if isinstance(labels, list)
                else labels
                for lang, labels in value.items()
                if is_lang_key(lang)
            }
        )

    if isinstance(value, list):
        merged: List[dict] = []
        for item in value:
            merged.extend(parse_skos_alt_label(item))
        return sanitize_alt_label_array(merged) or []

    return []


def lexical_maps_equal(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def concept_lexical_equal(a: dict, b: dict) -> bool:
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
    """Build canonical SKOS lexical array fields for a VocabularyConcept."""
    content: Dict[str, Any] = {}
    apply_lexical_maps_to_canonical_content(
        content,
        {
            "prefLabel": pref_label,
            "altLabel": {
                lang: [{"label": label} for label in labels]
                for lang, labels in (alt_label or {}).items()
            }
            if alt_label
            else None,
            "definition": definition,
            "scopeNote": scope_note,
        },
    )
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

        entries: Dict[str, str] = {}
        for lang, label in value.items():
            if not is_lang_key(lang):
                continue
            text = _stripped(label)
            if text and lang not in entries:
                entries[lang] = text
        return entries

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
