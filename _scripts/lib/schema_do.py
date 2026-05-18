#!/usr/bin/env python3
"""Discover local schema versions and build Cordra Schema DO payloads."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlunparse

from packaging.version import InvalidVersion, Version

VERSION_TAG_RE = re.compile(r"^v\d+(\.\d+)*$", re.IGNORECASE)
VERSION_SEGMENT_RE = re.compile(
    r"^v\d+(\.\d+)*(\.schema\.json)?$", re.IGNORECASE
)


def read_json_safely(file_path: str | Path) -> Optional[Dict[str, Any]]:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception as exc:
        print(f"  ! Failed to read JSON '{file_path}': {exc}")
        return None


def parse_version_tag(version_tag: str) -> Version:
    """Parse a filename version tag such as 'v0.9' into a packaging Version."""
    tag = version_tag.strip()
    if tag.lower().startswith("v"):
        tag = tag[1:]
    return Version(tag)


def parse_version_from_schema_id(schema_id: Optional[str]) -> Optional[Version]:
    if not schema_id or not isinstance(schema_id, str):
        return None
    segment = schema_id.rstrip("/").rsplit("/", 1)[-1]
    if VERSION_SEGMENT_RE.match(segment):
        return parse_version_tag(segment.split(".schema.json")[0])
    return None


def derive_base_uri(schema_id: str) -> str:
    """Remove the version tail from a schema $id URL to obtain baseUri."""
    parsed = urlparse(schema_id)
    segments = [s for s in parsed.path.split("/") if s]
    if segments and VERSION_SEGMENT_RE.match(segments[-1]):
        segments = segments[:-1]
    path = "/" + "/".join(segments) if segments else ""
    return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))


def default_identifier(hdl_prefix: str, type_dir_name: str) -> str:
    prefix = hdl_prefix.rstrip("/")
    return f"{prefix}/schema.{type_dir_name.lower()}"


def list_type_directories(base_path: str | Path) -> List[str]:
    base = Path(base_path)
    if not base.is_dir():
        raise FileNotFoundError(f"Path is not a directory: {base}")

    type_dirs: List[str] = []
    for entry in sorted(base.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith(("_", ".")):
            continue
        type_dirs.append(entry.name)
    return type_dirs


def collect_schema_versions(schema_dir: str | Path) -> List[Dict[str, Any]]:
    schema_path = Path(schema_dir)
    versions: List[Dict[str, Any]] = []

    for file_path in sorted(schema_path.glob("v*.schema.json")):
        version_tag = file_path.name[: -len(".schema.json")]
        if not VERSION_TAG_RE.match(version_tag):
            print(f"  ! Skipping non-semver schema file: {file_path.name}")
            continue

        try:
            parsed_version = parse_version_tag(version_tag)
        except InvalidVersion as exc:
            print(f"  ! Skipping unparseable version '{version_tag}': {exc}")
            continue

        schema_json = read_json_safely(file_path)
        schema_id = schema_json.get("$id") if schema_json else None
        js_path = schema_path / f"{version_tag}.schema.js"
        has_js = js_path.is_file()

        versions.append(
            {
                "version_tag": version_tag,
                "schema_file": file_path.name,
                "schema_path": str(file_path),
                "schema_id": schema_id,
                "parsed_version": parsed_version,
                "has_js": has_js,
                "js_path": str(js_path) if has_js else None,
            }
        )

    versions.sort(key=lambda v: v["parsed_version"])
    return versions


def read_javascript(js_path: Optional[str]) -> Optional[str]:
    if not js_path or not os.path.isfile(js_path):
        return None
    try:
        with open(js_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as exc:
        print(f"  ! Failed to read JavaScript '{js_path}': {exc}")
        return None


def build_do(
    schema_json: Dict[str, Any],
    *,
    identifier: str,
    type_dir_name: str,
    javascript: Optional[str] = None,
) -> Dict[str, Any]:
    schema_id = schema_json.get("$id")
    if not isinstance(schema_id, str) or not schema_id.strip():
        raise ValueError(f"Schema for {type_dir_name} is missing a non-empty $id")

    do_obj: Dict[str, Any] = {
        "identifier": identifier,
        "name": schema_json.get("title", type_dir_name),
        "baseUri": derive_base_uri(schema_id),
        "schema": schema_json,
        "hashObject": True,
        "indexObjects": True,
        "indexPayloads": False,
    }
    if javascript is not None:
        do_obj["javascript"] = javascript
    return do_obj


def prepare_do_for_version(
    schema_dir: str | Path,
    version_info: Dict[str, Any],
    *,
    identifier: str,
    type_dir_name: str,
) -> Optional[Dict[str, Any]]:
    schema_json = read_json_safely(version_info["schema_path"])
    if not isinstance(schema_json, dict):
        return None
    javascript = read_javascript(version_info.get("js_path"))
    return build_do(
        schema_json,
        identifier=identifier,
        type_dir_name=type_dir_name,
        javascript=javascript,
    )


def version_index_by_schema_id(versions: List[Dict[str, Any]]) -> Dict[str, int]:
    mapping: Dict[str, int] = {}
    for idx, v in enumerate(versions):
        sid = v.get("schema_id")
        if sid:
            mapping[sid] = idx
    return mapping


def version_suffix_from_schema_id(schema_id: str) -> str:
    return schema_id.rsplit("/", 1)[-1]
