#!/usr/bin/env python3

"""
Protocol-aware Cordra client.

Supports two transports only:

- ``rest``: the legacy Cordra HTTP API (``/objects``, ``/search``, ``/cordra/call``, …)
- ``doip``: native DoIP over TLS (``cnri_doip_client``)

DoIP-over-HTTP (``/cordra/doip/0.DOIP/Op.*``) is not supported.

The legacy REST-only client lives in scripts/legacy/libcordra.py. This module
exposes one Cordra class whose public methods are stable across REST and native
DoIP where Cordra supports equivalent operations.
"""

import json
import random
import shutil
import string
import threading
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote, urlparse

import requests


try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    urllib3 = None


STATUS_OK = "0.DOIP/Status.001"
STATUS_NOT_FOUND = "0.DOIP/Status.104"
STATUS_CONFLICT = "0.DOIP/Status.105"
OP_HELLO = "0.DOIP/Op.Hello"
OP_LIST_OPERATIONS = "0.DOIP/Op.ListOperations"
OP_BATCH_UPLOAD = "20.DOIP/Op.BatchUpload"
OP_VERSIONS_GET = "20.DOIP/Op.Versions.Get"
OP_VERSIONS_PUBLISH = "20.DOIP/Op.Versions.Publish"

KEEPALIVE_INTERVAL = 60


class _TokenKeepalive:
    """Background thread that periodically pings Cordra to renew the access token."""

    def __init__(self, ping_fn, *, interval=KEEPALIVE_INTERVAL, on_failure=None):
        self._ping_fn = ping_fn
        self._interval = interval
        self._on_failure = on_failure
        self._stop_event = threading.Event()
        self._thread = None

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="cordra-keepalive",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self._interval + 5)
            self._thread = None

    def _run(self):
        while not self._stop_event.wait(self._interval):
            try:
                self._ping_fn()
            except Exception as exc:
                if self._on_failure is not None:
                    self._on_failure(exc)


class CordraError(RuntimeError):
    """Base class for Cordra transport/API errors."""


class CordraConfigError(CordraError):
    """Raised when required Cordra configuration is missing or invalid."""


class CordraUnsupportedError(CordraError):
    """Raised when an operation is not implemented for the selected protocol."""


class CordraNotFound(CordraError):
    """Raised when a Cordra object does not exist."""


class CordraConflict(CordraError):
    """Raised when Cordra reports a conflict."""


@dataclass
class BatchResult:
    stats: Dict[str, int]
    cacheable_objects: List[dict]
    response: Dict[str, Any]


def _merge_config(config: dict) -> dict:
    nested = config.get("cordra") if isinstance(config.get("cordra"), dict) else {}
    merged = dict(nested)
    merged.update({k: v for k, v in config.items() if k != "cordra"})
    return merged


def _first_config_value(config: dict, *keys: str) -> Any:
    for key in keys:
        value = config.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return None


def _config_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "y")


def _require(value: Any, name: str) -> Any:
    if value is None or str(value).strip() == "":
        raise CordraConfigError(f"Missing Cordra config key: {name}")
    return value


def _api_host(api_url: str) -> str:
    parsed = urlparse(api_url)
    if parsed.hostname:
        return parsed.hostname
    raise CordraConfigError(f"Cannot derive DoIP host from cordra_api_url: {api_url!r}")


def normalize_input_object(dobj: dict) -> Tuple[str, str, dict]:
    """Validate and extract id/type/content from a Cordra object wrapper."""
    if not isinstance(dobj, dict):
        raise ValueError("Input item is not an object")

    obj_id = dobj.get("id")
    obj_type = dobj.get("type")
    content = dobj.get("content")

    if not isinstance(obj_id, str) or not obj_id.strip():
        raise ValueError("Missing/invalid 'id'")
    if not isinstance(obj_type, str) or not obj_type.strip():
        raise ValueError(f"Missing/invalid 'type' for id={obj_id}")
    if not isinstance(content, dict):
        raise ValueError(f"Missing/invalid 'content' for id={obj_id}")

    obj_id = obj_id.strip()
    obj_type = obj_type.strip()
    content = dict(content)
    content["id"] = obj_id
    return obj_id, obj_type, content


def _rest_params(
    *,
    full: bool = False,
    json_pointer: Optional[str] = None,
    filter: Optional[Any] = None,
    payload: Optional[str] = None,
) -> str:
    params = []
    if full:
        params.append("full")
    if json_pointer:
        params.append(f"jsonPointer={quote(str(json_pointer), safe='/')}")
    if filter:
        params.append(f"filter={quote(json.dumps(filter) if isinstance(filter, list) else str(filter), safe='[]/,')}")
    if payload:
        params.append(f"payload={quote(str(payload), safe='')}")
    return ("?" + "&".join(params)) if params else ""


