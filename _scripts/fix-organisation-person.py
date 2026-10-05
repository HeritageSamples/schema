#!/usr/bin/env python3
"""
Rewrite existing Organisation and Person objects to the current schema.

Converts:
  - Organisation.name / displayName -> names[] + _labels
  - Person.firstName / lastName / fullName -> names[] + _labels
  - partOfOrganisation JSON strings -> Organisation handles

Schema JS also applies the same conversion on save. This script migrates
records already stored in Cordra.

Usage:
  cd _scripts
  python fix-organisation-person.py --dry-run
  python fix-organisation-person.py
  python fix-organisation-person.py --type Person
  python fix-organisation-person.py --dry-run --output /tmp/actor-fix.json
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
from lib.skos_lang import language_tail

SCRIPT_DIR = Path(__file__).resolve().parent

ORGANISATION_TYPE = "Organisation"
PERSON_TYPE = "Person"
DEFAULT_TYPES = (ORGANISATION_TYPE, PERSON_TYPE)
DEFAULT_BATCH_SIZE = 250
DEFAULT_PAGE_SIZE = 200

LABEL_LANG_KEYS = {
    "en-english": "eng",
    "fr-french": "fre",
    "de-german": "ger",
    "nl-dutch": "dut",
    "el-greek": "gre",
}

LEGACY_FIELDS = (
    "name",
    "displayName",
    "fullName",
    "firstName",
    "lastName",
    "_displayTitle",
    "_mainTitle",
    "_custodianNames",
)

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


def organisation_pid(value: Any) -> Optional[str]:
    if isinstance(value, dict):
        return (
            stripped(value.get("organisationPid"))
            or stripped(value.get("id"))
            or stripped(value.get("pid"))
        )
    text = stripped(value)
    if not text:
        return None
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return text
        if isinstance(parsed, dict):
            return organisation_pid(parsed) or text
        return text
    return text


def migrate_part_of_organisation(value: Any) -> Tuple[Optional[List[str]], bool]:
    if not isinstance(value, list):
        return None, False
    migrated: List[str] = []
    changed = False
    for item in value:
        pid = organisation_pid(item)
        if pid != item:
            changed = True
        if pid:
            migrated.append(pid)
        else:
            changed = True
    if migrated != value:
        changed = True
    return (migrated or None), changed


def organisation_name_entries(names: Any) -> List[dict]:
    if not isinstance(names, list):
        return []
    entries: List[dict] = []
    for item in names:
        if isinstance(item, str):
            name = stripped(item)
            if name:
                entries.append({"name": name})
            continue
        if not isinstance(item, dict):
            continue
        name = stripped(item.get("name"))
        if not name:
            continue
        entry = {"name": name}
        lang = stripped(item.get("lang"))
        if lang:
            entry["lang"] = lang
        entries.append(entry)
    return entries


def person_name_entries(names: Any) -> List[dict]:
    if not isinstance(names, list):
        return []
    entries: List[dict] = []
    for item in names:
        if not isinstance(item, dict):
            continue
        first_name = stripped(item.get("firstName"))
        last_name = stripped(item.get("lastName"))
        if not first_name and not last_name:
            continue
        entry = {
            "firstName": first_name or last_name,
            "lastName": last_name or first_name,
        }
        lang = stripped(item.get("lang"))
        if lang:
            entry["lang"] = lang
        entries.append(entry)
    return entries


def split_full_name(full_name: str) -> Tuple[str, str]:
    parts = [part for part in full_name.split() if part]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], parts[0]
    return " ".join(parts[:-1]), parts[-1]


def drop_legacy_fields(content: dict) -> List[str]:
    removed: List[str] = []
    for field in LEGACY_FIELDS:
        if field in content:
            del content[field]
            removed.append(field)
    return removed


def build_organisation_labels(content: dict) -> Optional[dict]:
    entries = organisation_name_entries(content.get("names"))
    acronym = stripped(content.get("acronym"))
    if not entries:
        return {"default": acronym} if acronym else None
    default = entries[0]["name"]
    if acronym:
        default = f"{default} ({acronym})"
    labels: Dict[str, str] = {"default": default}
    for entry in entries:
        key = LABEL_LANG_KEYS.get(language_tail(entry.get("lang")) or "")
        name = stripped(entry.get("name"))
        if key and name and key not in labels:
            labels[key] = name
    return labels


def build_person_labels(content: dict) -> Optional[dict]:
    entries = person_name_entries(content.get("names"))
    if not entries:
        return None
    first = stripped(entries[0].get("firstName")) or ""
    last = stripped(entries[0].get("lastName")) or ""
    default = " ".join(part for part in (first, last) if part).strip()
    if not default:
        return None
    labels: Dict[str, str] = {"default": default}
    for entry in entries:
        key = LABEL_LANG_KEYS.get(language_tail(entry.get("lang")) or "")
        text = " ".join(
            part
            for part in (stripped(entry.get("firstName")), stripped(entry.get("lastName")))
            if part
        )
        if key and text and key not in labels:
            labels[key] = text
    return labels


def migrate_organisation_names(content: dict) -> List[str]:
    reasons: List[str] = []
    names = organisation_name_entries(content.get("names"))
    if names:
        if names != content.get("names"):
            content["names"] = names
            reasons.append("names")
        return reasons

    name = stripped(content.get("name")) or stripped(content.get("displayName"))
    if name:
        content["names"] = [{"name": name}]
        reasons.append("names")
    return reasons


def migrate_person_names(content: dict) -> List[str]:
    reasons: List[str] = []
    names = person_name_entries(content.get("names"))
    if names:
        if names != content.get("names"):
            content["names"] = names
            reasons.append("names")
        return reasons

    first_name = stripped(content.get("firstName"))
    last_name = stripped(content.get("lastName"))
    if not first_name and not last_name:
        full_name = stripped(content.get("fullName"))
        if full_name:
            first_name, last_name = split_full_name(full_name)
    if first_name or last_name:
        content["names"] = [
            {
                "firstName": first_name or last_name,
                "lastName": last_name or first_name,
            }
        ]
        reasons.append("names")
    return reasons


def migrate_object(digital_object: dict) -> Tuple[Optional[dict], List[str], List[str]]:
    content = digital_object.get("content")
    if not isinstance(content, dict):
        return None, [], ["missing content"]

    object_type = digital_object.get("type") or ""
    next_content = copy.deepcopy(content)
    reasons: List[str] = []
    warnings: List[str] = []

    refs, refs_changed = migrate_part_of_organisation(
        next_content.get("partOfOrganisation")
    )
    if refs_changed:
        if refs:
            next_content["partOfOrganisation"] = refs
        else:
            next_content.pop("partOfOrganisation", None)
        reasons.append("partOfOrganisation")

    if object_type == ORGANISATION_TYPE:
        reasons.extend(migrate_organisation_names(next_content))
        labels = build_organisation_labels(next_content)
    elif object_type == PERSON_TYPE:
        reasons.extend(migrate_person_names(next_content))
        labels = build_person_labels(next_content)
    else:
        return None, [], [f"unsupported type {object_type}"]

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

    if object_type == ORGANISATION_TYPE and not organisation_name_entries(
        next_content.get("names")
    ):
        return None, warnings, ["no names after migration"]
    if object_type == PERSON_TYPE and not person_name_entries(next_content.get("names")):
        return None, warnings, ["no names after migration"]

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
            "Rewrite Organisation and Person objects to names[] + _labels "
            "and flatten partOfOrganisation handles."
        )
    )
    parser.add_argument(
        "--type",
        dest="types",
        action="append",
        choices=list(DEFAULT_TYPES),
        help="Limit to one type (repeatable). Default: Organisation and Person.",
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
    batch_size = args.batch_size or int(config["batch_size"])

    print(f"Cordra instance: {config['cordra_api_url']}", flush=True)
    print(f"Types: {', '.join(types)}", flush=True)

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
            payload, warnings, reasons = migrate_object(digital_object)
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
