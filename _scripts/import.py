#!/usr/bin/env python3
"""
Upload Digital Objects from JSON / JSONL files via Cordra batch upload.

Port of cordra-config/scripts/meta-import.py (cordra_client based). Connection
settings come from _scripts/.env (see .env_example).

Usage:
  python import.py -i output/vocabularies.json
  python import.py -i output/            # all *.json / *.jsonl in a directory
  python import.py -i 'output/*.json'    # quote globs
"""

import argparse
import glob
import json
import os
import sys
import time

from cordra_client import Cordra, CordraConfigError
from lib import libcordra_utils
from lib.libreporting import ConsoleReporter, emit_critical, reporter_or_null, HarvestAbort


def _is_object_file(path: str) -> bool:
    lower = path.lower()
    return os.path.isfile(path) and (lower.endswith(".json") or lower.endswith(".jsonl"))


def expand_one(pattern: str) -> list[str]:
    """Expand one -i argument to object files, sorted alphanumerically."""
    if os.path.isfile(pattern):
        return [pattern]
    if os.path.isdir(pattern):
        files = [
            os.path.join(pattern, name)
            for name in os.listdir(pattern)
            if _is_object_file(os.path.join(pattern, name))
        ]
        return sorted(files)
    matches = glob.glob(pattern, recursive=("**" in pattern))
    files = [path for path in matches if _is_object_file(path)]
    return sorted(files)


def expand_input_paths(patterns: list[str]) -> list[str]:
    """
    Resolve -i arguments to files.

    Each argument may be a file, a directory (non-recursive *.json / *.jsonl),
    or a glob. Directory and glob expansions are sorted alphanumerically
    (Python code-point order). Multiple arguments keep CLI order, with
    duplicates dropped after first occurrence.

    Quote globs so this function expands them, e.g. -i 'vocab/*.json'.
    """
    resolved: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        files = expand_one(pattern)
        if not files:
            raise SystemExit(f"No input files matched: {pattern}")
        for path in files:
            key = os.path.abspath(path)
            if key in seen:
                continue
            seen.add(key)
            resolved.append(path)
    return resolved


def read_objects(path: str, fmt: str) -> list[dict]:
    """
    This function reads digital objects from a file on disk.
    """
    if fmt == "auto":
        fmt = "jsonl" if path.lower().endswith(".jsonl") else "json"

    if fmt == "json":
        with open(path, "r", encoding="utf-8") as f:
            objs = json.load(f)
        if not isinstance(objs, list):
            raise SystemExit(f"Expected JSON array in {path}")
        return objs

    # jsonl: typically not used.
    objs: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                objs.append(json.loads(line))
            except Exception as e:
                raise SystemExit(f"Bad JSONL at {path}:{line_no}: {e}")
    return objs


def main(config: dict, input_paths: list[str], inputfmt: str, batch_size: int, sleeptime: float, protocol=None, reporter=None) -> None:
    rep = reporter_or_null(reporter)
    protocol = libcordra_utils.resolve_protocol(config, protocol)
    try:
        client = Cordra(**libcordra_utils.cordra_kwargs(config, protocol=protocol))
    except CordraConfigError as exc:
        emit_critical(rep, str(exc), category="cordra_connect")

    total_stats = {"upserted": 0, "conflicts": 0, "failed": 0, "skipped_invalid": 0}
    many_files = len(input_paths) > 1
    rep.emit("info", f"Uploading {len(input_paths)} file(s) via Cordra {protocol} Batch Upload...")

    for input_path in input_paths:
        objects = read_objects(input_path, inputfmt)
        rep.emit("info", f"Read {len(objects)} objects from {input_path}")

        batches = [objects[i:i + batch_size] for i in range(0, len(objects), batch_size)]

        for bi, batch in enumerate(batches, start=1):
            if many_files:
                label = f"{input_path} batch {bi}/{len(batches)}"
            else:
                label = f"batch {bi}/{len(batches)}"
            rep.emit("progress", f"Processing {label} ({len(batch)} items)...")

            stats = libcordra_utils.batch_upload_stats(client, batch, reporter=rep)

            for key in total_stats:
                total_stats[key] += stats[key]

            if sleeptime > 0:
                time.sleep(sleeptime)

    rep.emit("info", f"Finished. Total Stats: {total_stats}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload Digital Objects from JSON / JSONL files via Cordra batch upload.")
    parser.add_argument(
        "-i",
        "--input",
        dest="input",
        nargs="+",
        required=True,
        help=(
            "Input file, directory, or glob (repeatable). Directories and globs "
            "are expanded and sorted alphanumerically. Quote globs so the script "
            "expands them: -i vocab/  or  -i 'vocab/*.json'."
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Override batch size (default: CORDRA_DEFAULT_BATCH_SIZE from .env, else 250).",
    )
    parser.add_argument("--sleeptime", dest="sleeptime", type=float, default=0.0, help="Seconds to sleep between batches.")
    parser.add_argument("--inputfmt", choices=["json", "jsonl", "auto"], default="auto")
    parser.add_argument("--protocol", choices=["doip", "rest"], default=None, help="Cordra protocol (default: CORDRA_PROTOCOL from .env, else rest).")

    args = parser.parse_args()

    config = libcordra_utils.load_env_config()
    print(f"Cordra instance: {config['url']}", flush=True)

    batch_size = libcordra_utils.resolve_batch_size(config, args.batch_size)
    reporter = ConsoleReporter()
    try:
        main(
            config,
            expand_input_paths(args.input),
            inputfmt=args.inputfmt,
            batch_size=batch_size,
            sleeptime=args.sleeptime,
            protocol=args.protocol,
            reporter=reporter,
        )
    except HarvestAbort:
        sys.exit(1)