def _status_message(prefix: str, response: requests.Response) -> str:
    return f"{prefix}: HTTP {response.status_code}: {response.text}"


def _content_from_object(obj: dict) -> dict:
    if not isinstance(obj, dict):
        return {}
    if isinstance(obj.get("content"), dict):
        return obj["content"]
    attrs = obj.get("attributes") if isinstance(obj.get("attributes"), dict) else {}
    content = attrs.get("content")
    return content if isinstance(content, dict) else {}


def _normalize_operations_list(body: Any) -> List[str]:
    """Extract operation identifiers from a ListOperations response."""
    if isinstance(body, list):
        return [str(item) for item in body]
    if isinstance(body, dict):
        output = body.get("output")
        if isinstance(output, list):
            return [str(item) for item in output]
    raise CordraError(f"Unexpected ListOperations response: {body!r}")


def _to_rest_object(obj: Any) -> Any:
    """Expose DoIP objects in the same broad shape as REST objects."""
    if not isinstance(obj, dict):
        return obj
    attrs = obj.get("attributes") if isinstance(obj.get("attributes"), dict) else {}
    out = dict(obj)
    if "content" not in out and isinstance(attrs.get("content"), dict):
        out["content"] = attrs["content"]
    if "userMetadata" not in out and isinstance(attrs.get("userMetadata"), dict):
        out["userMetadata"] = attrs["userMetadata"]
    return out


def _to_rest_object_from_do(dobj: Any) -> Any:
    """Convert a DoIP DigitalObject (or dict) into REST-shaped dict."""
    if dobj is None:
        return None
    if isinstance(dobj, str):
        return dobj
    if hasattr(dobj, "to_dict"):
        return _to_rest_object(dobj.to_dict())
    return _to_rest_object(dobj)


def _unwrap_doip_output(body: Any) -> Any:
    """Unwrap perform_operation JSON for Cordra extended ops (versions, batch, etc.)."""
    if body is None:
        return None
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        if "output" in body:
            return body["output"]
        if "results" in body:
            return body["results"]
    return body


def _version_ids_from_list(items: Any, current_pid: str) -> List[str]:
    """Extract published version ids, excluding the current/tip object id."""
    if not isinstance(items, list):
        return []
    return [
        str(item["id"])
        for item in items
        if isinstance(item, dict) and item.get("id") and item["id"] != current_pid
    ]


def _map_doip_status(
    status: str,
    context: str,
    body: Any = None,
    *,
    status_not_found: str = STATUS_NOT_FOUND,
    status_conflict: str = STATUS_CONFLICT,
) -> CordraError:
    msg = f"{context} failed with DOIP status {status}. Response body: {body}"
    if status == status_not_found:
        return CordraNotFound(msg)
    if status == status_conflict:
        return CordraConflict(msg)
    return CordraError(msg)


def _digital_object_attributes(
    content: dict,
    *,
    pid: Optional[str] = None,
    user_metadata: Optional[dict] = None,
) -> dict:
    content_copy = dict(content)
    if pid:
        content_copy["id"] = pid
    attrs: Dict[str, Any] = {"content": content_copy}
    if isinstance(user_metadata, dict):
        attrs["userMetadata"] = user_metadata
    return attrs


