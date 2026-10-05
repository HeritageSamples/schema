#!/usr/bin/env python3
"""
Rewrite existing Vocabulary and VocabularyConcept prefLabel languages to
Common-language concept handles, drop _mainTitle, and set _labels.

Harvest snapshots and pending prefLabel edits are rewritten so AAT harvest
protection does not treat the language-handle migration as a user edit.

Languages that cannot be mapped to a Common-language concept are dropped by
default. Pass --keep-unmapped to leave them (schema validation will likely fail).

Usage:
  cd _scripts
  python fix-preflabel-handles.py --dry-run
  python fix-preflabel-handles.py
  python fix-preflabel-handles.py --type VocabularyConcept --keep-unmapped
  python fix-preflabel-handles.py --dry-run --output /tmp/preflabel-fix.json
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from dotenv import load_dotenv

from lib import libcordra2
from lib.skos_lang import (
    HANDLE_TAIL_RE,
    display_label_from_pref_label,
    language_tail,
    language_to_handle,
    pref_label_entries_to_handles,
)

SCRIPT_DIR = Path(__file__).resolve().parent

VOCABULARY_TYPE = "Vocabulary"
CONCEPT_TYPE = "VocabularyConcept"
DEFAULT_TYPES = (VOCABULARY_TYPE, CONCEPT_TYPE)
DEFAULT_BATCH_SIZE = 250
DEFAULT_PAGE_SIZE = 200

UM_SNAPSHOT = "vocabHarvestSnapshot"
UM_EDITS = "vocabEdits"

LABEL_LANG_KEYS = {
    "en-english": "eng",
    "fr-french": "fre",
    "de-german": "ger",
    "nl-dutch": "dut",
    "el-greek": "gre",
}

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


def flatten_user_metadata(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    nested = raw.get("userMetadata")
    flat = dict(raw)
    flat.pop("userMetadata", None)
    flat.pop("content", None)
    if isinstance(nested, dict):
        return {**flatten_user_metadata(nested), **flat}
    return flat


def build_labels(content: dict, object_type: str) -> Optional[dict]:
    default = display_label_from_pref_label(content.get("prefLabel"))
    if object_type == VOCABULARY_TYPE:
        if not default:
            default = stripped(content.get("sourceName")) or stripped(content.get("notation")) or ""
    else:
        notation = stripped(content.get("notation")) or stripped(content.get("label")) or ""
        if notation:
            default = f"{default} ({notation})" if default else f"({notation})"

    if not default:
        return None

    labels: Dict[str, str] = {"default": default}
    for entry in content.get("prefLabel") or []:
        if not isinstance(entry, dict):
            continue
        key = LABEL_LANG_KEYS.get(language_tail(entry.get("lang")) or "")
        text = stripped(entry.get("label"))
        if key and text and key not in labels:
            labels[key] = text
    return labels


def as_pref_label_entries(entries: Any) -> Optional[List[dict]]:
    if isinstance(entries, list):
        return entries
    text = stripped(entries)
    if text:
        return [{"label": text, "lang": "en"}]
    if isinstance(entries, dict):
        converted = []
        for lang, value in entries.items():
            label = stripped(value)
            if label:
                converted.append({"label": label, "lang": str(lang)})
        return converted or None
    return None


def migrate_pref_label(
    entries: Any,
    hdl_prefix: str,
    *,
    drop_unmapped: bool,
) -> Tuple[Optional[List[dict]], List[str], List[str]]:
    normalized = as_pref_label_entries(entries)
    if not isinstance(normalized, list):
        return None, [], []

    converted = pref_label_entries_to_handles(normalized, hdl_prefix)
    mapped: List[dict] = []
    dropped: List[str] = []
    kept_unmapped: List[str] = []
    seen = set()

    for entry in converted:
        lang = stripped(entry.get("lang")) or ""
        if lang in seen:
            continue
        if is_language_handle(lang):
            seen.add(lang)
            mapped.append(entry)
            continue
        if drop_unmapped:
            dropped.append(lang)
            continue
        seen.add(lang)
        kept_unmapped.append(lang)
        mapped.append(entry)

    return (mapped or None), dropped, kept_unmapped


def migrate_snapshot_pref_label(
    snapshot: Any,
    hdl_prefix: str,
    *,
    drop_unmapped: bool,
) -> Tuple[Any, bool, List[str]]:
    if not isinstance(snapshot, dict):
        return snapshot, False, []
    pref = snapshot.get("prefLabel")
    if not isinstance(pref, dict):
        return snapshot, False, []

    next_pref: Dict[str, Any] = {}
    dropped: List[str] = []
    changed = False
    for lang, value in pref.items():
        handle = language_to_handle(hdl_prefix, lang)
        if handle != lang:
            changed = True
        if is_language_handle(handle):
            if handle not in next_pref:
                next_pref[handle] = value
            continue
        if drop_unmapped:
            dropped.append(str(lang))
            changed = True
            continue
        if handle not in next_pref:
            next_pref[handle] = value

    if not changed and next_pref == pref:
        return snapshot, False, dropped

    next_snapshot = dict(snapshot)
    if next_pref:
        next_snapshot["prefLabel"] = next_pref
    else:
        next_snapshot.pop("prefLabel", None)
    return next_snapshot, True, dropped


def migrate_pref_label_edits(
    edits: Any,
    hdl_prefix: str,
    *,
    drop_unmapped: bool,
) -> Tuple[Any, bool, List[str]]:
    if not isinstance(edits, dict):
        return edits, False, []

    next_edits: Dict[str, Any] = {}
    dropped: List[str] = []
    changed = False
    for path, edit in edits.items():
        if not str(path).startswith("prefLabel."):
            next_edits[path] = edit
            continue
        lang = str(path)[len("prefLabel.") :]
        handle = language_to_handle(hdl_prefix, lang)
        if handle != lang:
            changed = True
        if is_language_handle(handle):
            next_path = f"prefLabel.{handle}"
            if next_path not in next_edits:
                next_edits[next_path] = edit
            continue
        if drop_unmapped:
            dropped.append(str(path))
            changed = True
            continue
        next_edits[path if handle == lang else f"prefLabel.{handle}"] = edit

    if not changed and next_edits == edits:
        return edits, False, dropped
    return next_edits, True, dropped


def migrate_object(
    digital_object: dict,
    hdl_prefix: str,
    *,
    drop_unmapped: bool,
) -> Tuple[Optional[dict], List[str], List[str]]:
    content = digital_object.get("content")
    if not isinstance(content, dict):
        return None, [], ["missing content"]

    object_type = digital_object.get("type") or ""
    next_content = copy.deepcopy(content)
    reasons: List[str] = []
    warnings: List[str] = []

    pref, dropped_langs, kept_unmapped = migrate_pref_label(
        next_content.get("prefLabel"),
        hdl_prefix,
        drop_unmapped=drop_unmapped,
    )
    if dropped_langs:
        warnings.append(f"dropped unmapped prefLabel lang(s): {', '.join(dropped_langs)}")
    if kept_unmapped:
        warnings.append(f"kept unmapped prefLabel lang(s): {', '.join(kept_unmapped)}")

    if pref is None:
        return None, warnings, ["no prefLabel after migration"]
    if pref != content.get("prefLabel"):
        next_content["prefLabel"] = pref
        reasons.append("prefLabel.lang")

    if "_mainTitle" in next_content:
        del next_content["_mainTitle"]
        reasons.append("_mainTitle")

    labels = build_labels(next_content, object_type)
    if labels != content.get("_labels"):
        if labels:
            next_content["_labels"] = labels
            reasons.append("_labels")
        elif "_labels" in next_content:
            del next_content["_labels"]
            reasons.append("_labels")

    next_user_metadata = None
    raw_user_metadata = digital_object.get("userMetadata")
    if isinstance(raw_user_metadata, dict) and raw_user_metadata:
        user_metadata = flatten_user_metadata(copy.deepcopy(raw_user_metadata))
        metadata_changed = False

        snapshot, snapshot_changed, dropped_snapshot = migrate_snapshot_pref_label(
            user_metadata.get(UM_SNAPSHOT),
            hdl_prefix,
            drop_unmapped=drop_unmapped,
        )
        if snapshot_changed:
            if snapshot:
                user_metadata[UM_SNAPSHOT] = snapshot
            else:
                user_metadata.pop(UM_SNAPSHOT, None)
            metadata_changed = True
            reasons.append("vocabHarvestSnapshot")
        if dropped_snapshot:
            warnings.append(
                f"dropped unmapped snapshot prefLabel lang(s): {', '.join(dropped_snapshot)}"
            )

        edits, edits_changed, dropped_edits = migrate_pref_label_edits(
            user_metadata.get(UM_EDITS),
            hdl_prefix,
            drop_unmapped=drop_unmapped,
        )
        if edits_changed:
            if edits:
                user_metadata[UM_EDITS] = edits
            else:
                user_metadata.pop(UM_EDITS, None)
            metadata_changed = True
            reasons.append("vocabEdits")
        if dropped_edits:
            warnings.append(f"dropped unmapped vocabEdits path(s): {', '.join(dropped_edits)}")

        if metadata_changed:
            next_user_metadata = user_metadata

    if not reasons:
        return None, warnings, []

    payload = {
        "id": digital_object.get("id"),
        "type": object_type,
        "content": next_content,
    }
    if next_user_metadata is not None:
        payload["userMetadata"] = next_user_metadata
    return payload, warnings, reasons


def iter_type_objects(cordra: libcordra2.Cordra, object_type: str, *, page_size: int, limit: Optional[int]) -> Iterable[dict]:
    yielded = 0
    page_num = 0
    while True:
        remaining = None if limit is None else max(limit - yielded, 0)
        if remaining == 0:
            return
        size = page_size if remaining is None else min(page_size, remaining)
        results = cordra.query(f'type:"{object_type}"', page_num=page_num, page_size=size, full=True)
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
            "Rewrite Vocabulary and VocabularyConcept prefLabel languages to "
            "Common-language handles and generate _labels."
        )
    )
    parser.add_argument(
        "--type",
        dest="types",
        action="append",
        choices=list(DEFAULT_TYPES),
        help="Limit to one type (repeatable). Default: Vocabulary and VocabularyConcept.",
    )
    parser.add_argument(
        "--keep-unmapped",
        action="store_true",
        help="Keep prefLabel languages that cannot be mapped to a Common-language handle.",
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
    drop_unmapped = not args.keep_unmapped
    output_path = Path(args.output).resolve() if args.output else None

    config = load_config()
    hdl_prefix = config["hdl_prefix"]
    batch_size = args.batch_size or int(config["batch_size"])

    print(f"Cordra instance: {config['cordra_api_url']}", flush=True)
    print(f"Handle prefix: {hdl_prefix}", flush=True)
    print(f"Types: {', '.join(types)}", flush=True)
    print(
        "Unmapped languages: "
        + ("keep" if args.keep_unmapped else "drop"),
        flush=True,
    )

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
                digital_object,
                hdl_prefix,
                drop_unmapped=drop_unmapped,
            )
            for warning in warnings:
                warning_count += 1
                print(f"  {YELLOW}{handle}: {warning}{RESET}", flush=True)
            if payload is None:
                if reasons:
                    skipped.append((handle, "; ".join(reasons)))
                    print(f"  {YELLOW}skip {handle}: {'; '.join(reasons)}{RESET}", flush=True)
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
        result = cordra.batch_upload_detailed(batch, include_user_metadata=True).stats
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
