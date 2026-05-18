#!/usr/bin/env python3
"""
Upload and manage Cordra Schema objects from local semver-tagged schema files.

Setup:
  cd _scripts
  python -m venv .venv && source .venv/bin/activate
  pip install -r requirements.txt
  cp .env_example .env   # edit values
  python upload-schemas.py --all -m 1          # dry run / diff
  python upload-schemas.py --schema Sample       # upload if newer
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

from lib import libcordra, schema_do

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_SCHEMA_ROOT = SCRIPT_DIR.parent

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
    print(f"Cordra instance: {config['cordra_api_url']}", flush=True)
    return config


def ensure_valid_selection(all_flag: bool, schemas: Optional[List[str]]) -> None:
    if all_flag and schemas:
        print("Specify either --all or --schema, not both.")
        sys.exit(1)
    if not all_flag and not schemas:
        print("No schemas specified. Use --all or one/more --schema.")
        sys.exit(1)


def flatten_schema_args(schema_args: Optional[List[str]]) -> List[str]:
    if not schema_args:
        return []
    flattened: List[str] = []
    for item in schema_args:
        parts = [p.strip() for p in item.split(",") if p.strip()]
        flattened.extend(parts)
    seen = set()
    unique: List[str] = []
    for name in flattened:
        if name not in seen:
            unique.append(name)
            seen.add(name)
    return unique


def resolve_selected_types(
    all_flag: bool, schema_args: Optional[List[str]], base_path: Path
) -> List[str]:
    if all_flag:
        return schema_do.list_type_directories(base_path)

    requested = flatten_schema_args(schema_args)
    if not requested:
        print("No schemas specified after parsing. Use --schema.")
        sys.exit(1)

    missing: List[str] = []
    present: List[str] = []
    for name in requested:
        if name.startswith("_"):
            missing.append(name)
            continue
        full_path = base_path / name
        if full_path.is_dir():
            present.append(name)
        else:
            missing.append(name)

    if missing:
        print(
            "The following schema folders were not found or invalid "
            "(skip underscore-prefixed names): "
            + ", ".join(missing)
        )
        sys.exit(1)
    return sorted(present)


def fetch_cordra_current_and_versions(
    cordra: Optional[libcordra.Cordra], current_pid: str
) -> Tuple[Optional[Dict], List[Dict]]:
    if cordra is None:
        return None, []
    current_obj: Optional[Dict] = None
    try:
        results = cordra.query(f'id:"{current_pid}"', full=True)
        if isinstance(results, list) and len(results) > 0:
            current_obj = results[0]
    except SystemExit:
        current_obj = None

    versions_info: List[Dict] = []
    if current_obj is not None:
        try:
            version_ids = cordra.get_versions(current_pid)
            for vid in sorted(version_ids):
                v_results = cordra.query(f'id:"{vid}"', full=True)
                v_item = (
                    v_results[0]
                    if isinstance(v_results, list) and len(v_results) > 0
                    else None
                )
                schema_id = None
                if v_item and isinstance(v_item, dict):
                    content = v_item.get("content") or {}
                    schema = content.get("schema") or {}
                    schema_id = schema.get("$id")
                versions_info.append({"id": vid, "$id": schema_id})
        except SystemExit:
            versions_info = []

    return current_obj, versions_info


def print_comparison_table(
    type_name: str,
    schema_path: Path,
    resolved_id: Optional[str],
    local_versions: List[Dict],
    current_obj: Optional[Dict],
    versions_info: List[Dict],
) -> None:
    ansi_re = re.compile(r"\x1b\[[0-9;]*m")

    def strip_ansi(s: str) -> str:
        return ansi_re.sub("", s)

    def ljust_ansi(s: str, width: int) -> str:
        visible = len(strip_ansi(s))
        pad = max(0, width - visible)
        return s + (" " * pad)

    local_by_id: Dict[str, Dict] = {}
    for v in local_versions:
        sid = v.get("schema_id")
        if sid:
            local_by_id[sid] = {
                "version_tag": v.get("version_tag"),
                "has_js": v.get("has_js", False),
            }

    server_by_id: Dict[str, str] = {}
    current_schema_id = None
    if current_obj:
        content = current_obj.get("content") or {}
        schema = content.get("schema") or {}
        current_schema_id = schema.get("$id")
        if current_schema_id and resolved_id:
            server_by_id[current_schema_id] = resolved_id
    for v in versions_info:
        sid = v.get("$id")
        pid = v.get("id")
        if sid and pid:
            server_by_id[sid] = pid

    all_ids = sorted(set(list(local_by_id.keys()) + list(server_by_id.keys())))
    header = ["status", "$id (version)", "local", "server"]
    rows: List[List[str]] = []
    for sid in all_ids:
        local_cell = "-"
        server_cell = "-"
        in_local = sid in local_by_id
        in_server = sid in server_by_id
        if in_local and in_server:
            lv = local_by_id[sid]
            local_cell = f"{lv['version_tag']}" + (
                " +js" if lv.get("has_js") else ""
            )
            server_cell = server_by_id[sid]
            if current_schema_id and sid == current_schema_id:
                server_cell = f"{server_cell} (current)"
            status = "="
        elif in_local and not in_server:
            lv = local_by_id[sid]
            local_cell = f"{lv['version_tag']}" + (
                " +js" if lv.get("has_js") else ""
            )
            status = "+"
        else:
            server_cell = server_by_id[sid]
            if current_schema_id and sid == current_schema_id:
                server_cell = f"{server_cell} (current)"
            status = "-"
        rows.append([status, sid, local_cell, server_cell])

    cols = list(zip(*([header] + rows))) if rows else [header]
    widths = [max(len(str(cell)) for cell in col) for col in cols]

    print(f"\nType: {type_name}")
    print(f"Path: {schema_path}")
    print(f"Identifier: {resolved_id if resolved_id else '-'}")
    rule = "+" + "+".join(["-" * (w + 2) for w in widths]) + "+"
    print(rule)
    print("| " + " | ".join(h.ljust(widths[i]) for i, h in enumerate(header)) + " |")
    print(rule)

    for r in rows:
        status_symbol = r[0]
        if status_symbol == "=":
            status_colored = f"{GREEN}{status_symbol}{RESET}"
            local_val = r[2]
            server_val = r[3]
        elif status_symbol == "+":
            status_colored = f"{YELLOW}{status_symbol}{RESET}"
            local_val = f"{YELLOW}{r[2]}{RESET}"
            server_val = f"{RED}{r[3]}{RESET}" if r[3] != "-" else r[3]
        else:
            status_colored = f"{RED}{status_symbol}{RESET}"
            local_val = f"{YELLOW}{r[2]}{RESET}" if r[2] != "-" else r[2]
            server_val = f"{RED}{r[3]}{RESET}"

        cells = [status_colored, r[1], local_val, server_val]
        print(
            "| "
            + " | ".join(
                ljust_ansi(str(cells[i]), widths[i]) for i in range(len(widths))
            )
            + " |"
        )
    print(rule)
    print()


def parse_mode(mode_arg: str) -> int:
    mode_map = {
        "1": 1,
        "do-nothing": 1,
        "dry": 1,
        "2": 2,
        "upload-latest-if-newer": 2,
        "if-newer": 2,
        "default": 2,
        "3": 3,
        "upload-or-replace-latest": 3,
        "replace-latest": 3,
        "4": 4,
        "reupload-entire-tree": 4,
        "reupload-tree": 4,
    }
    return mode_map.get(str(mode_arg).strip().lower(), 2)


def server_version_index(
    server_schema_id: Optional[str], local_versions: List[Dict]
) -> Optional[int]:
    if not server_schema_id:
        return None
    local_id_to_index = schema_do.version_index_by_schema_id(local_versions)
    if server_schema_id in local_id_to_index:
        return local_id_to_index[server_schema_id]
    server_version = schema_do.parse_version_from_schema_id(server_schema_id)
    if server_version is None:
        return None
    for idx, v in enumerate(local_versions):
        if v["parsed_version"] == server_version:
            return idx
    return None


def upload_version(
    cordra: libcordra.Cordra,
    identifier: str,
    do_obj: Dict,
    schema_id: str,
    *,
    create: bool,
) -> None:
    if create:
        print(f"  - create current {identifier}", end="")
        cordra.create(obj=do_obj, type="Schema", pid=identifier)
    else:
        print(f"  - update current {identifier}", end="")
        cordra.update(pid=identifier, obj=do_obj)
    print(f" --> {GREEN}OK{RESET}")

    version_suffix = schema_do.version_suffix_from_schema_id(schema_id)
    version_pid = f"{identifier}/{version_suffix}"
    print(f"  - create version {version_pid}", end="")
    cordra.create_version(pid=identifier, version_pid=version_pid)
    print(f" --> {GREEN}OK{RESET}")


def process_type(
    type_name: str,
    base_path: Path,
    config: Dict[str, str],
    cordra: Optional[libcordra.Cordra],
    mode: int,
) -> bool:
    """Process one schema type. Returns True on success, False on failure."""
    schema_dir = base_path / type_name
    identifier = schema_do.default_identifier(config["hdl_prefix"], type_name)

    local_versions = schema_do.collect_schema_versions(schema_dir)
    current_obj: Optional[Dict] = None
    versions_info: List[Dict] = []
    try:
        current_obj, versions_info = fetch_cordra_current_and_versions(
            cordra, identifier
        )
    except Exception:
        current_obj, versions_info = None, []

    print_comparison_table(
        type_name=type_name,
        schema_path=schema_dir,
        resolved_id=identifier,
        local_versions=local_versions,
        current_obj=current_obj,
        versions_info=versions_info,
    )

    if mode == 1:
        return True

    if cordra is None:
        print(f"- {type_name}: Cordra unavailable; cannot upload")
        return False

    if not local_versions:
        print(f"- {type_name}: no local versions; no action")
        return True

    newest_local = local_versions[-1]
    newest_local_schema_id = newest_local.get("schema_id")
    newest_index = len(local_versions) - 1

    server_current_schema_id = None
    if current_obj:
        content = current_obj.get("content") or {}
        schema = content.get("schema") or {}
        server_current_schema_id = schema.get("$id")

    server_index = server_version_index(server_current_schema_id, local_versions)

    if mode in (2, 3):
        take_action = False
        replace_existing = False
        reason = ""

        if server_index is None:
            take_action = True
            reason = "server current $id not found locally; treat local newest as newer"
        elif server_index < newest_index:
            take_action = True
            reason = "local newest is newer than server current"
        elif (
            mode == 3
            and server_current_schema_id
            and newest_local_schema_id
            and server_current_schema_id == newest_local_schema_id
        ):
            take_action = True
            replace_existing = True
            reason = "local newest equals server current (replace)"

        if not take_action:
            print(f"- {type_name}: no action (mode {mode})")
            return True

        print(f"- {type_name}: {reason}")

        if replace_existing and server_current_schema_id:
            matching_ver_pid = None
            for v in versions_info:
                if v.get("$id") == server_current_schema_id:
                    matching_ver_pid = v.get("id")
                    break
            if matching_ver_pid:
                print(f"  - delete version {matching_ver_pid}", end="")
                cordra.delete(pid=matching_ver_pid)
                print(f" --> {GREEN}OK{RESET}")

        do_obj = schema_do.prepare_do_for_version(
            schema_dir,
            newest_local,
            identifier=identifier,
            type_dir_name=type_name,
        )
        if not isinstance(do_obj, dict):
            print("  ! Failed to prepare DO object; skipping")
            return False

        if not newest_local_schema_id:
            print("  ! Newest local version has no $id; skipping")
            return False

        try:
            upload_version(
                cordra,
                identifier,
                do_obj,
                newest_local_schema_id,
                create=current_obj is None,
            )
        except SystemExit:
            return False
        return True

    if mode == 4:
        print(f"- {type_name}: reupload entire tree")
        try:
            if current_obj is not None:
                for v in versions_info:
                    if v.get("id"):
                        print(f"  - delete version {v['id']}", end="")
                        cordra.delete(pid=v["id"])
                        print(f" --> {GREEN}OK{RESET}")
                print(f"  - delete current {identifier}", end="")
                cordra.delete(pid=identifier)
                print(f" --> {GREEN}OK{RESET}")

            for idx, v in enumerate(local_versions):
                do_obj = schema_do.prepare_do_for_version(
                    schema_dir,
                    v,
                    identifier=identifier,
                    type_dir_name=type_name,
                )
                if not isinstance(do_obj, dict):
                    print(
                        f"  ! Failed to prepare DO for version tag "
                        f"{v['version_tag']}; skipping"
                    )
                    return False
                schema_id = v.get("schema_id")
                if not schema_id:
                    print(
                        f"  ! Version {v['version_tag']} has no $id; skipping"
                    )
                    return False
                upload_version(
                    cordra,
                    identifier,
                    do_obj,
                    schema_id,
                    create=idx == 0,
                )
        except SystemExit:
            return False
        return True

    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upload and manage Cordra Schema objects."
    )
    parser.add_argument(
        "-p",
        "--path",
        dest="path",
        default=str(DEFAULT_SCHEMA_ROOT),
        help="Path to the schema root directory (default: repo root)",
    )
    parser.add_argument(
        "-a",
        "--all",
        dest="all",
        action="store_true",
        help="Process all schema type folders (exclude underscore-prefixed)",
    )
    parser.add_argument(
        "-s",
        "--schema",
        dest="schemas",
        action="append",
        help="Schema type folder name (repeatable or comma-separated)",
    )
    parser.add_argument(
        "-m",
        "--mode",
        dest="mode",
        default="2",
        help=(
            "Mode: 1=dry-run, 2=upload-latest-if-newer (default), "
            "3=upload-or-replace-latest, 4=reupload-entire-tree"
        ),
    )
    args = parser.parse_args()

    config = load_config()
    base_path = Path(args.path).resolve()
    ensure_valid_selection(args.all, args.schemas)
    selected = resolve_selected_types(args.all, args.schemas, base_path)
    mode = parse_mode(args.mode)

    print(
        f"Selected schemas ({len(selected)}): "
        f"{', '.join(selected) if selected else '-'}"
    )

    cordra: Optional[libcordra.Cordra] = None
    try:
        cordra = libcordra.Cordra(
            config["cordra_api_url"],
            config["cordra_username"],
            config["cordra_password"],
        )
    except (SystemExit, requests.RequestException) as exc:
        if mode == 1:
            print(
                "Warning: Could not connect to Cordra "
                f"({exc}). Showing local schema state only.\n"
            )
        else:
            print(f"Could not initialize Cordra client: {exc}")
            sys.exit(1)

    failures: List[str] = []
    for type_name in selected:
        ok = process_type(type_name, base_path, config, cordra, mode)
        if not ok:
            failures.append(type_name)

    print("\nAll done!\n")
    if failures:
        print(f"Failed types: {', '.join(failures)}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