class _RestCordraTransport:
    protocol = "rest"

    def __init__(self, url: str, username: Optional[str], password: Optional[str], verify: bool = False):
        self.url = url.rstrip("/")
        self.username = username
        self.password = password
        self.verify = verify
        self.token = None
        self.headers: Dict[str, str] = {}
        self._keepalive = None
        if username and password:
            self.token = self.get_token()
            self.headers = {"Authorization": f"Bearer {self.token}"}
            self._start_keepalive()

    def _start_keepalive(self):
        self._keepalive = _TokenKeepalive(
            self._keepalive_ping,
            on_failure=self._on_keepalive_failure,
        )
        self._keepalive.start()

    def _keepalive_ping(self):
        self.check_credentials()

    def _on_keepalive_failure(self, exc):
        print(f"WARNING: Cordra token keepalive failed: {exc}", flush=True)
        try:
            self.token = self.get_token()
            self.headers = {"Authorization": f"Bearer {self.token}"}
        except Exception as reauth_exc:
            print(
                f"WARNING: Cordra token keepalive re-authentication failed: {reauth_exc}",
                flush=True,
            )

    def _request(self, method: str, path: str, **kwargs):
        response = requests.request(
            method,
            f"{self.url}{path}",
            headers=kwargs.pop("headers", self.headers),
            verify=kwargs.pop("verify", self.verify),
            **kwargs,
        )
        return self._handle_response(response, f"{method} {path}")

    def _handle_response(self, response: requests.Response, context: str, *, allow_empty: bool = False):
        if response.status_code == 404:
            raise CordraNotFound(_status_message(context, response))
        if response.status_code == 409:
            raise CordraConflict(_status_message(context, response))
        if response.status_code < 200 or response.status_code >= 300:
            raise CordraError(_status_message(context, response))
        if allow_empty or not response.content:
            return True
        try:
            return response.json()
        except Exception as exc:
            raise CordraError(f"{context}: response is not JSON: {exc}") from exc

    def get_token(self):
        response = requests.post(
            f"{self.url}/auth/token",
            json={"username": self.username, "password": self.password},
            verify=self.verify,
        )
        data = self._handle_response(response, "POST /auth/token")
        return data["access_token"]

    def get_by_handle(self, pid, full=False, json_pointer=None, filter=None, payload=None):
        parameter_string = _rest_params(full=full, json_pointer=json_pointer, filter=filter, payload=payload)
        response = requests.get(
            f"{self.url}/objects/{pid}{parameter_string}",
            headers=self.headers,
            verify=self.verify,
        )
        if payload:
            if response.status_code == 404:
                raise CordraNotFound(_status_message(f"GET /objects/{pid}", response))
            if response.status_code < 200 or response.status_code >= 300:
                raise CordraError(_status_message(f"GET /objects/{pid}", response))
            return response.content
        return self._handle_response(response, f"GET /objects/{pid}")

    def query(
        self,
        query,
        page_num=0,
        page_size=-1,
        filter=None,
        full=False,
        ids=False,
        include_versions=False,
        sort_fields=None,
    ):
        post_data = {"query": query, "pageNum": page_num, "pageSize": page_size}
        if filter and isinstance(filter, list):
            post_data["filter"] = filter
        if include_versions:
            post_data["includeVersions"] = True
        if sort_fields:
            post_data["sortFields"] = sort_fields
        if full:
            post_data["full"] = True
        elif ids:
            post_data["ids"] = True
        response = requests.post(f"{self.url}/search", json=post_data, headers=self.headers, verify=self.verify)
        data = self._handle_response(response, "POST /search")
        return data.get("results", [])

    def query_count(self, query, include_versions=False):
        post_data = {"query": query, "pageNum": 0, "pageSize": 1, "filter": ["/id"]}
        if include_versions:
            post_data["includeVersions"] = True
        response = requests.post(f"{self.url}/search", json=post_data, headers=self.headers, verify=self.verify)
        data = self._handle_response(response, "POST /search")
        return data.get("size", 0)

    def create(self, obj, type, pid=None, full=False):
        pid_param = f"&handle={quote(pid, safe='/')}" if pid else ""
        full_param = "&full" if full else ""
        response = requests.post(
            f"{self.url}/objects/?type={quote(type, safe='')}{pid_param}{full_param}",
            json=obj,
            headers=self.headers,
            verify=self.verify,
        )
        return self._handle_response(response, "POST /objects")

    def update(self, pid, obj, full=False):
        full_param = "?full" if full else ""
        response = requests.put(
            f"{self.url}/objects/{pid}{full_param}",
            json=obj,
            headers=self.headers,
            verify=self.verify,
        )
        return self._handle_response(response, f"PUT /objects/{pid}")

    def delete(self, pid):
        response = requests.delete(f"{self.url}/objects/{pid}", headers=self.headers, verify=self.verify)
        return self._handle_response(response, f"DELETE /objects/{pid}", allow_empty=True)

    def batch_upload(self, objects):
        response = requests.post(f"{self.url}/batchUpload", json=objects, headers=self.headers, verify=self.verify)
        return self._handle_response(response, "POST /batchUpload")

    def download_payload(self, pid, payload, path):
        with requests.get(
            f"{self.url}/objects/{pid}?payload={quote(payload, safe='')}",
            stream=True,
            headers=self.headers,
            verify=self.verify,
        ) as response:
            if response.status_code == 404:
                raise CordraNotFound(_status_message(f"GET /objects/{pid}?payload={payload}", response))
            if response.status_code < 200 or response.status_code >= 300:
                raise CordraError(_status_message(f"GET /objects/{pid}?payload={payload}", response))
            with open(path, "wb") as f:
                shutil.copyfileobj(response.raw, f)

    def create_object_with_payloads(self, do, type, payloads, full=False):
        full_param = "&full" if full else ""
        files = {"content": (None, json.dumps(do))}
        files.update(payloads)
        response = requests.post(
            f"{self.url}/objects/?type={quote(type, safe='')}{full_param}",
            headers=self.headers,
            files=files,
            verify=self.verify,
        )
        return self._handle_response(response, "POST /objects multipart")

    def update_object_with_payloads(self, pid, payloads, do=None, full=False):
        full_param = "?full" if full else ""
        if do is None:
            do = self.get_by_handle(pid, full=True).get("content", {})
        files = {"content": (None, json.dumps(do))}
        files.update(payloads)
        response = requests.put(
            f"{self.url}/objects/{pid}{full_param}",
            headers=self.headers,
            files=files,
            verify=self.verify,
        )
        return self._handle_response(response, f"PUT /objects/{pid} multipart")

    def get_versions(self, pid):
        response = requests.get(f"{self.url}/versions/?objectId={pid}", headers=self.headers, verify=self.verify)
        version_list = self._handle_response(response, "GET /versions")
        return [item["id"] for item in version_list if item.get("id") != pid]

    def create_version(self, pid, version_pid=None):
        version_param = f"&versionId={quote(version_pid, safe='/')}" if version_pid else ""
        response = requests.post(
            f"{self.url}/versions/?objectId={pid}{version_param}",
            headers=self.headers,
            verify=self.verify,
        )
        return self._handle_response(response, "POST /versions")

    def update_design(self, design, payload=None):
        url = f"{self.url}/objects/design"
        if payload is not None:
            files = {
                "content": (None, design),
                "customAuthentication.html": ("customAuthentication.html", payload, "text/html"),
            }
            response = requests.put(url, headers=self.headers, files=files, verify=self.verify)
        else:
            response = requests.put(url, headers=self.headers, json=json.loads(design), verify=self.verify)
        self._handle_response(response, "PUT /objects/design")
        return True

    def reindex(self, objects=None, query=None, all=False, lock_objects=True, timeout=30):
        parameters = {}
        body = None
        if all:
            parameters["all"] = True
        elif query:
            parameters["query"] = query
        elif objects and isinstance(objects, list):
            body = objects
        else:
            return False
        if lock_objects:
            parameters["lockObjects"] = True
        qs = ""
        if parameters:
            qs = "?" + "&".join(f"{key}={value}" for key, value in parameters.items())
        try:
            response = requests.post(
                f"{self.url}/reindexBatch{qs}",
                json=body,
                headers=self.headers,
                verify=self.verify,
                timeout=timeout,
            )
            self._handle_response(response, "POST /reindexBatch", allow_empty=True)
        except requests.exceptions.Timeout:
            print("Timeout... (this is usually a good sign and means that the server is busy reindexing)", flush=True)
        return None

    def call_type_method(self, pid, method, input=None):
        response = requests.post(
            f"{self.url}/cordra/call?objectId={pid}&method={method}",
            headers=self.headers,
            json=input,
            verify=self.verify,
        )
        return self._handle_response(response, "POST /cordra/call")

    def check_credentials(self, full=False):
        params = "?full=true" if full else ""
        response = requests.get(
            f"{self.url}/check-credentials{params}",
            headers=self.headers,
            verify=self.verify,
        )
        return self._handle_response(response, "GET /check-credentials")

    def list_operations(self, target_id: str) -> List[str]:
        """List permitted type methods via GET /cordra/listMethods (legacy REST)."""
        pid = quote(str(target_id), safe="/")
        response = requests.get(
            f"{self.url}/cordra/listMethods/?objectId={pid}",
            headers=self.headers,
            verify=self.verify,
        )
        body = self._handle_response(response, f"GET /cordra/listMethods objectId={target_id}")
        return _normalize_operations_list(body)

    def close(self):
        if self._keepalive is not None:
            self._keepalive.stop()
            self._keepalive = None


