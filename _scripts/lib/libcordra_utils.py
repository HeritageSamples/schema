#!/usr/bin/env python3
"""
Cordra .env settings → kwargs and batch upload helpers (cordra_client based).

Port of cordra-config/scripts/lib/libcordra_utils.py. Connection settings come
from _scripts/.env (see .env_example) instead of a settings.json ``cordra``
block. Scripts construct clients with ``Cordra(**cordra_kwargs(config))`` and
own reporting for ``CordraConfigError``.

The older scripts in this directory use lib/libcordra.py / lib/libcordra2.py
and are not affected by this module.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version as pkg_version
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from cordra_client import CordraConfigError, CordraError
from dotenv import load_dotenv
from packaging.version import Version

from lib.libreporting import Reporter, emit_critical, reporter_or_null

SCRIPT_DIR = Path(__file__).resolve().parent.parent

# Minimum cordra-client required by these scripts (bump with the requirements pin).
CORDRA_CLIENT_MIN_VERSION = "0.3.2"

DEFAULT_BATCH_SIZE = 250


def require_cordra_client(min_version: str = CORDRA_CLIENT_MIN_VERSION) -> str:
    """Return installed version, or raise RuntimeError if missing/too old."""
    try:
        import cordra_client

        installed = getattr(cordra_client, "__version__", None) or pkg_version(
            "cordra-client"
        )
    except PackageNotFoundError as exc:
        raise RuntimeError(
            "cordra-client is not installed; run: pip install -r requirements.txt"
        ) from exc

    if installed.endswith("+unknown") or Version(installed) < Version(min_version):
        raise RuntimeError(
            f"cordra-client {installed!r} is incompatible; need >={min_version}. "
            f"Run: pip install -r requirements.txt"
        )
    return installed


# --------------------------------------------------
# DIGITAL OBJECT ACCESSORS
# --------------------------------------------------


def content_of(obj: dict) -> dict:
    """Read content from a Digital Object or legacy Cordra wrapper."""
    attrs = obj.get("attributes") if isinstance(obj.get("attributes"), dict) else {}
    if isinstance(attrs.get("content"), dict):
        return attrs["content"]
    content = obj.get("content")
    return content if isinstance(content, dict) else {}


def metadata_of(obj: dict) -> dict:
    """Read metadata from a Digital Object or legacy Cordra wrapper."""
    attrs = obj.get("attributes") if isinstance(obj.get("attributes"), dict) else {}
    if isinstance(attrs.get("metadata"), dict):
        return attrs["metadata"]
    metadata = obj.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def elements_of(obj: dict) -> list:
    """Read elements/payloads from a Digital Object or legacy Cordra wrapper."""
    if isinstance(obj.get("elements"), list):
        return obj["elements"]
    payloads = obj.get("payloads")
    return payloads if isinstance(payloads, list) else []


def user_metadata_of(obj: dict) -> dict:
    """Read userMetadata from a Digital Object or legacy Cordra wrapper."""
    attrs = obj.get("attributes") if isinstance(obj.get("attributes"), dict) else {}
    if isinstance(attrs.get("userMetadata"), dict):
        return attrs["userMetadata"]
    user_metadata = obj.get("userMetadata")
    return user_metadata if isinstance(user_metadata, dict) else {}


def acl_of(obj: dict) -> dict:
    """Read acl from a Digital Object or legacy Cordra wrapper."""
    attrs = obj.get("attributes") if isinstance(obj.get("attributes"), dict) else {}
    if isinstance(attrs.get("acl"), dict):
        return attrs["acl"]
    acl = obj.get("acl")
    return acl if isinstance(acl, dict) else {}



# --------------------------------------------------
# CONFIG (.env)
# --------------------------------------------------


_REQUIRED_ENV = {
    "CORDRA_REST_API_URL": "url",
    "CORDRA_ADMIN_USERNAME": "username",
    "CORDRA_ADMIN_PASSWORD": "password",
}

_OPTIONAL_ENV = {
    "CORDRA_PROTOCOL": "protocol",
    "CORDRA_VERIFY_TLS": "verify",
    "CORDRA_DOIP_HOST": "doip_host",
    "CORDRA_DOIP_PORT": "doip_port",
    "CORDRA_DOIP_SERVICE_ID": "service_id",
    "CORDRA_DEFAULT_BATCH_SIZE": "default_batch_size",
}


def load_env_config(env_path: Optional[Path] = None) -> dict:
    """Load _scripts/.env and return a flat config dict; exit if required keys are missing."""
    load_dotenv(env_path or SCRIPT_DIR / ".env")

    config: Dict[str, str] = {}
    missing: List[str] = []
    for env_key, config_key in _REQUIRED_ENV.items():
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

    config["url"] = config["url"].rstrip("/")

    for env_key, config_key in _OPTIONAL_ENV.items():
        value = os.environ.get(env_key, "").strip()
        if value:
            config[config_key] = value

    return config


def resolve_batch_size(config: dict, override: Optional[int] = None) -> int:
    """Return CLI override, else CORDRA_DEFAULT_BATCH_SIZE, else 250."""
    if override is not None:
        return int(override)
    return int(config.get("default_batch_size") or DEFAULT_BATCH_SIZE)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


# --------------------------------------------------
# CONNECT
# --------------------------------------------------


def resolve_protocol(config: dict, override: Optional[str] = None) -> str:
    """Return CLI override or CORDRA_PROTOCOL (default ``rest``)."""
    if override is not None and str(override).strip():
        return str(override).strip().lower()
    return str(config.get("protocol") or "rest").strip().lower()


def _require_str(config: dict, key: str, env_key: str) -> str:
    value = config.get(key)
    if value is None or not str(value).strip():
        raise CordraConfigError(f"Missing Cordra setting: {env_key}")
    return str(value).strip()


def cordra_kwargs(
    config: dict,
    *,
    protocol: Optional[str] = None,
    anonymous: bool = False,
) -> dict[str, Any]:
    """Map the .env config dict to ``cordra_client.Cordra`` constructor kwargs."""
    require_cordra_client()
    effective_protocol = resolve_protocol(config, protocol)
    if effective_protocol not in {"rest", "doip"}:
        raise CordraConfigError(
            f"Invalid Cordra protocol {effective_protocol!r} (expected rest or doip)"
        )
    kwargs: dict[str, Any] = {
        "url": _require_str(config, "url", "CORDRA_REST_API_URL"),
        "verify": _as_bool(config.get("verify", False)),
        "protocol": effective_protocol,
    }

    if anonymous:
        kwargs["username"] = None
        kwargs["password"] = None
    else:
        kwargs["username"] = _require_str(config, "username", "CORDRA_ADMIN_USERNAME")
        kwargs["password"] = _require_str(config, "password", "CORDRA_ADMIN_PASSWORD")

    if effective_protocol == "doip":
        doip_port = config.get("doip_port")
        if doip_port is None or not str(doip_port).strip():
            raise CordraConfigError(
                "Missing Cordra setting: CORDRA_DOIP_PORT (required for protocol=doip)"
            )
        kwargs["doip_port"] = int(doip_port)
        kwargs["service_id"] = _require_str(
            config, "service_id", "CORDRA_DOIP_SERVICE_ID (required for protocol=doip)"
        )
        # Optional: cordra_client derives the DoIP host from url when omitted.
        doip_host = config.get("doip_host")
        if doip_host and str(doip_host).strip():
            kwargs["doip_host"] = str(doip_host).strip()

    return kwargs


# --------------------------------------------------
# UPLOAD
# --------------------------------------------------


@dataclass
class BatchResult:
    stats: Dict[str, int]
    cacheable_objects: List[dict]
    response: Dict[str, Any]


def normalize_input_object(dobj: dict) -> Tuple[Optional[str], str, dict]:
    """Validate and extract optional id, type, and content from a Cordra/DO wrapper."""
    if not isinstance(dobj, dict):
        raise ValueError("Input item is not an object")

    raw_id = dobj.get("id")
    obj_type = dobj.get("type")
    content = content_of(dobj)

    obj_id: Optional[str] = None
    if isinstance(raw_id, str) and raw_id.strip():
        obj_id = raw_id.strip()

    if not isinstance(obj_type, str) or not obj_type.strip():
        raise ValueError("Missing/invalid 'type'")
    if not content:
        raise ValueError(f"Missing/invalid 'content' for type={obj_type.strip()}")

    obj_type = obj_type.strip()
    content = dict(content)
    if obj_id is not None:
        content["id"] = obj_id
    return obj_id, obj_type, content


def _prepare_batch_item(item: dict, *, include_user_metadata: bool = False) -> dict:
    """Validate item and return it for ``Cordra.batch_upload`` (client normalizes shape)."""
    oid, otype, content = normalize_input_object(item)

    # Prefer Digital Object shape for new/rewritten callers; preserve legacy
    # wrappers and element/payload attachments so the client can map them.
    if isinstance(item.get("attributes"), dict) and isinstance(
        item["attributes"].get("content"), dict
    ):
        prepared = dict(item)
        prepared["type"] = otype
        if oid is not None:
            prepared["id"] = oid
        attrs = dict(prepared.get("attributes") or {})
        attrs["content"] = content
        if include_user_metadata:
            um = user_metadata_of(item)
            if um:
                attrs["userMetadata"] = um
        acl = acl_of(item)
        if acl:
            attrs["acl"] = acl
        prepared["attributes"] = attrs
        return prepared

    prepared: dict[str, Any] = {"type": otype, "content": content}
    if oid is not None:
        prepared["id"] = oid
    if include_user_metadata:
        um = user_metadata_of(item)
        if um:
            prepared["userMetadata"] = um
    acl = acl_of(item)
    if acl:
        prepared["acl"] = acl
    elements = elements_of(item)
    if elements:
        # Keep legacy key if that is what the caller used; else use elements.
        if isinstance(item.get("payloads"), list):
            prepared["payloads"] = elements
        else:
            prepared["elements"] = elements
    return prepared


def batch_upload_detailed(
    cordra,
    objects,
    *,
    include_user_metadata=False,
    reporter: Optional[Reporter] = None,
) -> BatchResult:
    rep = reporter_or_null(reporter)
    stats = {"upserted": 0, "conflicts": 0, "failed": 0, "skipped_invalid": 0}
    payload = []
    source_objects = []

    for item in objects:
        try:
            payload.append(
                _prepare_batch_item(item, include_user_metadata=include_user_metadata)
            )
            source_objects.append(item)
        except Exception as exc:
            stats["skipped_invalid"] += 1
            rep.emit(
                "warning",
                f"Skipping invalid object before upload: {exc}",
                category="batch_invalid",
            )

    if not payload:
        return BatchResult(stats=stats, cacheable_objects=[], response={"results": []})

    try:
        response = cordra.batch_upload(payload)
    except CordraError as exc:
        emit_critical(rep, f"Batch upload failed: {exc}", category="cordra_connect")
    except Exception as exc:
        rep.emit("error", f"Batch upload failed: {exc}", category="batch_error")
        stats["failed"] = len(payload)
        return BatchResult(stats=stats, cacheable_objects=[], response={"results": []})

    results = response.get("results", []) if isinstance(response, dict) else []
    if not isinstance(results, list):
        rep.emit(
            "error",
            "batchUpload returned unexpected payload",
            category="batch_error",
        )
        stats["failed"] = len(payload)
        return BatchResult(
            stats=stats,
            cacheable_objects=[],
            response=response if isinstance(response, dict) else {},
        )
    if not results and isinstance(response, dict) and response.get("success") is True:
        stats["upserted"] = len(source_objects)
        return BatchResult(
            stats=stats,
            cacheable_objects=list(source_objects),
            response=response,
        )

    cacheable_objects = []
    for res in results:
        code = res.get("responseCode")
        pos = res.get("position")

        if pos is None or not isinstance(pos, int) or pos < 0 or pos >= len(source_objects):
            stats["failed"] += 1
            rep.emit(
                "error",
                "Batch Error [position unknown]: malformed response item",
                category="batch_error",
            )
            continue

        source_obj = source_objects[pos]
        if code == 200:
            stats["upserted"] += 1
            cacheable_objects.append(source_obj)
        elif code == 409:
            stats["conflicts"] += 1
            cacheable_objects.append(source_obj)
        else:
            stats["failed"] += 1
            message = "Unknown error"
            nested = res.get("response")
            if isinstance(nested, dict):
                message = nested.get("message") or content_of(nested).get(
                    "message", message
                )
            rep.emit(
                "error",
                f"Batch Error [ID {source_obj.get('id', 'UNKNOWN')}]: {message}",
                category="batch_error",
                record_id=str(source_obj.get("id", "UNKNOWN")),
            )

    return BatchResult(stats=stats, cacheable_objects=cacheable_objects, response=response)


def batch_upload_stats(cordra, objects, *, include_user_metadata=False, reporter=None) -> dict:
    return batch_upload_detailed(
        cordra,
        objects,
        include_user_metadata=include_user_metadata,
        reporter=reporter,
    ).stats

