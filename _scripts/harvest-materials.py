#!/usr/bin/env python3
"""
Harvest Getty AAT materials into Cordra VocabularyConcept objects.

Setup:
  cd _scripts
  python -m venv .venv && source .venv/bin/activate
  pip install -r requirements.txt
  cp .env_example .env   # edit values

Workflow:
  1. SPARQL (or --single / --id-list) selects AAT concept ids
  2. Phase 1: batched Getty fetch + Cordra upload without broader/related handle refs
     (vocabHarvestUpdate merges lexical content server-side in Cordra)
  3. Phase 2: Cordra upload with relationship refs only
     (vocabHarvestEnrichmentUpdate merges refs server-side; no second Getty fetch)

Phase 2 runs after all phase-1 concepts exist so linked handles can resolve.
Use --cache-on-disk for very large harvests or to resume without re-fetching Getty.
Use --files to write JSON instead of uploading to Cordra.

Concepts reference an existing Vocabulary object (default: {hdl_prefix}/voc.aat).
Override with --vocabulary. The harvester does not create or update Vocabulary records.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import requests
from dotenv import load_dotenv

from lib import libcordra2
from lib.skos_lang import (
    content_to_lexical_maps,
    is_lang_key,
    lexical_maps_to_terms,
    main_title_from_content,
    maps_to_descriptions,
)

SCRIPT_DIR = Path(__file__).resolve().parent

DEFAULT_BATCH_SIZE = 250

# -------------------------
# Constants
# -------------------------
OBJECT_TYPE = "VocabularyConcept"
HDL_SHOULDER = "voc"
VOCABULARY_HDL_SHOULDER = "vocab"
DEFAULT_VOCABULARY_NOTATION = "aat"
PUBLIC_WRITER_GROUP = "auth.powerusers"

AAT_ROOT_ID = "300010358"
QUERY_TERM = "materials"

AAT_BASE_URL = "https://vocab.getty.edu/aat"
AAT_SCHEME_URI = "http://vocab.getty.edu/aat/"
SPARQL_URL = "https://vocab.getty.edu/sparql.json"
SCHEMA_ID = "https://heritagesamples.org/schema/VocabularyConcept/v0.9"
UM_SNAPSHOT = "vocabHarvestSnapshot"
UM_SNAPSHOT_AT = "vocabSnapshotAt"
UM_HARVEST_UPDATE = "vocabHarvestUpdate"
UM_HARVEST_ENRICHMENT_UPDATE = "vocabHarvestEnrichmentUpdate"
UM_RESET_HARVEST_PROTECTION = "vocabResetHarvestProtection"

HARVESTED_DATE = datetime.now().strftime("%Y-%m-%d")

WARNING_SAMPLE_LIMIT = None
DEFAULT_TIMEOUT = 60
DEBUG = False


@dataclass
class AatHarvestSession:
    concepts_by_id: Dict[str, dict] = field(default_factory=dict)
    formatted_batches: List[List[dict]] = field(default_factory=list)

LANG_ALIASES = {
    "eng": "en",
    "english": "en",
    "dut": "nl",
    "nld": "nl",
    "dutch": "nl",
    "flemish": "nl",
    "fre": "fr",
    "fra": "fr",
    "french": "fr",
    "ger": "de",
    "deu": "de",
    "german": "de",
}


# -------------------------
# Timing helpers
# -------------------------
def _now() -> float:
    return time.perf_counter()


def _fmt_s(x: float) -> str:
    return f"{x:.3f}s"


# -------------------------
# Warning helpers
# -------------------------
def _new_warning_tracker(sample_limit=WARNING_SAMPLE_LIMIT):
    return {
        "total": 0,
        "counts": {},
        "samples_printed": {},
        "sample_limit": sample_limit,
    }


def _warn(tracker, category: str, aat_id: Optional[str] = None, detail: Optional[str] = None):
    if tracker is None:
        return

    tracker.setdefault("total", 0)
    tracker.setdefault("counts", {})
    tracker.setdefault("samples_printed", {})
    tracker.setdefault("sample_limit", WARNING_SAMPLE_LIMIT)

    tracker["total"] += 1
    tracker["counts"][category] = tracker["counts"].get(category, 0) + 1

    printed = tracker["samples_printed"].get(category, 0)
    sample_limit = tracker.get("sample_limit")

    if sample_limit is None or sample_limit < 0 or printed < sample_limit:
        msg = f"  - WARNING [{category}]"
        if aat_id:
            msg += f" AAT {aat_id}"
        if detail:
            msg += f": {detail}"
        print(msg, flush=True)
        tracker["samples_printed"][category] = printed + 1


def _debug_warn(tracker, category: str, aat_id: Optional[str] = None, detail: Optional[str] = None):
    """Print/count low-value warnings only when --debug is enabled.

    Getty often includes useful labels/notes in languages outside the current KIK
    VocabularyConcept schema. These are expected and should not pollute normal
    harvest logs.
    """
    if DEBUG:
        _warn(tracker, category, aat_id, detail)


def _print_final_summary(run_stats: dict, warnings: dict):
    print("Summary:", flush=True)
    for key in (
        "concepts_selected",
        "concepts_fetched",
        "records_formatted",
        "cache_hits",
        "cache_misses",
        "skipped_broader_outside_selection",
        "skipped_related_outside_selection",
        "upserted",
        "conflicts",
        "failed",
        "skipped_invalid",
    ):
        print(f"  {key}={run_stats.get(key, 0)}", flush=True)
    print(f"  warnings_total={warnings['total']}", flush=True)

    if warnings["counts"]:
        print("Warnings by category:", flush=True)
        for category, count in sorted(warnings["counts"].items()):
            print(f"  {category}={count}", flush=True)


# -------------------------
# Basic helpers
# -------------------------
def _as_list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _stripped(s):
    if isinstance(s, str):
        s = s.strip()
        return s if s else None
    if s is None:
        return None
    t = str(s).strip()
    return t if t else None


def _dedupe_preserve_order(items: Iterable[str]) -> List[str]:
    out = []
    seen = set()
    for item in items:
        s = _stripped(item)
        if not s:
            continue
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _chunks(items: List[Any], size: int) -> Iterable[List[Any]]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _extract_aat_id(uri_or_id: str) -> str:
    value = _stripped(uri_or_id) or ""
    value = value.rstrip("/")
    if not value:
        return ""
    # Handles full URIs, handles (voc.aat.300010358), notation (aat:300010358), and bare IDs.
    tail = value.split("/")[-1]
    tail = tail.split(":")[-1]
    if tail.startswith("aat."):
        tail = tail[4:]
    m = re.search(r"(\d+)$", tail)
    return m.group(1) if m else ""


def _normalize_prefix(prefix: str) -> str:
    return str(prefix or "").strip().rstrip("/")


def _vocab_notation(aat_id: str) -> str:
    return f"aat:{aat_id}"


def _notation_to_handle_suffix(notation: str) -> str:
    return notation.replace(":", ".")


def _local_vocab_id(hdl_prefix: str, aat_id: str) -> str:
    notation = _vocab_notation(aat_id)
    return f"{_normalize_prefix(hdl_prefix)}/{HDL_SHOULDER}.{_notation_to_handle_suffix(notation)}"


def _default_vocabulary_handle(hdl_prefix: str) -> str:
    prefix = _normalize_prefix(hdl_prefix)
    if not prefix:
        raise ValueError(
            "CORDRA_HDL_PREFIX is required to resolve the default vocabulary handle "
            f"({DEFAULT_VOCABULARY_NOTATION}); use --vocabulary to supply one explicitly."
        )
    return f"{prefix}/{VOCABULARY_HDL_SHOULDER}.{DEFAULT_VOCABULARY_NOTATION}"


def _resolve_vocabulary_id(config: dict, cli_handle: Optional[str]) -> str:
    if cli_handle and cli_handle.strip():
        return cli_handle.strip()
    hdl_prefix = config.get("hdl_prefix") or config.get("cordra", {}).get("hdl_prefix") or ""
    return _default_vocabulary_handle(hdl_prefix)


def _ensure_vocabulary_exists(cordra: libcordra2.Cordra, vocabulary_id: str) -> None:
    if not cordra.exists(vocabulary_id):
        print(
            f"Vocabulary not found: {vocabulary_id}\n"
            "Create the Vocabulary object in Cordra first, or pass --vocabulary.",
            flush=True,
        )
        raise SystemExit(1)


def _public_acl(hdl_prefix: str, config: Optional[dict] = None) -> dict:
    writer_group = PUBLIC_WRITER_GROUP
    if config and config.get("public_writer_group"):
        writer_group = str(config["public_writer_group"]).strip()
    return {
        "readers": ["public"],
        "writers": [f"{_normalize_prefix(hdl_prefix)}/{writer_group}"],
    }


def _concept_json_url(base_url: str, aat_id: str) -> str:
    return f"{base_url.rstrip('/')}/{aat_id}.json"


def _concept_uri(base_url: str, aat_id: str) -> str:
    # Getty concept IDs normally use http://vocab.getty.edu/aat/<id> in the LOD.
    # The HTTPS JSON endpoint still represents the concept URI itself as http.
    return f"http://vocab.getty.edu/aat/{aat_id}"


def _language_code(language_value) -> Optional[str]:
    if not language_value:
        return None

    lang = None

    if isinstance(language_value, str):
        lang = language_value
    elif isinstance(language_value, dict):
        lang = language_value.get("_label") or language_value.get("id") or language_value.get("@id")
    elif isinstance(language_value, list):
        for item in language_value:
            lang = _language_code(item)
            if lang:
                break

    lang = _stripped(lang)
    if not lang:
        return None

    if "/" in lang:
        lang = lang.rstrip("/").split("/")[-1]

    lang = lang.lower().replace("_", "-")

    if "-" in lang:
        lang = lang.split("-")[0] # Keep only the primary subtag e.g. "en" from "en-US".

    return lang


def _main_title_from_content(content: dict) -> str:
    return main_title_from_content(content)


def _label_from_concept(concept: dict) -> Optional[str]:
    label = concept.get("_label") or concept.get("label")
    if isinstance(label, list):
        for x in label:
            s = _stripped(x)
            if s:
                return s
        return None
    return _stripped(label)

def _normalize_skos_lang(language_value) -> Optional[str]:
    lang = _language_code(language_value)
    if not lang:
        return None
    return LANG_ALIASES.get(lang, lang)


def _lexical_snapshot(content: dict) -> dict:
    return content_to_lexical_maps(content)


def _initial_user_metadata(incoming: dict) -> dict:
    return {
        UM_SNAPSHOT: _lexical_snapshot(incoming),
        UM_SNAPSHOT_AT: _stripped(incoming.get("harvestedDate")) or HARVESTED_DATE,
    }


RELATIONSHIP_FIELDS = ("broader", "related")


def _mark_harvest_update(digital_objects: List[dict]) -> None:
    for obj in digital_objects:
        content = obj.get("content")
        if not isinstance(content, dict):
            content = {}
            obj["content"] = content
        content[UM_HARVEST_UPDATE] = True


def _mark_harvest_enrichment_update(digital_objects: List[dict]) -> None:
    for obj in digital_objects:
        content = obj.get("content")
        if not isinstance(content, dict):
            content = {}
            obj["content"] = content
        content[UM_HARVEST_ENRICHMENT_UPDATE] = True


def _mark_reset_harvest_protection(digital_objects: List[dict]) -> None:
    for obj in digital_objects:
        content = obj.get("content")
        if not isinstance(content, dict):
            content = {}
            obj["content"] = content
        content[UM_RESET_HARVEST_PROTECTION] = True


def _format_aat_enrichment_payload(obj: dict) -> Optional[dict]:
    content = obj.get("content") or {}
    rel_content: Dict[str, Any] = {
        "id": content.get("id"),
        "vocabulary": content.get("vocabulary"),
        "notation": content.get("notation"),
        "uri": content.get("uri"),
        "harvestedSource": content.get("harvestedSource"),
        "harvestedDate": content.get("harvestedDate"),
    }
    has_rel = False
    for field_name in RELATIONSHIP_FIELDS:
        value = content.get(field_name)
        if value:
            rel_content[field_name] = copy.deepcopy(value)
            has_rel = True
    if not has_rel:
        return None
    rel_content["_mainTitle"] = _main_title_from_content(rel_content)
    return {
        "id": obj.get("id"),
        "type": OBJECT_TYPE,
        "content": rel_content,
        "userMetadata": {},
        "acl": obj.get("acl"),
    }


def _config_bool(value, default=False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "y")


def _connect_cordra(config: dict, protocol: str) -> libcordra2.Cordra:
    return libcordra2.Cordra.from_config(config, protocol=protocol, error_mode="harvest")


# -------------------------
# HTTP / Getty helpers
# -------------------------
def _request_json(
    url: str,
    *,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout: int = DEFAULT_TIMEOUT,
    attempts: int = 3,
    sleep: float = 1.0,
) -> Any:
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            last_error = e
            if attempt < attempts:
                time.sleep(sleep * attempt)
    raise RuntimeError(f"Failed to retrieve JSON from {url}: {last_error}")


def _sparql_query_material_ids(sparql_url: str, root_id: str, timeout: int) -> List[str]:
    query = f"""