class _DoipCordraTransport:
    protocol = "doip"

    def __init__(
        self,
        host: str,
        port: int,
        username: Optional[str],
        password: Optional[str],
        service_id: str,
    ):
        import cnri_doip_client as doip_client

        self.doip_client = doip_client
        self.service_id = service_id
        self.status_ok = getattr(doip_client.DoipConstants, "STATUS_OK", STATUS_OK)
        self.status_not_found = getattr(doip_client.DoipConstants, "STATUS_NOT_FOUND", STATUS_NOT_FOUND)
        self.status_conflict = getattr(doip_client.DoipConstants, "STATUS_CONFLICT", STATUS_CONFLICT)

        service_info = doip_client.ServiceInfo(
            ip_address=str(host),
            port=int(port),
            service_id=str(service_id),
        )
        client_kwargs: Dict[str, Any] = {"service_info": service_info}
        if username and password:
            client_kwargs["authentication"] = doip_client.PasswordAuthenticationInfo(
                str(username),
                str(password),
            )
        self.client = doip_client.StandardDoipClient(**client_kwargs)
        self._client_lock = threading.RLock()
        self._keepalive = None
        if username and password:
            self._start_keepalive()

    def _start_keepalive(self):
        self._keepalive = _TokenKeepalive(
            self._keepalive_ping,
            on_failure=self._on_keepalive_failure,
        )
        self._keepalive.start()

    def _keepalive_ping(self):
        with self._client_lock:
            self.hello()

    def _on_keepalive_failure(self, exc):
        print(f"WARNING: Cordra token keepalive failed: {exc}", flush=True)

    def _error_from_status(self, status: str, context: str, body: Any = None):
        return _map_doip_status(
            status,
            context,
            body,
            status_not_found=self.status_not_found,
            status_conflict=self.status_conflict,
        )

    def _read_response(self, resp, context: str, *, allow_not_found: bool = False):
        status = resp.get_status()
        body = None
        try:
            body = resp.as_json()
        except Exception:
            body = None
        if status == self.status_ok:
            return body
        if allow_not_found and status == self.status_not_found:
            return None
        raise self._error_from_status(status, context, body)

    def _search_params(self, page_num: int, page_size: int) -> Any:
        return self.doip_client.QueryParams(page_num=page_num, page_size=page_size)

    def _query_via_perform_operation(
        self,
        query: str,
        page_num: int,
        page_size: int,
        filter: Any,
        ids: bool,
        include_versions: bool,
        sort_fields: Any = None,
    ) -> List[Any]:
        op_search = self.doip_client.DoipConstants.OP_SEARCH
        attrs: Dict[str, Any] = {
            "query": query,
            "pageNum": page_num,
            "pageSize": page_size,
            "type": "ids" if ids else "full",
        }
        if filter:
            attrs["filter"] = filter
        if include_versions:
            attrs["includeVersions"] = True
        if sort_fields:
            attrs["sortFields"] = sort_fields
        with self.client.perform_operation(self.service_id, op_search, attributes=attrs) as resp:
            body = self._read_response(resp, f"Search query={query!r}")
        results = body.get("results", []) if isinstance(body, dict) else []
        if ids:
            return results
        return [_to_rest_object(item) for item in results]

    def get_by_handle(self, pid, full=False, json_pointer=None, filter=None, payload=None):
        if json_pointer or filter or payload:
            raise CordraUnsupportedError("DoIP get_by_handle does not support json_pointer/filter/payload in libcordra2")
        try:
            dobj = self.client.retrieve(pid)
            if dobj is None:
                raise CordraNotFound(f"Retrieve target={pid} failed: not found")
            return _to_rest_object_from_do(dobj)
        except CordraError:
            raise
        except Exception as exc:
            self._raise_doip_exception(exc, f"Retrieve target={pid}")

    def query(
        self,
        query,
        page_num=0,
        page_size=-1,
        filter=None,
        full=False,
        ids=False,
        include_versions=False,
        sort_fields=None,
    ):
        if filter or include_versions or sort_fields:
            try:
                return self._query_via_perform_operation(
                    query,
                    page_num,
                    page_size,
                    filter,
                    ids,
                    include_versions,
                    sort_fields,
                )
            except Exception as exc:
                self._raise_doip_exception(exc, f"Search query={query!r}")
        params = self._search_params(page_num, page_size)
        try:
            if ids:
                with self.client.search_ids(query, params=params) as results:
                    return list(results)
            with self.client.search(query, params=params) as results:
                return [_to_rest_object_from_do(item) for item in results]
        except Exception as exc:
            self._raise_doip_exception(exc, f"Search query={query!r}")

    def query_count(self, query, include_versions=False):
        if include_versions:
            try:
                attrs = {
                    "query": query,
                    "pageNum": 0,
                    "pageSize": 1,
                    "type": "ids",
                    "includeVersions": True,
                }
                op_search = self.doip_client.DoipConstants.OP_SEARCH
                with self.client.perform_operation(self.service_id, op_search, attributes=attrs) as resp:
                    body = self._read_response(resp, f"Search count query={query!r}")
                return int(body.get("size", 0)) if isinstance(body, dict) else 0
            except Exception as exc:
                self._raise_doip_exception(exc, f"Search count query={query!r}")
        params = self._search_params(0, 1)
        try:
            with self.client.search_ids(query, params=params) as results:
                return int(results.size)
        except Exception as exc:
            self._raise_doip_exception(exc, f"Search count query={query!r}")

    def create(self, obj, type, pid=None, full=False):
        content = _content_from_object(obj) or (obj if isinstance(obj, dict) else {})
        user_metadata = obj.get("userMetadata") if isinstance(obj, dict) else None
        attributes = _digital_object_attributes(
            content,
            pid=pid,
            user_metadata=user_metadata if isinstance(user_metadata, dict) else None,
        )
        dobj = self.doip_client.DigitalObject(id=pid, type=type, attributes=attributes)
        try:
            created = self.client.create(dobj)
            return _to_rest_object_from_do(created)
        except Exception as exc:
            self._raise_doip_exception(exc, f"Create type={type}")

    def update(self, pid, obj, full=False):
        obj_type = obj.get("type") if isinstance(obj, dict) else None
        content = _content_from_object(obj) or (obj if isinstance(obj, dict) else {})
        if not obj_type:
            try:
                existing = self.get_by_handle(pid)
                obj_type = existing.get("type")
            except CordraNotFound:
                raise
        if not obj_type:
            raise CordraError(f"Cannot update {pid}: object type is missing")
        user_metadata = obj.get("userMetadata") if isinstance(obj, dict) else None
        attributes = _digital_object_attributes(
            content,
            pid=pid,
            user_metadata=user_metadata if isinstance(user_metadata, dict) else None,
        )
        dobj = self.doip_client.DigitalObject(id=pid, type=obj_type, attributes=attributes)
        try:
            updated = self.client.update(dobj)
            return _to_rest_object_from_do(updated)
        except Exception as exc:
            self._raise_doip_exception(exc, f"Update target={pid}")

    def delete(self, pid):
        try:
            self.client.delete(pid)
            return True
        except Exception as exc:
            self._raise_doip_exception(exc, f"Delete target={pid}")

    def batch_upload(self, objects):
        try:
            with self.client.perform_operation(self.service_id, OP_BATCH_UPLOAD, objects) as resp:
                return self._read_response(resp, "BatchUpload")
        except Exception as exc:
            self._raise_doip_exception(exc, "BatchUpload")

    def get_versions(self, pid):
        try:
            with self.client.perform_operation(pid, OP_VERSIONS_GET) as resp:
                body = self._read_response(resp, f"Versions.Get target={pid}")
            items = _unwrap_doip_output(body)
            return _version_ids_from_list(items, pid)
        except Exception as exc:
            self._raise_doip_exception(exc, f"Versions.Get target={pid}")

    def create_version(self, pid, version_pid=None):
        attrs = {"versionId": version_pid} if version_pid else None
        try:
            with self.client.perform_operation(pid, OP_VERSIONS_PUBLISH, attributes=attrs) as resp:
                return self._read_response(resp, f"Versions.Publish target={pid}")
        except Exception as exc:
            self._raise_doip_exception(exc, f"Versions.Publish target={pid}")

    def hello(self):
        try:
            dobj = self.client.hello()
            return _to_rest_object_from_do(dobj)
        except Exception as exc:
            self._raise_doip_exception(exc, "Hello")

    def list_operations(self, target_id: str) -> List[str]:
        """List permitted operations via native DoIP 0.DOIP/Op.ListOperations."""
        try:
            return self.client.list_operations(target_id)
        except Exception as exc:
            self._raise_doip_exception(exc, f"ListOperations target={target_id}")

    def _raise_doip_exception(self, exc: Exception, context: str):
        if isinstance(exc, CordraError):
            raise exc
        doip_exception = getattr(self.doip_client, "DoipException", None)
        if doip_exception is not None and isinstance(exc, doip_exception):
            raise self._error_from_status(exc.status, context, exc.response) from exc
        status = getattr(exc, "status", None)
        response = getattr(exc, "response", None)
        if status:
            raise self._error_from_status(status, context, response) from exc
        msg = str(exc)
        if self.status_not_found in msg:
            raise CordraNotFound(f"{context} failed: {msg}") from exc
        raise CordraError(f"{context} failed: {msg}") from exc

    def close(self):
        if self._keepalive is not None:
            self._keepalive.stop()
            self._keepalive = None
        close = getattr(self.client, "close", None)
        if callable(close):
            close()

    def __getattr__(self, name: str):
        raise CordraUnsupportedError(f"Operation {name} is not supported for protocol doip")


