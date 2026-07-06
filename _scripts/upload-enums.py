#!/usr/bin/env python3
"""
Upload one SKOS JSON-LD controlled list to Cordra as VocabularyConcept objects.

Uses an existing Vocabulary object (default: {hdl_prefix}/voc.heritagesamples).
Override with --vocabulary when concepts belong to another scheme.

Usage:
  cd _scripts
  python upload-enums.py ../skos/Sample-titleType.jsonld titleType titleType
  python upload-enums.py ../skos/Sample-titleType.jsonld titleType titleType --dry-run
  python upload-enums.py ../skos/Sample-titleType.jsonld titleType titleType -v HSR/voc.aat
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

from lib import libcordra2
from lib.skos_lang import display_label, parse_skos_pref_label

SCRIPT_DIR = Path(__file__).resolve().parent
CONCEPT_TYPE = "VocabularyConcept"
SCHEMA_CONCEPT = "https://heritagesamples.org/schema/VocabularyConcept/v0.9"
DEFAULT_VOCABULARY_NOTATION = "heritagesamples"

GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"


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


def concept_notation(query_term: str, concept_id: Optional[str], pref_label: str) -> str:
    if concept_id:
        tail = concept_id.rstrip("/").split("/")[-1]
        slug = re.sub(r"[^a-z0-9]+", "", tail.lower()) or "term"
        return f"{query_term.lower()}:{slug}"
    slug = re.sub(r"[^a-z0-9]+", "", pref_label.lower()) or "term"
    return f"{query_term.lower()}:{slug}"


def concept_handle(hdl_prefix: str, notation: str) -> str:
    prefix = hdl_prefix.rstrip("/")
    return f"{prefix}/voc.{notation.replace(':', '.')}"


def load_jsonld(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def parse_concepts(data: dict) -> tuple[Optional[str], List[dict]]:
    scheme_id = data.get("@id")
    concepts = data.get("skos:hasTopConcept") or []
    if not isinstance(concepts, list):
        raise ValueError("skos:hasTopConcept must be a list")
    return scheme_id, concepts


def pref_label_display(pref_label: Dict[str, str]) -> str:
    return display_label(pref_label) or "term"


def build_top_content(
    handle: str,
    vocabulary_id: str,
    pref_label: Dict[str, str],
    query_term: str,
    scheme_id: Optional[str],
) -> dict:
    notation = f"{query_term.lower()}:top"
    content: dict = {
        "id": handle,
        "$schema": SCHEMA_CONCEPT,
        "vocabulary": vocabulary_id,
        "notation": notation,
        "prefLabel": pref_label,
        "broader": [],
        "queryTerms": [query_term, "TOP_LEVEL"],
    }
    if scheme_id:
        content["uri"] = f"{scheme_id.rstrip('/')}/top"
        content["exactMatch"] = [{"uri": scheme_id, "scheme": "HS"}]
    return content


def build_term_content(
    handle: str,
    vocabulary_id: str,
    pref_label: Dict[str, str],
    query_term: str,
    notation: str,
    top_handle: str,
    concept_id: Optional[str],
) -> dict:
    content: dict = {
        "id": handle,
        "$schema": SCHEMA_CONCEPT,
        "vocabulary": vocabulary_id,
        "notation": notation,
        "prefLabel": pref_label,
        "broader": [top_handle],
        "queryTerms": [query_term],
    }
    if concept_id:
        content["uri"] = concept_id
        content["exactMatch"] = [{"uri": concept_id, "scheme": "HS"}]
    return content


def upload_object(cordra: libcordra2.Cordra, content: dict) -> bool:
    digital_object = {
        "id": content["id"],
        "type": CONCEPT_TYPE,
        "content": content,
    }
    try:
        result = cordra.batch_upload_detailed([digital_object]).stats
    except Exception as exc:
        print(f"{RED}Cordra upload failed: {exc}{RESET}", flush=True)
        return False

    if result.get("failed", 0) > 0:
        print(f"{RED}Cordra rejected upload for {content['id']}{RESET}", flush=True)
        return False
    return True


def ensure_vocabulary_exists(cordra: libcordra2.Cordra, vocabulary_id: str) -> None:
    if not cordra.exists(vocabulary_id):
        print(
            f"{RED}Vocabulary not found: {vocabulary_id}{RESET}\n"
            "Create the Vocabulary object in Cordra first, or pass --vocabulary.",
            flush=True,
        )
        sys.exit(1)


def ingest(
    jsonld_path: Path,
    top_level_term: str,
    query_term: str,
    vocabulary_id: str,
    config: Dict[str, str],
    cordra: Optional[libcordra2.Cordra],
    *,
    dry_run: bool,
    cordra_sleep: float,
) -> int:
    data = load_jsonld(jsonld_path)
    scheme_id, concepts = parse_concepts(data)

    top_pref_label = parse_skos_pref_label(top_level_term)
    if not top_pref_label:
        print(f"{RED}Top-level term is empty{RESET}", flush=True)
        sys.exit(1)

    top_handle = concept_handle(config["hdl_prefix"], f"{query_term.lower()}:top")
    top_content = build_top_content(
        top_handle,
        vocabulary_id,
        top_pref_label,
        query_term,
        scheme_id,
    )

    top_display = pref_label_display(top_pref_label)
    print(f"File: {jsonld_path}", flush=True)
    print(f"Query term: {query_term}", flush=True)
    print(f"Vocabulary (existing): {vocabulary_id}", flush=True)
    print(f"Top-level concept: {top_handle} ({top_display})", flush=True)

    planned: List[tuple[str, str, dict]] = []
    for concept in concepts:
        pref_label = parse_skos_pref_label(concept.get("skos:prefLabel"))
        if not pref_label:
            print(f"{RED}Skipping concept without skos:prefLabel{RESET}", flush=True)
            continue
        concept_id = concept.get("@id")
        display = pref_label_display(pref_label)
        notation = concept_notation(query_term, concept_id, display)
        handle = concept_handle(config["hdl_prefix"], notation)
        term_content = build_term_content(
            handle,
            vocabulary_id,
            pref_label,
            query_term,
            notation,
            top_handle,
            concept_id,
        )
        planned.append((handle, display, term_content))

    for handle, display, _content in planned:
        print(f"  term: {handle} ({display})", flush=True)

    total = len(planned) + 1
    if dry_run:
        print(f"Dry run: would upload 1 top + {len(planned)} terms", flush=True)
        return total

    if cordra is None:
        print(f"{RED}Cordra client not available{RESET}", flush=True)
        sys.exit(1)

    ensure_vocabulary_exists(cordra, vocabulary_id)

    uploaded = 0
    if upload_object(cordra, top_content):
        print(f"{GREEN}uploaded top: {top_handle}{RESET}", flush=True)
        uploaded += 1
    else:
        print(f"{RED}failed top: {top_handle}{RESET}", flush=True)
        sys.exit(1)
    if cordra_sleep > 0:
        time.sleep(cordra_sleep)

    for handle, display, term_content in planned:
        if upload_object(cordra, term_content):
            print(f"{GREEN}uploaded: {handle} ({display}){RESET}", flush=True)
            uploaded += 1
        else:
            print(f"{RED}failed: {handle} ({display}){RESET}", flush=True)
        if cordra_sleep > 0:
            time.sleep(cordra_sleep)

    print(
        f"\nSummary: query_term={query_term} vocabulary={vocabulary_id} "
        f"top={top_handle} terms={len(planned)} uploaded={uploaded}",
        flush=True,
    )
    return uploaded


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload one SKOS JSON-LD controlled list to Cordra as VocabularyConcept objects."
    )
    parser.add_argument(
        "jsonld_file",
        help="Path to the SKOS JSON-LD file to ingest",
    )
    parser.add_argument(
        "top_level_term",
        help="prefLabel for the scheme root concept",
    )
    parser.add_argument(
        "query_term",
        help="queryTerms value for all uploaded concepts",
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
        help="Parse and print planned handles; no Cordra writes",
    )
    parser.add_argument(
        "--cordra-sleep",
        type=float,
        default=0.2,
        help="Seconds to sleep between Cordra requests (default: 0.2)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    jsonld_path = Path(args.jsonld_file).resolve()
    if not jsonld_path.is_file():
        print(f"File not found: {jsonld_path}", flush=True)
        sys.exit(1)

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

    ingest(
        jsonld_path,
        args.top_level_term.strip(),
        args.query_term.strip(),
        vocabulary_id,
        config,
        cordra,
        dry_run=args.dry_run,
        cordra_sleep=args.cordra_sleep,
    )
    print("\nAll done!\n", flush=True)


if __name__ == "__main__":
    main()
