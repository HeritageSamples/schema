#!/usr/bin/env python3
"""Fetch and transform Getty AAT concepts for VocabularyConcept harvest."""

from __future__ import annotations

from typing import Dict, Iterator, List, Set, Tuple

import requests

QUERY_TERM = "materials"
TOP_LEVEL_ID = "300010358"
AAT_BASE_URL = "https://vocab.getty.edu/aat/"
CORDRA_TYPE = "VocabularyConcept"
QUERY_FILTER = "/queryTerms/_:materials"


def aat_json_url(aat_id: str) -> str:
    return f"{AAT_BASE_URL}{aat_id}.json"


def handle_for_aat_id(aat_id: str, hdl_prefix: str) -> str:
    prefix = hdl_prefix.rstrip("/")
    return f"{prefix}/voc.aat.{aat_id}"


def extract_aat_id(uri: str) -> str:
    if not uri:
        return ""
    uri = uri.rstrip("/")
    return uri.split("/")[-1]


def extract_language_code(language_list: List[dict]) -> str:
    if not language_list:
        return ""
    lang_obj = language_list[0] or {}
    if "_label" in lang_obj and lang_obj["_label"]:
        return str(lang_obj["_label"])
    lang_id = lang_obj.get("id", "")
    return extract_aat_id(lang_id)


def fetch_aat_concept(aat_id: str) -> dict:
    url = aat_json_url(aat_id)
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def transform_concept(concept: dict, aat_id: str, hdl_prefix: str) -> dict:
    pref_label = concept.get("_label") or ""

    terms: List[dict] = []
    seen_terms: Set[Tuple[str, str, bool]] = set()
    for ident in concept.get("identified_by", []) or []:
        if ident.get("type") == "Identifier":
            continue
        label = (ident.get("content") or "").strip()
        lang = extract_language_code(ident.get("language", []) or [])
        if label:
            key = (label, lang, False)
            if key not in seen_terms:
                terms.append({"label": label, "lang": lang, "isAlternative": False})
                seen_terms.add(key)
        for alt in ident.get("alternative", []) or []:
            alt_label = (alt.get("content") or "").strip()
            alt_lang = extract_language_code(alt.get("language", []) or [])
            if alt_label:
                key_alt = (alt_label, alt_lang, True)
                if key_alt not in seen_terms:
                    terms.append(
                        {"label": alt_label, "lang": alt_lang, "isAlternative": True}
                    )
                    seen_terms.add(key_alt)

    descriptions: List[dict] = []
    for subj in concept.get("subject_of", []) or []:
        content = (subj.get("content") or "").strip()
        if not content:
            continue
        lang = extract_language_code(subj.get("language", []) or [])
        descriptions.append({"description": content, "lang": lang})

    broader_handles: List[str] = []
    if aat_id != TOP_LEVEL_ID:
        for broader in concept.get("broader", []) or []:
            broader_uri = broader.get("id") or ""
            broader_id = extract_aat_id(broader_uri)
            if broader_id:
                broader_handles.append(handle_for_aat_id(broader_id, hdl_prefix))

    exact_match_uri = concept.get("id") or f"{AAT_BASE_URL}{aat_id}"
    exact_match = [{"uri": exact_match_uri, "scheme": "AAT", "primarySource": True}]

    query_terms = [QUERY_TERM]
    if aat_id == TOP_LEVEL_ID:
        query_terms.append("TOP_LEVEL")

    result: Dict[str, object] = {
        "id": handle_for_aat_id(aat_id, hdl_prefix),
        "prefLabel": pref_label,
        "terms": terms,
        "descriptions": descriptions,
        "broader": broader_handles,
        "narrower": [],
        "exactMatch": exact_match,
        "queryTerms": query_terms,
    }

    return result


def collect_narrower_ids(concept: dict) -> List[str]:
    ids: List[str] = []
    for item in concept.get("narrower", []) or []:
        uri = item.get("id") or ""
        child_id = extract_aat_id(uri)
        if child_id:
            ids.append(child_id)
    return ids


def traverse_materials(
    hdl_prefix: str,
    *,
    start_id: str = TOP_LEVEL_ID,
    max_concepts: int | None = None,
) -> Iterator[Tuple[str, dict, dict, List[str]]]:
    """BFS over AAT materials subtree.

    Yields (aat_id, raw_concept, transformed_content, child_aat_ids).
    """
    work_list: List[str] = [start_id]
    processed: Set[str] = set()
    count = 0

    while work_list:
        if max_concepts is not None and count >= max_concepts:
            return

        current_id = work_list.pop(0)
        if current_id in processed:
            continue

        concept = fetch_aat_concept(current_id)
        transformed = transform_concept(concept, current_id, hdl_prefix)
        child_ids = collect_narrower_ids(concept)

        yield current_id, concept, transformed, child_ids

        for child_id in child_ids:
            if child_id not in processed and child_id not in work_list:
                work_list.append(child_id)

        processed.add(current_id)
        count += 1