class Cordra:
    """Cordra client facade with REST and native DoIP transports."""

    def __init__(
        self,
        url=None,
        username=None,
        password=None,
        verify=False,
        *,
        protocol="rest",
        doip_host=None,
        doip_port=None,
        service_id=None,
        error_mode="strict",
    ):
        self.protocol = (protocol or "rest").strip().lower()
        self.error_mode = error_mode
        self.service_id = service_id
        if self.protocol == "rest":
            self._transport = _RestCordraTransport(
                _require(url, "cordra_api_url"),
                username,
                password,
                verify=verify,
            )
        elif self.protocol == "doip":
            host = doip_host or _api_host(_require(url, "cordra_api_url"))
            self._transport = _DoipCordraTransport(
                host=host,
                port=int(_require(doip_port, "cordra_doip_port")),
                username=username,
                password=password,
                service_id=service_id or resolve_service_id({}),
            )
        else:
            raise CordraConfigError(f"Unknown Cordra protocol: {protocol!r}")

    @classmethod
    def from_config(cls, config: dict, protocol="doip", error_mode="strict"):
        c = _merge_config(config)
        rest_url = _first_config_value(c, "cordra_api_url", "url", "rest_url", "cordra_url")
        username = _first_config_value(c, "cordra_username", "username", "doip_username")
        password = _first_config_value(c, "cordra_password", "password", "doip_password")
        verify = _config_bool(_first_config_value(c, "verify", "cordra_verify"), default=False)
        doip_host = _first_config_value(c, "cordra_doip_host", "doip_ip")
        if doip_host is None and rest_url:
            doip_host = _api_host(rest_url)
        doip_port = _first_config_value(c, "cordra_doip_port", "doip_port")
        service_id = resolve_service_id(c)

        return cls(
            url=rest_url,
            username=username,
            password=password,
            verify=verify,
            protocol=protocol,
            doip_host=doip_host,
            doip_port=doip_port,
            service_id=service_id,
            error_mode=error_mode,
        )

    def get_by_handle(self, *args, **kwargs):
        return self._transport.get_by_handle(*args, **kwargs)

    retrieve = get_by_handle

    def exists(self, pid: str) -> bool:
        try:
            self.get_by_handle(pid)
            return True
        except CordraNotFound:
            return False

    def query(self, *args, **kwargs):
        return self._transport.query(*args, **kwargs)

    search = query

    def query_count(self, *args, **kwargs):
        return self._transport.query_count(*args, **kwargs)

    def create(self, *args, **kwargs):
        return self._transport.create(*args, **kwargs)

    def update(self, *args, **kwargs):
        return self._transport.update(*args, **kwargs)

    def delete(self, *args, **kwargs):
        return self._transport.delete(*args, **kwargs)

    def batch_upload(self, objects, *, normalize=False, include_user_metadata=False, return_cacheable=False):
        if normalize or return_cacheable:
            result = self.batch_upload_detailed(objects, include_user_metadata=include_user_metadata)
            return (result.stats, result.cacheable_objects) if return_cacheable else result.response

        if self.protocol == "rest":
            return self._transport.batch_upload(objects)

        for item in objects:
            if isinstance(item, dict) and item.get("payloads"):
                raise CordraUnsupportedError("DoIP batch_upload with payloads is not supported in libcordra2")
        payload = [self._object_to_doip_payload(item, include_user_metadata=True) for item in objects]
        return self._transport.batch_upload(payload)

    def batch_upload_detailed(self, objects, *, include_user_metadata=False) -> BatchResult:
        stats = {"upserted": 0, "conflicts": 0, "failed": 0, "skipped_invalid": 0}
        payload = []
        source_objects = []

        for item in objects:
            try:
                if self.protocol == "rest":
                    payload.append(self._object_to_rest_payload(item, include_user_metadata=include_user_metadata))
                else:
                    payload.append(self._object_to_doip_payload(item, include_user_metadata=include_user_metadata))
                source_objects.append(item)
            except Exception as exc:
                stats["skipped_invalid"] += 1
                print(f"    - WARNING: Skipping invalid object before upload: {exc}", flush=True)

        if not payload:
            return BatchResult(stats=stats, cacheable_objects=[], response={"results": []})

        try:
            response = self._transport.batch_upload(payload)
        except Exception as exc:
            print(f"    - ERROR: CRITICAL BATCH ERROR: {exc}", flush=True)
            stats["failed"] = len(payload)
            return BatchResult(stats=stats, cacheable_objects=[], response={"results": []})

        results = response.get("results", []) if isinstance(response, dict) else []
        if not isinstance(results, list):
            print("    - ERROR: CRITICAL BATCH ERROR: batchUpload returned unexpected payload", flush=True)
            stats["failed"] = len(payload)
            return BatchResult(stats=stats, cacheable_objects=[], response=response if isinstance(response, dict) else {})

        cacheable_objects = []
        for res in results:
            code = res.get("responseCode")
            pos = res.get("position")

            if pos is None or not isinstance(pos, int) or pos < 0 or pos >= len(source_objects):
                stats["failed"] += 1
                print("    - ERROR: Batch Error [position unknown]: malformed response item", flush=True)
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
                if isinstance(res.get("response"), dict):
                    message = res["response"].get("message", message)
                print(f"    - ERROR: Batch Error [ID {source_obj.get('id', 'UNKNOWN')}]: {message}", flush=True)

        return BatchResult(stats=stats, cacheable_objects=cacheable_objects, response=response)

    def _object_to_rest_payload(self, item: dict, *, include_user_metadata=False) -> dict:
        oid, otype, content = normalize_input_object(item)
        payload = {"id": oid, "type": otype, "content": content}
        user_metadata = item.get("userMetadata") if isinstance(item.get("userMetadata"), dict) else None
        if include_user_metadata and user_metadata:
            payload["userMetadata"] = user_metadata
        acl = item.get("acl") if isinstance(item.get("acl"), dict) else None
        if acl:
            payload["acl"] = acl
        return payload

    def _object_to_doip_payload(self, item: dict, *, include_user_metadata=False) -> dict:
        oid, otype, content = normalize_input_object(item)
        attributes = {"content": content}
        user_metadata = item.get("userMetadata") if isinstance(item.get("userMetadata"), dict) else None
        if include_user_metadata and user_metadata:
            attributes["userMetadata"] = user_metadata
        acl = item.get("acl") if isinstance(item.get("acl"), dict) else None
        if acl:
            attributes["acl"] = acl
        return {"id": oid, "type": otype, "attributes": attributes}

    def download_payload(self, *args, **kwargs):
        return self._transport.download_payload(*args, **kwargs)

    def create_object_with_payloads(self, *args, **kwargs):
        return self._transport.create_object_with_payloads(*args, **kwargs)

    def update_object_with_payloads(self, *args, **kwargs):
        return self._transport.update_object_with_payloads(*args, **kwargs)

    def get_versions(self, *args, **kwargs):
        return self._transport.get_versions(*args, **kwargs)

    def create_version(self, *args, **kwargs):
        return self._transport.create_version(*args, **kwargs)

    def update_design(self, *args, **kwargs):
        return self._transport.update_design(*args, **kwargs)

    def reindex(self, *args, **kwargs):
        return self._transport.reindex(*args, **kwargs)

    def call_type_method(self, *args, **kwargs):
        return self._transport.call_type_method(*args, **kwargs)

    def check_credentials(self, full=False):
        if self.protocol != "rest":
            raise CordraUnsupportedError("check_credentials is only available for protocol rest")
        return self._transport.check_credentials(full=full)

    def hello(self):
        if self.protocol != "doip":
            raise CordraUnsupportedError("hello is only available for protocol doip")
        return self._transport.hello()

    def list_operations(self, target_id: str) -> List[str]:
        """List permitted operations/methods on a target (DoIP or legacy REST)."""
        return self._transport.list_operations(target_id)

    def close(self):
        return self._transport.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


def resolve_service_id(config: dict) -> str:
    sid = _first_config_value(config, "cordra_doip_service_id", "doip_service_id", "service_id")
    if isinstance(sid, str) and sid.strip():
        return sid.strip()
    prefix = str(config.get("hdl_prefix") or "").strip()
    return f"{prefix}/service" if prefix else "service"


def generate_hdl_suffix(
    format="alphanumeric",
    upper=False,
    length=8,
    in_groups_of=4,
    group_separator=".",
):
    if format == "hexadecimal":
        format_characters = string.hexdigits
    else:
        format_characters = string.ascii_lowercase + string.digits

    groups = []
    number_of_groups = length // in_groups_of
    for _ in range(0, number_of_groups):
        groups.append("".join(random.choices(format_characters, k=in_groups_of)))
    if length % in_groups_of > 0:
        groups.append("".join(random.choices(format_characters, k=length % in_groups_of)))

    suffix = group_separator.join(groups)
    return suffix.upper() if upper else suffix


if __name__ == "__main__":
    print("This is a module, not a script!")
