#!/usr/bin/env python3
"""
Rewrite existing HeritageObject and Sample records to the current schema.

Converts:
  - titles / custodianLabel -> _labels
  - drop leftover _displayTitle, _mainTitle, _custodianNames
  - title/description/subject/rights lang tags -> Common-language handles
  - leftover enum labels (resourceType, titleType, ...) -> VocabularyConcept handles
  - Sample isCustodianIdentifier titles -> custodianLabel

Schema JS also applies label generation on save. This script migrates
records already stored in Cordra.

Usage:
  cd _scripts
  python fix-heritageobject-sample.py --dry-run
  python fix-heritageobject-sample.py
  python fix-heritageobject-sample.py --type Sample
  python fix-heritageobject-sample.py --dry-run --output /tmp/object-fix.json
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from dotenv import load_dotenv

from lib import libcordra2
from lib.skos_lang import HANDLE_TAIL_RE, language_tail, language_to_handle

SCRIPT_DIR = Path(__file__).resolve().parent

HERITAGE_TYPE = "HeritageObject"
SAMPLE_TYPE = "Sample"
DEFAULT_TYPES = (HERITAGE_TYPE, SAMPLE_TYPE)
DEFAULT_BATCH_SIZE = 250
DEFAULT_PAGE_SIZE = 200
TITLE_TYPE_TAIL = "title"
DEFAULT_TITLE_TYPE = "Title"

SCHEMA_IDS = {
    HERITAGE_TYPE: "https://heritagesamples.org/schema/HeritageObject/v0.9",
    SAMPLE_TYPE: "https://heritagesamples.org/schema/Sample/v0.9",
}

LANG_ARRAY_FIELDS = {
    HERITAGE_TYPE: ("titles", "descriptions", "subjects", "rightsList"),
    SAMPLE_TYPE: ("titles", "otherDescriptions", "subjects", "rightsList"),
}

CONTROLLED_LISTS_DIR = SCRIPT_DIR.parent / "_controlled_lists"
ENUM_RULES = {
    HERITAGE_TYPE: (
        ("principalIdentifier.identifierType", "Common-persistentIdentifier"),
        ("types.resourceType", "HeritageObject-resourceType"),
        ("titles[].titleType", "HeritageObject-titleType"),
        ("descriptions[].descriptionType", "HeritageObject-descriptionType"),
        ("objectType", "HeritageObject-objectType"),
        ("alternateIdentifiers[].alternateIdentifierType", "Common-persistentIdentifier"),
        ("fundingReferences[].funderIdentifierType", "HeritageObject-funderIdentifierType"),
        ("relatedIdentifiers[].relatedIdentifierType", "HeritageObject-relatedIdentifierType"),
        ("relatedIdentifiers[].relationType", "HeritageObject-relationType"),
        ("relatedIdentifiers[].resourceTypeGeneral", "HeritageObject-resourceTypeGeneral"),
    ),
    SAMPLE_TYPE: (
        ("principalIdentifier.identifierType", "Common-persistentIdentifier"),
        ("types.resourceType", "Sample-resourceType"),
        ("titles[].titleType", "Sample-titleType"),
        ("otherDescriptions[].descriptionType", "Sample-descriptionType"),
        ("documentationIdentifier.relatedIdentifierType", "Sample-relatedIdentifierType"),
        ("documentationIdentifier.relationType", "Sample-relationType"),
        ("documentationIdentifier.resourceTypeGeneral", "Sample-relatedIdentifiers-resourceTypeGeneral"),
        ("sampleType", "Sample-sampleType"),
        ("alternateIdentifiers[].alternateIdentifierType", "Common-persistentIdentifier"),
        ("fundingReferences[].funderIdentifierType", "Sample-funderIdentifierType"),
        ("relatedIdentifiers[].relatedIdentifierType", "Sample-relatedIdentifierType"),
        ("relatedIdentifiers[].relationType", "Sample-relatedIdentifiers-relationType"),
        ("relatedIdentifiers[].resourceTypeGeneral", "Sample-relatedIdentifiers-resourceTypeGeneral"),
    ),
}

TITLE_KEYS = ("title", "titleType", "lang")

LABEL_LANG_KEYS = {
    "en-english": "eng",
    "fr-french": "fre",
    "de-german": "ger",
    "nl-dutch": "dut",
    "el-greek": "gre",
}

LEGACY_FIELDS = ("_displayTitle", "_mainTitle", "_custodianNames")

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"


def load_config() -> Dict[str, str]:
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
        sys.exit(1)

    config["cordra_api_url"] = config["cordra_api_url"].rstrip("/")
    batch = os.environ.get("CORDRA_DEFAULT_BATCH_SIZE", "").strip()
    config["batch_size"] = batch or str(DEFAULT_BATCH_SIZE)
    return config


def stripped(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def is_language_handle(value: Any) -> bool:
    text = stripped(value)
    return bool(text and HANDLE_TAIL_RE.search(text))


def is_concept_handle(value: Any) -> bool:
    return is_language_handle(value)


def slug_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")


def lookup_keys(value: str) -> List[str]:
    text = value.strip()
    lower = text.lower()
    slug = slug_key(text)
    compact = re.sub(r"[^a-z0-9]+", "", lower)
    keys = [lower, slug, compact]
    seen = set()
    unique: List[str] = []
    for key in keys:
        if key and key not in seen:
            seen.add(key)
            unique.append(key)
    return unique


def concept_label_texts(value: Any) -> List[str]:
    texts: List[str] = []
    if isinstance(value, str):
        text = stripped(value)
        if text:
            texts.append(text)
    elif isinstance(value, dict):
        text = stripped(value.get("@value") or value.get("label"))
        if text:
            texts.append(text)
        else:
            for item in value.values():
                texts.extend(concept_label_texts(item))
    elif isinstance(value, list):
        for item in value:
            texts.extend(concept_label_texts(item))
    return texts


class EnumCatalog:
    def __init__(self, skos_dir: Path, hdl_prefix: str):
        self.by_term: Dict[str, Dict[str, str]] = {}
        prefix = (stripped(hdl_prefix) or "").rstrip("/")
        if not skos_dir.is_dir():
            raise FileNotFoundError(f"Controlled lists directory not found: {skos_dir}")
        for path in sorted(skos_dir.glob("*.jsonld")):
            data = json.loads(path.read_text(encoding="utf-8"))
            concepts = data.get("skos:hasTopConcept") or []
            if not isinstance(concepts, list):
                continue
            table: Dict[str, str] = {}
            for concept in concepts:
                if not isinstance(concept, dict):
                    continue
                concept_id = stripped(concept.get("@id"))
                if not concept_id:
                    continue
                tail = concept_id.rstrip("/").split("/")[-1]
                handle = f"{prefix}/voc.hsr.{tail}"
                keys = lookup_keys(tail)
                for label in concept_label_texts(concept.get("skos:prefLabel")):
                    keys.extend(lookup_keys(label))
                for label in concept_label_texts(concept.get("skos:altLabel")):
                    keys.extend(lookup_keys(label))
                for key in keys:
                    table.setdefault(key, handle)
            self.by_term[path.stem] = table

    def resolve(self, query_term: str, value: Any) -> Optional[str]:
        text = stripped(value)
        if not text:
            return None
        if is_concept_handle(text):
            return text
        table = self.by_term.get(query_term) or {}
        for key in lookup_keys(text):
            handle = table.get(key)
            if handle:
                return handle
        return None


def rewrite_string_fields(
    root: dict,
    path: str,
    resolver,
) -> Tuple[int, List[str]]:
    segments = path.split(".")
    current: List[Any] = [root]
    for segment in segments[:-1]:
        array_segment = segment.endswith("[]")
        key = segment[:-2] if array_segment else segment
        next_nodes: List[Any] = []
        for value in current:
            if not isinstance(value, dict):
                continue
            if array_segment:
                items = value.get(key)
                if isinstance(items, list):
                    next_nodes.extend(item for item in items if isinstance(item, dict))
            elif isinstance(value.get(key), dict):
                next_nodes.append(value[key])
        current = next_nodes
        if not current:
            return 0, []

    last = segments[-1]
    changed = 0
    unmapped: List[str] = []
    for parent in current:
        if not isinstance(parent, dict) or last not in parent:
            continue
        value = parent[last]
        if not isinstance(value, str) or not value.strip():
            continue
        resolved = resolver(value)
        if resolved is None:
            unmapped.append(value.strip())
            continue
        if resolved != value:
            parent[last] = resolved
            changed += 1
    return changed, unmapped


def migrate_enum_fields(
    content: dict,
    object_type: str,
    catalog: EnumCatalog,
) -> Tuple[List[str], List[str]]:
    reasons: List[str] = []
    unmapped: List[str] = []
    for path, query_term in ENUM_RULES.get(object_type, ()):
        changed, missed = rewrite_string_fields(
            content,
            path,
            lambda value, term=query_term: catalog.resolve(term, value),
        )
        if changed:
            reasons.append(path)
        for value in missed:
            unmapped.append(f"{path}={value} ({query_term})")
    return reasons, unmapped


def is_true(value: Any) -> bool:
    return value is True or value == "true" or value == 1


def is_primary_title_type(value: Any) -> bool:
    text = stripped(value)
    if not text:
        return False
    if text == DEFAULT_TITLE_TYPE:
        return True
    match = HANDLE_TAIL_RE.search(text)
    return bool(match and match.group(1) == TITLE_TYPE_TAIL)


def default_title_type(hdl_prefix: str) -> str:
    prefix = (stripped(hdl_prefix) or "").rstrip("/")
    if prefix:
        return f"{prefix}/voc.hsr.{TITLE_TYPE_TAIL}"
    return DEFAULT_TITLE_TYPE


def title_entries(titles: Any) -> List[dict]:
    if not isinstance(titles, list):
        return []
    entries: List[dict] = []
    for item in titles:
        if isinstance(item, str):
            title = stripped(item)
            if title:
                entries.append({"title": title})
            continue
        if not isinstance(item, dict):
            continue
        title = stripped(item.get("title"))
        if not title:
            continue
        entry = dict(item)
        entry["title"] = title
        entries.append(entry)
    return entries


def sanitize_title_entry(entry: dict, hdl_prefix: str) -> dict:
    cleaned = {"title": entry["title"]}
    title_type = stripped(entry.get("titleType")) or default_title_type(hdl_prefix)
    cleaned["titleType"] = title_type
    lang = rewrite_lang_value(entry.get("lang"), hdl_prefix)
    if lang:
        cleaned["lang"] = lang
    return cleaned


def rewrite_lang_value(value: Any, hdl_prefix: str) -> Optional[str]:
    lang = stripped(value)
    if not lang:
        return None
    handle = language_to_handle(hdl_prefix, lang)
    if is_language_handle(handle):
        return handle
    return None


def rewrite_array_langs(items: Any, hdl_prefix: str) -> Tuple[Optional[List[dict]], bool]:
    if not isinstance(items, list):
        return None, False
    next_items: List[Any] = []
    changed = False
    for item in items:
        if not isinstance(item, dict):
            next_items.append(item)
            continue
        next_item = dict(item)
        lang = stripped(next_item.get("lang"))
        if lang:
            handle = rewrite_lang_value(lang, hdl_prefix)
            if handle != lang:
                changed = True
                if handle:
                    next_item["lang"] = handle
                else:
                    next_item.pop("lang", None)
        next_items.append(next_item)
    return next_items, changed


def add_language_labels(labels: Dict[str, str], entries: Sequence[dict]) -> None:
    for entry in entries:
        key = LABEL_LANG_KEYS.get(language_tail(entry.get("lang")) or "")
        title = stripped(entry.get("title"))
        if key and title and key not in labels:
            labels[key] = title


def labels_from_titles(titles: Any, *, priority: str) -> Optional[dict]:
    entries = title_entries(titles)
    if not entries:
        return None

    ordered = list(entries)
    default_title = stripped(entries[0].get("title")) or ""

    if priority == "heritageObject":
        primary = [entry for entry in entries if is_primary_title_type(entry.get("titleType"))]
        rest = [entry for entry in entries if not is_primary_title_type(entry.get("titleType"))]
        if primary:
            ordered = primary + rest
            default_title = stripped(primary[0].get("title")) or default_title
    elif priority == "sample":
        custodian = [entry for entry in entries if is_true(entry.get("isCustodianIdentifier"))]
        remaining = [entry for entry in entries if not is_true(entry.get("isCustodianIdentifier"))]
        primary = [entry for entry in remaining if is_primary_title_type(entry.get("titleType"))]
        rest = [entry for entry in remaining if not is_primary_title_type(entry.get("titleType"))]
        ordered = custodian + primary + rest
        if custodian:
            default_title = stripped(custodian[0].get("title")) or default_title
        elif primary:
            default_title = stripped(primary[0].get("title")) or default_title

    if not default_title:
        return None
    labels: Dict[str, str] = {"default": default_title}
    add_language_labels(labels, ordered)
    return labels


def labels_from_text(value: Any) -> Optional[dict]:
    text = stripped(value)
    return {"default": text} if text else None


def build_heritage_labels(content: dict) -> Optional[dict]:
    return (
        labels_from_titles(content.get("titles"), priority="heritageObject")
        or labels_from_text(content.get("_displayTitle"))
        or labels_from_text(content.get("inventoryNumber"))
    )


def build_sample_labels(content: dict) -> Optional[dict]:
    return (
        labels_from_titles(content.get("titles"), priority="sample")
        or labels_from_text(content.get("custodianLabel"))
        or labels_from_text(content.get("_displayTitle"))
    )


def migrate_heritage_titles(content: dict, hdl_prefix: str) -> List[str]:
    reasons: List[str] = []
    entries = title_entries(content.get("titles"))
    if not entries:
        fallback = stripped(content.get("_displayTitle")) or stripped(content.get("inventoryNumber"))
        if fallback:
            entries = [{"title": fallback, "titleType": default_title_type(hdl_prefix)}]
            reasons.append("titles")

    cleaned = [sanitize_title_entry(entry, hdl_prefix) for entry in entries]
    if cleaned != content.get("titles"):
        if cleaned:
            content["titles"] = cleaned
            if "titles" not in reasons:
                reasons.append("titles")
        elif "titles" in content:
            del content["titles"]
            reasons.append("titles")
    return reasons


def migrate_sample_titles(content: dict, hdl_prefix: str) -> List[str]:
    reasons: List[str] = []
    entries = title_entries(content.get("titles"))
    custodian_label = stripped(content.get("custodianLabel"))

    if not custodian_label:
        for entry in entries:
            if is_true(entry.get("isCustodianIdentifier")):
                custodian_label = stripped(entry.get("title"))
                break
        if not custodian_label:
            custodian_label = stripped(content.get("_displayTitle"))
        if custodian_label:
            content["custodianLabel"] = custodian_label
            reasons.append("custodianLabel")

    cleaned = [sanitize_title_entry(entry, hdl_prefix) for entry in entries]
    if cleaned != content.get("titles"):
        if cleaned:
            content["titles"] = cleaned
            reasons.append("titles")
        elif "titles" in content:
            del content["titles"]
            reasons.append("titles")
    return reasons


def migrate_lang_arrays(content: dict, object_type: str, hdl_prefix: str) -> List[str]:
    reasons: List[str] = []
    for field in LANG_ARRAY_FIELDS.get(object_type, ()):
        if field == "titles":
            continue
        next_items, changed = rewrite_array_langs(content.get(field), hdl_prefix)
        if changed:
            content[field] = next_items
            reasons.append(f"{field}.lang")
    return reasons


def clean_principal_identifier(content: dict) -> bool:
    principal = content.get("principalIdentifier")
    if principal is None:
        return False
    if not isinstance(principal, dict):
        del content["principalIdentifier"]
        return True
    identifier = stripped(principal.get("identifier"))
    identifier_type = stripped(principal.get("identifierType"))
    if identifier or identifier_type:
        return False
    del content["principalIdentifier"]
    return True


def drop_legacy_fields(content: dict) -> List[str]:
    removed: List[str] = []
    for field in LEGACY_FIELDS:
        if field in content:
            del content[field]
            removed.append(field)
    return removed


def migrate_object(
    digital_object: dict,
    hdl_prefix: str,
    catalog: EnumCatalog,
) -> Tuple[Optional[dict], List[str], List[str]]:
    content = digital_object.get("content")
    if not isinstance(content, dict):
        return None, [], ["missing content"]

    object_type = digital_object.get("type") or ""
    next_content = copy.deepcopy(content)
    reasons: List[str] = []
    warnings: List[str] = []

    schema_id = SCHEMA_IDS.get(object_type)
    if schema_id and next_content.get("$schema") != schema_id:
        next_content["$schema"] = schema_id
        reasons.append("$schema")

    if object_type == HERITAGE_TYPE:
        labels = build_heritage_labels(next_content)
        reasons.extend(migrate_heritage_titles(next_content, hdl_prefix))
    elif object_type == SAMPLE_TYPE:
        labels = build_sample_labels(next_content)
        reasons.extend(migrate_sample_titles(next_content, hdl_prefix))
    else:
        return None, [], [f"unsupported type {object_type}"]

    reasons.extend(migrate_lang_arrays(next_content, object_type, hdl_prefix))
    enum_reasons, unmapped = migrate_enum_fields(next_content, object_type, catalog)
    reasons.extend(enum_reasons)
    if unmapped:
        return None, warnings, [f"unmapped enum: {'; '.join(unmapped)}"]

    if clean_principal_identifier(next_content):
        reasons.append("principalIdentifier")

    if labels != content.get("_labels"):
        if labels:
            next_content["_labels"] = labels
            reasons.append("_labels")
        elif "_labels" in next_content:
            del next_content["_labels"]
            reasons.append("_labels")

    removed = drop_legacy_fields(next_content)
    if removed:
        reasons.extend(removed)

    if object_type == HERITAGE_TYPE:
        if not title_entries(next_content.get("titles")):
            return None, warnings, ["no titles after migration"]
        if not next_content.get("_labels"):
            return None, warnings, ["no _labels after migration"]

    if not reasons:
        return None, warnings, []

    return (
        {
            "id": digital_object.get("id"),
            "type": object_type,
            "content": next_content,
        },
        warnings,
        reasons,
    )


def iter_type_objects(
    cordra: libcordra2.Cordra, object_type: str, *, page_size: int, limit: Optional[int]
) -> Iterable[dict]:
    yielded = 0
    page_num = 0
    while True:
        remaining = None if limit is None else max(limit - yielded, 0)
        if remaining == 0:
            return
        size = page_size if remaining is None else min(page_size, remaining)
        results = cordra.query(
            f'type:"{object_type}"', page_num=page_num, page_size=size, full=True
        )
        if not results:
            return
        for item in results:
            yield item
            yielded += 1
            if limit is not None and yielded >= limit:
                return
        if len(results) < size:
            return
        page_num += 1


def chunked(items: Sequence[dict], size: int) -> Iterable[List[dict]]:
    for index in range(0, len(items), size):
        yield list(items[index : index + size])


def write_output(path: Path, digital_objects: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(digital_objects, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(f"Wrote {len(digital_objects)} object(s) to {path}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Rewrite HeritageObject and Sample records to _labels and drop "
            "legacy _displayTitle fields."
        )
    )
    parser.add_argument(
        "--type",
        dest="types",
        action="append",
        choices=list(DEFAULT_TYPES),
        help="Limit to one type (repeatable). Default: HeritageObject and Sample.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned updates; no Cordra writes.",
    )
    parser.add_argument(
        "--output",
        metavar="FILE",
        default=None,
        help="Write planned digital objects to JSON.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum objects to scan per type.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help=f"Cordra batchUpload size (default: {DEFAULT_BATCH_SIZE}).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    types = tuple(args.types) if args.types else DEFAULT_TYPES
    output_path = Path(args.output).resolve() if args.output else None

    config = load_config()
    hdl_prefix = config["hdl_prefix"]
    batch_size = args.batch_size or int(config["batch_size"])

    print(f"Cordra instance: {config['cordra_api_url']}", flush=True)
    print(f"Handle prefix: {hdl_prefix}", flush=True)
    print(f"Types: {', '.join(types)}", flush=True)

    catalog = EnumCatalog(CONTROLLED_LISTS_DIR, hdl_prefix)
    print(f"Enum lists: {len(catalog.by_term)}", flush=True)

    cordra = libcordra2.Cordra.from_config(config, protocol="rest")

    scanned = 0
    unchanged = 0
    planned: List[dict] = []
    skipped: List[Tuple[str, str]] = []
    warning_count = 0

    for object_type in types:
        print(f"\nScanning {object_type}...", flush=True)
        for digital_object in iter_type_objects(
            cordra,
            object_type,
            page_size=DEFAULT_PAGE_SIZE,
            limit=args.limit,
        ):
            scanned += 1
            handle = digital_object.get("id") or ""
            payload, warnings, reasons = migrate_object(
                digital_object, hdl_prefix, catalog
            )
            for warning in warnings:
                warning_count += 1
                print(f"  {YELLOW}{handle}: {warning}{RESET}", flush=True)
            if payload is None:
                if reasons:
                    skipped.append((handle, "; ".join(reasons)))
                    print(
                        f"  {YELLOW}skip {handle}: {'; '.join(reasons)}{RESET}",
                        flush=True,
                    )
                else:
                    unchanged += 1
                continue
            planned.append(payload)
            print(f"  {handle}: {', '.join(reasons)}", flush=True)

    print(
        f"\nScanned {scanned}: {len(planned)} to update, {unchanged} unchanged, "
        f"{len(skipped)} skipped, {warning_count} warning(s).",
        flush=True,
    )

    if output_path is not None:
        write_output(output_path, planned)

    if args.dry_run:
        print(f"\nDry run: would upload {len(planned)} object(s)", flush=True)
        return

    if not planned:
        print("Nothing to upload.", flush=True)
        return

    upserted = 0
    failed = 0
    for batch in chunked(planned, batch_size):
        print(f"Uploading {len(batch)} object(s)...", flush=True)
        result = cordra.batch_upload_detailed(batch).stats
        upserted += result.get("upserted", 0) + result.get("conflicts", 0)
        failed += result.get("failed", 0) + result.get("skipped_invalid", 0)
        print(
            f"  upserted={result.get('upserted', 0)} "
            f"conflicts={result.get('conflicts', 0)} "
            f"failed={result.get('failed', 0)} "
            f"skipped_invalid={result.get('skipped_invalid', 0)}",
            flush=True,
        )

    if failed:
        print(f"\n{RED}Updated {upserted} object(s); {failed} failed{RESET}", flush=True)
        sys.exit(1)

    print(f"\n{GREEN}Updated {upserted} object(s){RESET}", flush=True)


if __name__ == "__main__":
    main()
