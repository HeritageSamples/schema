#!/usr/bin/env python3
"""
Import SKOS JSON-LD controlled lists into Cordra as VocabularyConcept objects.

Scans all *.jsonld files in a directory, merges concepts that share the same
@id tail across lists, and uploads the result in one batchUpload call.

Uses an existing Vocabulary object (default: {hdl_prefix}/voc.hsr).
Override with --vocabulary when concepts belong to another scheme.

Usage:
  cd _scripts
  python upload-enums.py --dry-run
  python upload-enums.py --dry-run --output /tmp/vocabulary-concepts.json
  python upload-enums.py ../skos
  python upload-enums.py -v HSR/voc.hsr
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

from lib import libcordra2
from lib.skos_lang import (
    build_concept_lexical_content,
    concept_lexical_maps_equal,
    display_label,
    parse_skos_alt_label,
    parse_skos_lang_text,
    parse_skos_pref_label,
)

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_SKOS_DIR = SCRIPT_DIR.parent / "_controlled_lists"
CONCEPT_TYPE = "VocabularyConcept"
SCHEMA_CONCEPT = "https://heritagesamples.org/schema/VocabularyConcept/v0.9"
DEFAULT_VOCABULARY_NOTATION = "hsr"
CONCEPT_URI_BASE = f"https://heritagesamples.org/vocab/{DEFAULT_VOCABULARY_NOTATION}"

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"


@dataclass
class MergedConcept:
    tail: str
    pref_label: Dict[str, str]
    alt_label: Dict[str, List[dict]] = field(default_factory=dict)
    definition: Dict[str, str] = field(default_factory=dict)
    scope_note: Dict[str, str] = field(default_factory=dict)
    query_terms: set[str] = field(default_factory=set)
    source_ids: List[str] = field(default_factory=list)

    def lexical_maps(self) -> Dict[str, object]:
        maps: Dict[str, object] = {"prefLabel": self.pref_label}
        if self.alt_label:
            maps["altLabel"] = self.alt_label
        if self.definition:
            maps["definition"] = self.definition
        if self.scope_note:
            maps["scopeNote"] = self.scope_note
        return maps


@dataclass
class PlanResult:
    files_scanned: int
    source_records: int
    skipped: int
    merged: Dict[str, MergedConcept]
    label_conflicts: List[str]


def load_config(*, require_cordra: bool = True) -> Dict[str, str]:
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
        if require_cordra:
            print(
                "Missing required environment variables in _scripts/.env:\n  "
                + "\n  ".join(missing),
                flush=True,
            )
            print("Copy .env_example to .env and set the values.", flush=True)
            sys.exit(1)
        for env_key, config_key in required.items():
            if env_key in missing:
                config[config_key] = ""

    if config.get("cordra_api_url"):
        config["cordra_api_url"] = config["cordra_api_url"].rstrip("/")
    return config


def default_vocabulary_handle(hdl_prefix: str) -> str:
    prefix = hdl_prefix.rstrip("/")
    if not prefix:
        raise ValueError(
            "CORDRA_HDL_PREFIX is required to resolve the default vocabulary handle "
            f"({DEFAULT_VOCABULARY_NOTATION}); use --vocabulary to supply one explicitly."
        )
    return f"{prefix}/voc.{DEFAULT_VOCABULARY_NOTATION}"


def resolve_vocabulary_id(config: Dict[str, str], cli_handle: Optional[str]) -> str:
    if cli_handle and cli_handle.strip():
        return cli_handle.strip()
    return default_vocabulary_handle(config.get("hdl_prefix", ""))


def concept_tail(concept_id: str) -> str:
    tail = concept_id.rstrip("/").split("/")[-1]
    if not tail:
        raise ValueError(f"Cannot derive tail from concept @id: {concept_id!r}")
    return tail


def concept_notation(tail: str) -> str:
    return f"{DEFAULT_VOCABULARY_NOTATION}:{tail}"


def concept_uri(tail: str) -> str:
    return f"{CONCEPT_URI_BASE}/{tail}"


def concept_handle(hdl_prefix: str, tail: str) -> str:
    prefix = hdl_prefix.rstrip("/")
    return f"{prefix}/voc.{DEFAULT_VOCABULARY_NOTATION}.{tail}"


def load_jsonld(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def parse_concepts(data: dict) -> List[dict]:
    concepts = data.get("skos:hasTopConcept") or []
    if not isinstance(concepts, list):
        raise ValueError("skos:hasTopConcept must be a list")
    return concepts


def lexical_maps_equal(a: Dict[str, object], b: Dict[str, object]) -> bool:
    return concept_lexical_maps_equal(a, b)


def plan_concepts(skos_dir: Path) -> PlanResult:
    if not skos_dir.is_dir():
        raise FileNotFoundError(f"SKOS directory not found: {skos_dir}")

    jsonld_files = sorted(skos_dir.glob("*.jsonld"))
    merged: Dict[str, MergedConcept] = {}
    label_conflicts: List[str] = []
    source_records = 0
    skipped = 0

    for path in jsonld_files:
        query_term = path.stem
        data = load_jsonld(path)
        for concept in parse_concepts(data):
            concept_id = concept.get("@id")
            if not concept_id or not isinstance(concept_id, str):
                print(f"{YELLOW}Skipping concept without @id in {path.name}{RESET}", flush=True)
                skipped += 1
                continue

            pref_label = parse_skos_pref_label(concept.get("skos:prefLabel"))
            if not pref_label:
                print(f"{YELLOW}Skipping concept without skos:prefLabel in {path.name}{RESET}", flush=True)
                skipped += 1
                continue

            alt_label = parse_skos_alt_label(concept.get("skos:altLabel"))
            definition = parse_skos_lang_text(concept.get("skos:definition"))
            scope_note = parse_skos_lang_text(concept.get("skos:scopeNote"))

            tail = concept_tail(concept_id)
            source_records += 1
            incoming_maps = build_concept_lexical_content(
                pref_label=pref_label,
                alt_label={
                    lang: [entry["label"] for entry in entries]
                    for lang, entries in alt_label.items()
                }
                if alt_label
                else None,
                definition=definition or None,
                scope_note=scope_note or None,
            )

            if tail not in merged:
                merged[tail] = MergedConcept(
                    tail=tail,
                    pref_label=pref_label,
                    alt_label=alt_label,
                    definition=definition,
                    scope_note=scope_note,
                    query_terms={query_term},
                    source_ids=[concept_id],
                )
                continue

            record = merged[tail]
            record.query_terms.add(query_term)
            record.source_ids.append(concept_id)
            if not lexical_maps_equal(record.lexical_maps(), incoming_maps):
                display = display_label(pref_label) or tail
                label_conflicts.append(
                    f"{tail} ({display}): label mismatch in {path.name} vs earlier occurrence"
                )

    return PlanResult(
        files_scanned=len(jsonld_files),
        source_records=source_records,
        skipped=skipped,
        merged=merged,
        label_conflicts=label_conflicts,
    )


def build_content(
    tail: str,
    vocabulary_id: str,
    record: MergedConcept,
    query_terms: List[str],
    handle: str,
) -> dict:
    content = {
        "id": handle,
        "$schema": SCHEMA_CONCEPT,
        "vocabulary": vocabulary_id,
        "notation": concept_notation(tail),
        "uri": concept_uri(tail),
        "queryTerms": query_terms,
    }
    content.update(
        build_concept_lexical_content(
            pref_label=record.pref_label,
            alt_label={
                lang: [entry["label"] for entry in entries]
                for lang, entries in record.alt_label.items()
            }
            if record.alt_label
            else None,
            definition=record.definition or None,
            scope_note=record.scope_note or None,
        )
    )
    return content


def build_digital_objects(
    plan: PlanResult,
    vocabulary_id: str,
    hdl_prefix: str,
) -> List[dict]:
    objects: List[dict] = []
    for tail in sorted(plan.merged):
        record = plan.merged[tail]
        handle = concept_handle(hdl_prefix, tail)
        content = build_content(
            tail,
            vocabulary_id,
            record,
            sorted(record.query_terms),
            handle,
        )
        objects.append({"id": handle, "type": CONCEPT_TYPE, "content": content})
    return objects


def print_plan_summary(plan: PlanResult, vocabulary_id: str, digital_objects: List[dict]) -> None:
    multi_query = [
        (tail, sorted(record.query_terms))
        for tail, record in sorted(plan.merged.items())
        if len(record.query_terms) > 1
    ]

    print(f"Files scanned: {plan.files_scanned}", flush=True)
    print(f"Source concept records: {plan.source_records}", flush=True)
    print(f"Skipped: {plan.skipped}", flush=True)
    print(f"Unique merged concepts: {len(plan.merged)}", flush=True)
    print(f"Vocabulary: {vocabulary_id}", flush=True)
    print(f"Upload count: {len(digital_objects)}", flush=True)

    if multi_query:
        print(f"\nConcepts with multiple queryTerms ({len(multi_query)}):", flush=True)
        for tail, query_terms in multi_query:
            print(f"  {tail}: {', '.join(query_terms)}", flush=True)

    if plan.label_conflicts:
        print(f"\n{YELLOW}Label conflicts ({len(plan.label_conflicts)}):{RESET}", flush=True)
        for message in plan.label_conflicts:
            print(f"  {message}", flush=True)


def write_output(path: Path, digital_objects: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(digital_objects, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Wrote {len(digital_objects)} object(s) to {path}", flush=True)


def ensure_vocabulary_exists(cordra: libcordra2.Cordra, vocabulary_id: str) -> None:
    if not cordra.exists(vocabulary_id):
        print(
            f"{RED}Vocabulary not found: {vocabulary_id}{RESET}\n"
            "Create the Vocabulary object in Cordra first, or pass --vocabulary.",
            flush=True,
        )
        sys.exit(1)


def upload_batch(cordra: libcordra2.Cordra, digital_objects: List[dict]) -> dict:
    if not digital_objects:
        print("Nothing to upload.", flush=True)
        return {"upserted": 0, "conflicts": 0, "failed": 0, "skipped_invalid": 0}

    print(f"Uploading {len(digital_objects)} object(s)...", flush=True)
    try:
        result = cordra.batch_upload_detailed(digital_objects).stats
    except Exception as exc:
        print(f"{RED}Cordra batch upload failed: {exc}{RESET}", flush=True)
        sys.exit(1)

    print(
        f"Batch result: upserted={result.get('upserted', 0)} "
        f"conflicts={result.get('conflicts', 0)} "
        f"failed={result.get('failed', 0)} "
        f"skipped_invalid={result.get('skipped_invalid', 0)}",
        flush=True,
    )
    return result


def ingest(
    skos_dir: Path,
    vocabulary_id: str,
    config: Dict[str, str],
    cordra: Optional[libcordra2.Cordra],
    *,
    dry_run: bool,
    output_path: Optional[Path],
) -> int:
    plan = plan_concepts(skos_dir)
    digital_objects = build_digital_objects(plan, vocabulary_id, config["hdl_prefix"])

    print_plan_summary(plan, vocabulary_id, digital_objects)

    if output_path is not None:
        write_output(output_path, digital_objects)

    if dry_run:
        print(f"\nDry run: would upload {len(digital_objects)} concept(s)", flush=True)
        return len(digital_objects)

    if cordra is None:
        print(f"{RED}Cordra client not available{RESET}", flush=True)
        sys.exit(1)

    ensure_vocabulary_exists(cordra, vocabulary_id)
    stats = upload_batch(cordra, digital_objects)

    if stats.get("failed", 0) > 0:
        sys.exit(1)

    uploaded = stats.get("upserted", 0) + stats.get("conflicts", 0)
    print(f"\n{GREEN}Uploaded {uploaded} concept(s){RESET}", flush=True)
    return uploaded


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Import SKOS JSON-LD controlled lists from a directory into Cordra "
            "as VocabularyConcept objects."
        )
    )
    parser.add_argument(
        "skos_dir",
        nargs="?",
        default=str(DEFAULT_SKOS_DIR),
        help=f"Directory containing SKOS JSON-LD files (default: {DEFAULT_SKOS_DIR})",
    )
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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and print planned objects; no Cordra writes",
    )
    parser.add_argument(
        "--output",
        metavar="FILE",
        default=None,
        help="Write generated digital objects to JSON file",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    skos_dir = Path(args.skos_dir).resolve()
    output_path = Path(args.output).resolve() if args.output else None

    config = load_config(require_cordra=not args.dry_run)
    try:
        vocabulary_id = resolve_vocabulary_id(config, args.vocabulary)
    except ValueError as exc:
        print(f"{RED}{exc}{RESET}", flush=True)
        sys.exit(1)

    if not args.dry_run:
        print(f"Cordra instance: {config['cordra_api_url']}", flush=True)

    cordra: Optional[libcordra2.Cordra] = None
    if not args.dry_run:
        cordra = libcordra2.Cordra.from_config(config, protocol="rest")

    try:
        ingest(
            skos_dir,
            vocabulary_id,
            config,
            cordra,
            dry_run=args.dry_run,
            output_path=output_path,
        )
    except FileNotFoundError as exc:
        print(f"{RED}{exc}{RESET}", flush=True)
        sys.exit(1)

    print("\nAll done!\n", flush=True)


if __name__ == "__main__":
    main()