PREFIX aat: <http://vocab.getty.edu/aat/>
PREFIX gvp: <http://vocab.getty.edu/ontology#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX dc: <http://purl.org/dc/elements/1.1/>

SELECT DISTINCT ?concept ?aatId WHERE {{
  {{
    BIND(aat:{root_id} AS ?concept)
  }}
  UNION
  {{
    ?concept gvp:broaderExtended aat:{root_id} .
  }}

  ?concept skos:inScheme aat: ;
           dc:identifier ?aatId .
}}
ORDER BY ?aatId
""".strip()

    headers = {
        "Accept": "application/sparql-results+json, application/json",
        "User-Agent": "KIK-IRPA-AAT-harvester/0.1",
    }
    data = _request_json(
        sparql_url,
        params={"query": query},
        headers=headers,
        timeout=timeout,
        attempts=3,
        sleep=2.0,
    )

    bindings = data.get("results", {}).get("bindings", []) if isinstance(data, dict) else []
    ids = []
    for row in bindings:
        raw = row.get("aatId", {}).get("value") or row.get("concept", {}).get("value")
        aat_id = _extract_aat_id(raw)
        if aat_id:
            ids.append(aat_id)

    ids = _dedupe_preserve_order(ids)

    # Keep root first for readability and stable output.
    root = str(root_id)
    if root in ids:
        ids = [root] + [x for x in ids if x != root]
    else:
        ids = [root] + ids

    return ids


def _coerce_concept_json(data: Any, aat_id: str) -> dict:
    """Coerce common JSON-LD shapes into the concept dict for the requested AAT ID."""
    target_suffix = f"/{aat_id}"

    if isinstance(data, dict):
        obj_id = data.get("id") or data.get("@id")
        if isinstance(obj_id, str) and obj_id.rstrip("/").endswith(target_suffix):
            return data

        graph = data.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                if not isinstance(item, dict):
                    continue
                obj_id = item.get("id") or item.get("@id")
                if isinstance(obj_id, str) and obj_id.rstrip("/").endswith(target_suffix):
                    return item
            for item in graph:
                if isinstance(item, dict) and ("identified_by" in item or "broader" in item):
                    return item

        return data

    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            obj_id = item.get("id") or item.get("@id")
            if isinstance(obj_id, str) and obj_id.rstrip("/").endswith(target_suffix):
                return item
        for item in data:
            if isinstance(item, dict) and ("identified_by" in item or "broader" in item):
                return item

    raise ValueError(f"Could not identify concept object in JSON for AAT {aat_id}")


def _resolve_concept_json(
    aat_id: str,
    session: AatHarvestSession,
    *,
    base_url: str,
    timeout: int,
    cache_on_disk: Optional[str] = None,
) -> Tuple[dict, str]:
    if aat_id in session.concepts_by_id:
        return session.concepts_by_id[aat_id], "memory"

    cache_path = None
    if cache_on_disk:
        os.makedirs(cache_on_disk, exist_ok=True)
        cache_path = os.path.join(cache_on_disk, f"{aat_id}.json")
        if os.path.exists(cache_path):
            with open(cache_path, "r", encoding="utf-8") as f:
                concept = _coerce_concept_json(json.load(f), aat_id)
            session.concepts_by_id[aat_id] = concept
            return concept, "disk"

    url = _concept_json_url(base_url, aat_id)
    headers = {
        "Accept": "application/ld+json, application/json",
        "User-Agent": "KIK-IRPA-AAT-harvester/0.1",
    }
    data = _request_json(url, headers=headers, timeout=timeout, attempts=3, sleep=1.5)
    concept = _coerce_concept_json(data, aat_id)
    session.concepts_by_id[aat_id] = concept

    if cache_path:
        tmp = cache_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, cache_path)

    return concept, "http"


# -------------------------
# Getty extraction helpers
# -------------------------
def _term_role(ident: dict) -> str:
    """Classify a Getty identified_by term as prefLabel or altLabel.

    Getty marks \"preferred term\" only on one term (usually English). Other
    languages use \"Descriptor\" as the preferred label for that language.
    """
    classification_texts: List[str] = []

    for cls in _as_list(ident.get("classified_as")):
        if not isinstance(cls, dict):
            continue
        label = (_stripped(cls.get("_label")) or "").lower()
        obj_id = (_stripped(cls.get("id") or cls.get("@id")) or "").lower()
        if label:
            classification_texts.append(label)
        if "preferred term" in label or obj_id.endswith("300404670"):
            return "pref"

    joined = " ".join(classification_texts)
    if "used for term" in joined or "alternate descriptor" in joined:
        return "alt"
    if "descriptor" in joined:
        return "pref"
    return "alt"


def _add_label(
    pref: Dict[str, str],
    alt: Dict[str, List[str]],
    lang: str,
    label: str,
    *,
    is_preferred: bool,
) -> None:
    if not is_lang_key(lang) or not label:
        return
    if is_preferred and lang not in pref:
        pref[lang] = label
        return
    alt.setdefault(lang, []).append(label)


def _extract_labels(concept: dict, aat_id: str, warnings: dict) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    pref_label: Dict[str, str] = {}
    alt_label: Dict[str, List[str]] = {}

    for ident in _as_list(concept.get("identified_by")):
        if not isinstance(ident, dict):
            continue

        label = _stripped(ident.get("content") or ident.get("value"))
        lang = _normalize_skos_lang(ident.get("language"))
        role = _term_role(ident)

        if label and lang:
            _add_label(pref_label, alt_label, lang, label, is_preferred=(role == "pref"))
        elif label and ident.get("language"):
            _debug_warn(warnings, "unsupported_term_language", aat_id, f"lang={ident.get('language')} label={label}")

        for alt in _as_list(ident.get("alternative")):
            if not isinstance(alt, dict):
                continue
            alt_text = _stripped(alt.get("content") or alt.get("value"))
            alt_lang = _normalize_skos_lang(alt.get("language")) or lang
            if alt_text and alt_lang:
                _add_label(pref_label, alt_label, alt_lang, alt_text, is_preferred=False)
            elif alt_text and alt.get("language"):
                _debug_warn(
                    warnings,
                    "unsupported_alt_term_language",
                    aat_id,
                    f"lang={alt.get('language')} label={alt_text}",
                )

    alt_label = {lang: _dedupe_preserve_order(values) for lang, values in alt_label.items()}
    alt_label = {lang: values for lang, values in alt_label.items() if values}

    if not pref_label:
        fallback = _label_from_concept(concept)
        if fallback:
            pref_label = {"en": fallback}
            _warn(warnings, "terms_fallback_to_label", aat_id, fallback)
        else:
            _warn(warnings, "missing_terms", aat_id, "No prefLabel in any language and no _label fallback")

    return pref_label, alt_label



def _values_from_nested_keys(node: Any, keys: Tuple[str, ...]) -> List[str]:
    """Collect string values for selected keys from a nested dict/list structure."""
    out: List[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in keys:
                if isinstance(value, str):
                    s = _stripped(value)
                    if s:
                        out.append(s)
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, str):
                            s = _stripped(item)
                            if s:
                                out.append(s)
                        elif isinstance(item, dict):
                            for label_key in ("_label", "label", "content", "value"):
                                s = _stripped(item.get(label_key))
                                if s:
                                    out.append(s)
            elif isinstance(value, (dict, list)):
                out.extend(_values_from_nested_keys(value, keys))
    elif isinstance(node, list):
        for item in node:
            out.extend(_values_from_nested_keys(item, keys))
    return out


def _looks_like_internal_code_note(content: str) -> bool:
    """Reject Getty administrative notes such as 'Code : M.MT.AFU'."""
    c = (content or "").strip()
    if not c:
        return True
    if re.match(r"^code\s*:\s*[A-Z0-9_.-]+\s*$", c, flags=re.IGNORECASE):
        return True
    if re.match(r"^(facet|hierarchy)\s+code\s*:\s*", c, flags=re.IGNORECASE):
        return True
    return False


def _subject_of_lexical_property(subj: dict, content: str) -> Optional[str]:
    """Map a Getty subject_of item to definition, scopeNote, or skip.

    Getty LOD uses \"descriptive note\" for definitional text (skos:definition).
    True scope notes are rare but mapped to scopeNote when explicitly classified.
    Administrative fragments such as Dutch `Code : M.MT.AFU` are rejected.
    """
    if _looks_like_internal_code_note(content):
        return None

    classification_texts = [
        x.lower()
        for x in _values_from_nested_keys(
            subj.get("classified_as") or subj.get("type") or subj.get("@type"),
            ("_label", "label", "content", "value", "id", "@id"),
        )
    ]
    joined = " ".join(classification_texts)

    reject_markers = (
        "facet",
        "hierarchy code",
        "code",
        "notation",
        "display order",
    )
    if any(marker in joined for marker in reject_markers):
        return None

    if "scope note" in joined:
        return "scopeNote"

    if any(marker in joined for marker in ("descriptive note", "description", "note text")):
        return "definition"

    if len(content) >= 25 and ("." in content or ";" in content):
        return "definition"

    return None


def _merge_lang_text_blocks(by_property: Dict[str, Dict[str, List[str]]]) -> Dict[str, Dict[str, str]]:
    merged: Dict[str, Dict[str, str]] = {}
    for prop, by_lang in by_property.items():
        block = {}
        for lang, values in by_lang.items():
            unique_values = _dedupe_preserve_order(values)
            if unique_values:
                block[lang] = "\n\n".join(unique_values)
        if block:
            merged[prop] = block
    return merged


def _extract_subject_of_lexical(concept: dict, aat_id: str, warnings: dict) -> Tuple[Dict[str, str], Dict[str, str]]:
    by_property: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))

    for subj in _as_list(concept.get("subject_of")):
        if not isinstance(subj, dict):
            continue

        content = _stripped(subj.get("content") or subj.get("value"))
        if not content:
            continue

        prop = _subject_of_lexical_property(subj, content)
        if not prop:
            _debug_warn(warnings, "skipped_non_lexical_note", aat_id, content[:120])
            continue

        lang = _normalize_skos_lang(subj.get("language"))
        if lang:
            by_property[prop][lang].append(content)
        elif subj.get("language"):
            _debug_warn(
                warnings,
                "unsupported_note_language",
                aat_id,
                f"property={prop} lang={subj.get('language')}",
            )

    blocks = _merge_lang_text_blocks(by_property)
    return blocks.get("definition") or {}, blocks.get("scopeNote") or {}


def _scheme_from_external_uri(uri: str) -> Optional[str]:
    lower = uri.lower()
    if "wikidata.org" in lower:
        return "Wikidata"
    if "rdaregistry.info" in lower:
        return "RDA"
    if "id.loc.gov" in lower:
        return "LCSH"
    if "d-nb.info" in lower or "dnb.de" in lower:
        return "GND"
    return None


def _extract_close_matches(concept: dict, aat_id: str, *, aat_base_url: str) -> List[dict]:
    self_uri = _stripped(concept.get("id") or concept.get("@id")) or _concept_uri(aat_base_url, aat_id)
    matches: List[dict] = []
    seen: Set[str] = set()

    for equivalent in _as_list(concept.get("equivalent")):
        if not isinstance(equivalent, dict):
            continue

        uri = _stripped(equivalent.get("id") or equivalent.get("@id"))
        if not uri or uri == self_uri or uri in seen:
            continue
        if "vocab.getty.edu/aat/" in uri:
            continue

        seen.add(uri)
        match: Dict[str, str] = {"uri": uri}
        scheme = _scheme_from_external_uri(uri)
        if scheme:
            match["scheme"] = scheme
        matches.append(match)

    return matches


def _extract_aat_handle_refs(
    concept: dict,
    aat_id: str,
    *,
    field: str,
    target_key: str,
    hdl_prefix: str,
    selected_ids: Optional[Set[str]],
    warnings: dict,
    warn_category: str,
    run_stats: Optional[dict] = None,
) -> List[str]:
    handles: List[str] = []

    for item in _as_list(concept.get(field)):
        if not isinstance(item, dict):
            continue

        target = item.get(target_key) if target_key else item
        if isinstance(target, dict):
            ref_id = _extract_aat_id(target.get("id") or target.get("@id"))
        else:
            ref_id = _extract_aat_id(target)

        if not ref_id or ref_id == aat_id:
            continue
        if selected_ids is not None and ref_id not in selected_ids:
            if run_stats is not None:
                run_stats[warn_category] = run_stats.get(warn_category, 0) + 1
            _debug_warn(warnings, warn_category, aat_id, ref_id)
            continue
        handles.append(_local_vocab_id(hdl_prefix, ref_id))

    return _dedupe_preserve_order(handles)


def _extract_broader_handles(
    concept: dict,
    aat_id: str,
    *,
    hdl_prefix: str,
    selected_ids: Optional[Set[str]],
    root_id: str,
    warnings: dict,
    run_stats: Optional[dict] = None,
) -> List[str]:
    if aat_id == root_id:
        return []

    return _extract_aat_handle_refs(
        concept,
        aat_id,
        field="broader",
        target_key="",
        hdl_prefix=hdl_prefix,
        selected_ids=selected_ids,
        warnings=warnings,
        warn_category="skipped_broader_outside_selection",
        run_stats=run_stats,
    )


def _extract_related_handles(
    concept: dict,
    aat_id: str,
    *,
    hdl_prefix: str,
    selected_ids: Optional[Set[str]],
    warnings: dict,
    run_stats: Optional[dict] = None,
) -> List[str]:
    return _extract_aat_handle_refs(
        concept,
        aat_id,
        field="la:related_from_by",
        target_key="la:relates_to",
        hdl_prefix=hdl_prefix,
        selected_ids=selected_ids,
        warnings=warnings,
        warn_category="skipped_related_outside_selection",
        run_stats=run_stats,
    )

# -------------------------
# Cordra formatting
# -------------------------
def format_aat_concept(
    concept: dict,
    aat_id: str,
    *,
    hdl_prefix: str,
    vocabulary_id: str,
    aat_base_url: str,
    selected_ids: Optional[Set[str]],
    root_id: str,
    config: Optional[dict] = None,
    warning_state=None,
    run_stats: Optional[dict] = None,
) -> Optional[dict]:
    if warning_state is None:
        warning_state = _new_warning_tracker()

    try:
        obj_id = _local_vocab_id(hdl_prefix, aat_id)
        notation = _vocab_notation(aat_id)

        pref_label, alt_label = _extract_labels(concept, aat_id, warning_state)
        if not pref_label:
            raise ValueError("Missing required terms")

        exact_uri = _stripped(concept.get("id") or concept.get("@id")) or _concept_uri(aat_base_url, aat_id)

        terms = lexical_maps_to_terms(pref_label, alt_label)
        if not terms:
            raise ValueError("Missing required terms")

        content = {
            "id": obj_id,
            "$schema": SCHEMA_ID,
            "vocabulary": vocabulary_id,
            "notation": notation,
            "uri": exact_uri,
            "terms": terms,
            "harvestedSource": "AAT",
            "harvestedDate": HARVESTED_DATE,
            "queryTerms": [QUERY_TERM],
            "exactMatch": [{"uri": exact_uri, "scheme": "AAT"}],
        }

        definition, scope_note = _extract_subject_of_lexical(concept, aat_id, warning_state)
        descriptions = maps_to_descriptions(definition, scope_note)
        if descriptions:
            content["descriptions"] = descriptions

        close_match = _extract_close_matches(concept, aat_id, aat_base_url=aat_base_url)
        if close_match:
            content["closeMatch"] = close_match

        content["_mainTitle"] = _main_title_from_content(content)

        broader = _extract_broader_handles(
            concept,
            aat_id,
            hdl_prefix=hdl_prefix,
            selected_ids=selected_ids,
            root_id=root_id,
            warnings=warning_state,
            run_stats=run_stats,
        )
        if broader:
            content["broader"] = broader

        related = _extract_related_handles(
            concept,
            aat_id,
            hdl_prefix=hdl_prefix,
            selected_ids=selected_ids,
            warnings=warning_state,
            run_stats=run_stats,
        )
        if related:
            content["related"] = related

        return {
            "id": obj_id,
            "type": OBJECT_TYPE,
            "content": content,
            "userMetadata": _initial_user_metadata(content),
            "acl": _public_acl(hdl_prefix, config),
        }

    except Exception as e:
        _warn(warning_state, "format_error", aat_id, str(e))
        fn = f"dump_{OBJECT_TYPE}_{aat_id}.json"
        print(f"  - ERROR AAT {aat_id}: {e}", flush=True)
        with open(fn, "w", encoding="utf-8") as fp:
            json.dump(concept, fp, indent=2, ensure_ascii=False)
        return None


def _write_batch_file(filename: str, digital_objects: list):
    dirname = os.path.dirname(filename)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(digital_objects, f, indent=2, ensure_ascii=False)
    print(f"Wrote file: {filename}", flush=True)


# -------------------------
# Main workflow
# -------------------------
def _load_config() -> dict:
    load_dotenv(SCRIPT_DIR / ".env")
    required = {
        "CORDRA_REST_API_URL": "cordra_api_url",
        "CORDRA_ADMIN_USERNAME": "cordra_username",
        "CORDRA_ADMIN_PASSWORD": "cordra_password",
        "CORDRA_HDL_PREFIX": "hdl_prefix",
    }
    config: Dict[str, str] = {}
    missing: List[str] = []
    for env_key, config_key in required.items():
        value = os.environ.get(env_key, "").strip()
        if not value:
            missing.append(env_key)
        else:
            config[config_key] = value

    if missing:
        print(
            "Missing required environment variables in _scripts/.env:\n  "
            + "\n  ".join(missing),
            flush=True,
        )
        print("Copy .env_example to .env and set the values.", flush=True)
        raise SystemExit(1)

    config["cordra_api_url"] = config["cordra_api_url"].rstrip("/")

    optional = {
        "CORDRA_DOIP_HOST": "cordra_doip_host",
        "CORDRA_DOIP_PORT": "cordra_doip_port",
        "CORDRA_DOIP_SERVICE_ID": "cordra_doip_service_id",
        "CORDRA_DEFAULT_BATCH_SIZE": "default_batch_size",
        "CORDRA_PUBLIC_WRITER_GROUP": "public_writer_group",
    }
    for env_key, config_key in optional.items():
        value = os.environ.get(env_key, "").strip()
        if value:
            config[config_key] = value

    return config


def _select_ids(args, config, warnings) -> List[str]:
    timeout = int(args.timeout)
    if args.full:
        t0 = _now()
        ids = _sparql_query_material_ids(args.sparql_url, args.root_id, timeout)
        print(f"Selected {len(ids)} AAT concepts from SPARQL in {_fmt_s(_now() - t0)}", flush=True)
    elif args.single:
        ids = [_extract_aat_id(args.single)]
    elif args.id_list:
        ids = [_extract_aat_id(x) for x in args.id_list.split(",")]
        ids = [x for x in ids if x]
    else:
        raise SystemExit("Select exactly one operational mode (full | single | id-list)")

    ids = _dedupe_preserve_order(ids)

    if args.max_items is not None:
        ids = ids[:args.max_items]

    if not ids:
        raise SystemExit("No AAT IDs selected")

    return ids


def _new_run_stats(concepts_selected: int) -> dict:
    return {
        "concepts_selected": concepts_selected,
        "concepts_fetched": 0,
        "records_formatted": 0,
        "upserted": 0,
        "conflicts": 0,
        "failed": 0,
        "skipped_invalid": 0,
        "cache_hits": 0,
        "cache_misses": 0,
    }


_FETCH_PROGRESS_WIDTH = 100


def _print_fetch_progress(
    global_idx: int,
    total_selected: int,
    aat_id: str,
) -> None:
    msg = f"    - Fetch aat:{aat_id} {global_idx}/{total_selected}"
    print(f"\r{msg.ljust(_FETCH_PROGRESS_WIDTH)}", end="", flush=True)


def _fetch_and_format_batch_ids(
    ids: List[str],
    *,
    session: AatHarvestSession,
    selected_ids: Set[str],
    args,
    config,
    warnings,
    run_stats: dict,
    progress_start_idx: Optional[int] = None,
    total_selected: Optional[int] = None,
) -> Tuple[List[dict], float, float]:
    hdl_prefix = config.get("hdl_prefix") or config.get("cordra", {}).get("hdl_prefix") or "20.500.14037"
    digital_objects = []
    t_fetch = 0.0
    t_format = 0.0
    show_progress = (
        not args.timing
        and sys.stdout.isatty()
        and progress_start_idx is not None
        and total_selected is not None
    )

    for item_idx, aat_id in enumerate(ids, start=1):
        if show_progress:
            _print_fetch_progress(progress_start_idx + item_idx - 1, total_selected, aat_id)

        t_fetch0 = _now()
        try:
            concept, fetch_source = _resolve_concept_json(
                aat_id,
                session,
                base_url=args.aat_base_url,
                timeout=int(args.timeout),
                cache_on_disk=args.cache_on_disk,
            )
            run_stats["concepts_fetched"] += 1
            if fetch_source == "http":
                run_stats["cache_misses"] += 1
            else:
                run_stats["cache_hits"] += 1
        except Exception as e:
            run_stats["failed"] += 1
            _warn(warnings, "fetch_error", aat_id, str(e))
            t_fetch += _now() - t_fetch0
            continue
        t_fetch += _now() - t_fetch0

        t_format0 = _now()
        dobj = format_aat_concept(
            concept,
            aat_id,
            hdl_prefix=hdl_prefix,
            vocabulary_id=args.vocabulary_id,
            aat_base_url=args.aat_base_url,
            selected_ids=selected_ids,
            root_id=args.root_id,
            config=config,
            warning_state=warnings,
            run_stats=run_stats,
        )
        t_format += _now() - t_format0

        if dobj:
            digital_objects.append(dobj)
            run_stats["records_formatted"] += 1
        else:
            run_stats["skipped_invalid"] += 1

        if args.timing:
            print(
                f"    [AAT {aat_id}] fetch+format={_fmt_s(_now() - t_fetch0)}",
                flush=True,
            )

        if args.fetch_sleep > 0:
            time.sleep(args.fetch_sleep)

    if show_progress:
        print(flush=True)

    return digital_objects, t_fetch, t_format

def _objects_without_handle_refs(digital_objects: List[dict]) -> List[dict]:
    phase_objects = []
    for obj in digital_objects:
        phase_obj = dict(obj)
        content = dict(obj.get("content", {}))
        content.pop("broader", None)
        content.pop("related", None)
        phase_obj["content"] = content
        phase_objects.append(phase_obj)
    return phase_objects

class _UploadContext:
    def __init__(self, args, config):
        self.cordra = _connect_cordra(config, args.protocol)


def _upload_digital_objects(
    upload_ctx: _UploadContext,
    digital_objects: List[dict],
    args,
    config: dict,
    run_stats: dict,
    *,
    label: Optional[str] = None,
) -> float:
    if not digital_objects:
        return 0.0

    if label:
        print(f"{label}: uploading {len(digital_objects)} object(s)...", flush=True)
    t0 = _now()
    stats = upload_ctx.cordra.batch_upload_detailed(digital_objects, include_user_metadata=True).stats

    run_stats["upserted"] += stats["upserted"]
    run_stats["conflicts"] += stats["conflicts"]
    run_stats["failed"] += stats["failed"]
    run_stats["skipped_invalid"] += stats["skipped_invalid"]

    if args.upload_sleep > 0:
        time.sleep(args.upload_sleep)

    return _now() - t0


def _batch_output_path(output_path: str, phase: str, batch_no: int) -> str:
    root, ext = os.path.splitext(output_path)
    ext = ext or ".json"
    return f"{root}_{phase}_p{batch_no}{ext}"


def _process_concept_batches(ids: List[str], args, config, warnings, run_stats: dict) -> None:
    selected_ids = set(ids)
    batch_size = args.batch_size
    session = AatHarvestSession()
    total_batches = (len(ids) + batch_size - 1) // batch_size if ids else 0

    if args.files:
        for batch_no, batch_ids in enumerate(_chunks(ids, batch_size), start=1):
            t_batch0 = _now()
            start_idx = (batch_no - 1) * batch_size + 1
            print(f"  - Batch {batch_no}/{total_batches}", flush=True)
            digital_objects, t_fetch, t_format = _fetch_and_format_batch_ids(
                batch_ids,
                session=session,
                selected_ids=selected_ids,
                args=args,
                config=config,
                warnings=warnings,
                run_stats=run_stats,
                progress_start_idx=start_idx,
                total_selected=len(ids),
            )
            print(
                f"    - Fetched={len(batch_ids)} formatted={len(digital_objects)}",
                flush=True,
            )
            print("    - Write JSON file", flush=True)
            _write_batch_file(_batch_output_path(args.output, "concepts", batch_no), digital_objects)
            if args.timing:
                print(
                    f"    - Timings: fetch={_fmt_s(t_fetch)} format={_fmt_s(t_format)} "
                    f"total={_fmt_s(_now() - t_batch0)}",
                    flush=True,
                )
        return

    upload_ctx = _UploadContext(args, config)
    _ensure_vocabulary_exists(upload_ctx.cordra, args.vocabulary_id)

    print("Phase 1: concepts without handle refs", flush=True)
    for batch_no, batch_ids in enumerate(_chunks(ids, batch_size), start=1):
        t_batch0 = _now()
        start_idx = (batch_no - 1) * batch_size + 1
        print(f"  - Batch {batch_no}/{total_batches}", flush=True)

        digital_objects, t_fetch, t_format = _fetch_and_format_batch_ids(
            batch_ids,
            session=session,
            selected_ids=selected_ids,
            args=args,
            config=config,
            warnings=warnings,
            run_stats=run_stats,
            progress_start_idx=start_idx,
            total_selected=len(ids),
        )
        session.formatted_batches.append(digital_objects)
        print(
            f"    - Fetched={len(batch_ids)} formatted={len(digital_objects)}",
            flush=True,
        )

        phase1_objects = _objects_without_handle_refs(digital_objects)
        _mark_harvest_update(phase1_objects)
        if args.reset:
            _mark_reset_harvest_protection(phase1_objects)

        print("    - Upload to cordra", flush=True)
        t_upload1 = _upload_digital_objects(
            upload_ctx,
            phase1_objects,
            args,
            config,
            run_stats,
        )

        if args.timing:
            print(
                f"    - Timings: fetch={_fmt_s(t_fetch)} format={_fmt_s(t_format)} "
                f"upload={_fmt_s(t_upload1)} total={_fmt_s(_now() - t_batch0)}",
                flush=True,
            )

    print("Phase 2: concepts with handle refs", flush=True)
    for batch_no, digital_objects in enumerate(session.formatted_batches, start=1):
        if not digital_objects:
            continue

        t_batch0 = _now()
        print(f"  - Batch {batch_no}/{total_batches}", flush=True)

        enrichment_updates = []
        for obj in digital_objects:
            payload = _format_aat_enrichment_payload(obj)
            if payload:
                enrichment_updates.append(payload)

        if not enrichment_updates:
            continue

        _mark_harvest_enrichment_update(enrichment_updates)
        if args.reset:
            _mark_reset_harvest_protection(enrichment_updates)

        print("    - Upload to cordra", flush=True)
        t_upload2 = _upload_digital_objects(
            upload_ctx,
            enrichment_updates,
            args,
            config,
            run_stats,
        )

        if args.timing:
            print(
                f"    - Timings: upload={_fmt_s(t_upload2)} total={_fmt_s(_now() - t_batch0)}",
                flush=True,
            )


def main(args):
    global DEBUG
    DEBUG = bool(args.debug)

    start_time = time.time()
    warnings = _new_warning_tracker(sample_limit=args.warning_sample_limit)
    config = _load_config()
    args.batch_size = args.batch_size if args.batch_size is not None else int(config.get("default_batch_size") or DEFAULT_BATCH_SIZE)
    args.cache_on_disk = args.cache_on_disk or args.cache_dir
    try:
        args.vocabulary_id = _resolve_vocabulary_id(config, args.vocabulary)
    except ValueError as exc:
        print(exc, flush=True)
        raise SystemExit(1) from exc

    ids = _select_ids(args, config, warnings)
    run_stats = _new_run_stats(len(ids))

    print(
        f"AAT harvest: root={args.root_id} selected={len(ids)} batch_size={args.batch_size} "
        f"vocabulary={args.vocabulary_id}",
        flush=True,
    )
    _process_concept_batches(ids, args, config, warnings, run_stats)

    print(f"Finished in {round((time.time() - start_time) / 60, 1)} minutes", flush=True)
    _print_final_summary(run_stats, warnings)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Harvest Getty AAT materials as Cordra VocabularyConcept objects."
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("-f", "--full", action="store_true", help="Harvest root AAT concept and all descendants.")
    mode.add_argument("-s", "--single", help="Harvest a single AAT concept by ID.")
    mode.add_argument("--id-list", type=str, default=None, help="Comma-separated list of AAT IDs to harvest.")

    parser.add_argument("--root-id", default=AAT_ROOT_ID, help=f"Root AAT concept ID for --full (default: {AAT_ROOT_ID}).")
    parser.add_argument("--sparql-url", default=SPARQL_URL, help=f"Getty SPARQL JSON endpoint (default: {SPARQL_URL}).")
    parser.add_argument("--aat-base-url", default=AAT_BASE_URL, help=f"Getty AAT record base URL (default: {AAT_BASE_URL}).")
    parser.add_argument(
        "-v",
        "--vocabulary",
        metavar="HANDLE",
        default=None,
        help=(
            "Cordra handle of an existing Vocabulary object "
            f"(default: {{hdl_prefix}}/voc.{DEFAULT_VOCABULARY_NOTATION})"
        ),
    )

    parser.add_argument("--files", action="store_true", help="Save output to a JSON file instead of uploading to Cordra.")
    parser.add_argument("-o", "--output", default="output/aat_materials_vocabularyconcepts.json", help="Output JSON file for --files mode.")
    parser.add_argument(
        "--cache-on-disk",
        default=None,
        help="Directory for cached Getty concept JSON files (resume / large harvests).",
    )
    parser.add_argument("--cache-dir", default=None, help="Deprecated alias for --cache-on-disk.")

    parser.add_argument("--protocol", choices=["doip", "rest"], default="rest", help="Cordra protocol (default: rest).")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Override batch size (default: CORDRA_DEFAULT_BATCH_SIZE from .env, else 250).",
    )
    parser.add_argument("--max-items", type=int, default=None, help="Stop after harvesting N selected concepts, useful for testing.")

    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help=f"HTTP timeout in seconds (default: {DEFAULT_TIMEOUT}).")
    parser.add_argument("--fetch-sleep", type=float, default=0.0, help="Seconds to sleep between Getty JSON fetches.")
    parser.add_argument("--upload-sleep", type=float, default=0.0, help="Seconds to sleep between Cordra upload batches.")
    parser.add_argument("--timing", action="store_true", help="Enable detailed per-concept timing logs.")
    parser.add_argument("--debug", action="store_true", help="Print low-value diagnostics, including ignored unsupported Getty languages and skipped non-scope notes.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear existing local harvest protection (vocabEdits) while applying this harvest.",
    )
    parser.add_argument("--warning-sample-limit", type=int, default=WARNING_SAMPLE_LIMIT, help="Per warning category print limit. Default: unlimited.")

    parsed_args = parser.parse_args()
    main(parsed_args)
