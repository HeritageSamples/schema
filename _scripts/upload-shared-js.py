#!/usr/bin/env python3
"""
Upload shared JavaScript modules to Cordra as a JavaScriptDirectory object.

Modules in _shared_js/ are mounted at /node_modules so type schema JS can
require them (e.g. require('vocab')).

Setup:
  cd _scripts
  python -m venv .venv && source .venv/bin/activate
  pip install -r requirements.txt
  cp .env_example .env   # edit values

Prerequisites (run in order):
  1. python upload-schemas.py --schema JavaScriptDirectory
  2. python upload-shared-js.py
  3. python upload-schemas.py --all   # or re-upload schemas that require shared JS

Usage:
  python upload-shared-js.py
  python upload-shared-js.py -d ../_shared_js
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv

from lib import libcordra2

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_SHARED_JS_DIR = SCRIPT_DIR.parent / "_shared_js"
BASIS_DO_FILENAME = "jsdir.node_modules.do.json"
JSDIR_HANDLE_SUFFIX = "jsdir.node_modules"


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


def load_do_content(shared_js_dir: Path) -> Dict:
    basis_path = shared_js_dir / BASIS_DO_FILENAME
    if not basis_path.is_file():
        print(f"Basis DO JSON not found: {basis_path}", flush=True)
        sys.exit(1)
    try:
        with basis_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print(f"Failed to read basis DO JSON: {exc}", flush=True)
        sys.exit(1)


def collect_js_payloads(shared_js_dir: Path) -> List[Dict]:
    payloads: List[Dict] = []
    for entry in sorted(shared_js_dir.iterdir()):
        if not entry.is_file() or entry.suffix != ".js":
            continue
        try:
            script = entry.read_text(encoding="utf-8")
        except Exception as exc:
            print(f"Warning: skip '{entry.name}' (read error: {exc})", flush=True)
            continue
        payload_name = entry.stem
        payloads.append({
            "base64Payload": base64.b64encode(script.encode("utf-8")).decode("utf-8"),
            "name": payload_name,
            "filename": entry.name,
            "mediaType": "text/javascript",
            "size": len(script),
        })
    return payloads


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upload shared JS libs as a JavaScriptDirectory object."
    )
    parser.add_argument(
        "-d",
        "--dir",
        dest="shared_js_dir",
        default=str(DEFAULT_SHARED_JS_DIR),
        help=f"Directory containing shared .js modules (default: {DEFAULT_SHARED_JS_DIR})",
    )
    args = parser.parse_args()

    shared_js_dir = Path(args.shared_js_dir).resolve()
    if not shared_js_dir.is_dir():
        print(f"Shared JS directory not found: {shared_js_dir}", flush=True)
        sys.exit(1)

    config = load_config()

    content = load_do_content(shared_js_dir)
    payloads_list = collect_js_payloads(shared_js_dir)
    if not payloads_list:
        print("No .js files found to upload.", flush=True)
        sys.exit(1)

    print(f"Shared JS directory: {shared_js_dir}", flush=True)
    print(f"Modules: {', '.join(p['name'] for p in payloads_list)}", flush=True)

    cordra = libcordra2.Cordra.from_config(config, protocol="rest")

    prefix = config["hdl_prefix"].rstrip("/")
    pid = f"{prefix}/{JSDIR_HANDLE_SUFFIX}"

    print(f"GET {pid}", flush=True)
    exists = False
    try:
        cordra.get_by_handle(pid, full=True)
        exists = True
        print("  -> found", flush=True)
    except libcordra2.CordraNotFound:
        print("  -> not found", flush=True)

    if exists:
        print(f"DELETE {pid}", flush=True)
        try:
            cordra.delete(pid)
            print("  -> deleted", flush=True)
        except libcordra2.CordraError as exc:
            print(f"  -> delete failed: {exc}", flush=True)
            sys.exit(1)

    do = {
        "id": pid,
        "type": "JavaScriptDirectory",
        "content": content,
        "payloads": payloads_list,
    }

    print("POST batchUpload (JavaScriptDirectory with payloads)", flush=True)
    try:
        resp = cordra.batch_upload([do])
        success = resp.get("success") if isinstance(resp, dict) else None
        if success:
            print("  -> upload OK", flush=True)
        else:
            print(f"  -> upload response: {json.dumps(resp)}", flush=True)
            sys.exit(1)
    except libcordra2.CordraError as exc:
        print(f"  -> upload failed: {exc}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
