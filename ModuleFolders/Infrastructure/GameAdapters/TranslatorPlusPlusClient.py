"""Loopback-only transport client for the Translator++ HTTP bridge.

Only the local Translator++ 8.8.9 bridge can be reached: requests target a
literal ``127.0.0.1`` IPv4 address with an explicit port, never through DNS,
environment proxies, redirects or a translation service.

Callers cannot inject JavaScript. Every ``/api/exec`` body is one of the fixed,
trusted templates defined in this module; the only dynamic parts are JSON
literals built from validated Python values. Requests are attempted once and
are never retried.
"""

from __future__ import annotations

import http.client
import json
import math
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional, Union

__all__ = ["TranslatorPlusPlusClient", "TranslatorPlusPlusError"]

_SUPPORTED_VERSION = "8.8.9"
_DEFAULT_ENDPOINT = "http://127.0.0.1:22883"
_DEFAULT_TIMEOUT = 60
_LOOPBACK_HOST = "127.0.0.1"
_MIN_PORT = 1
_MAX_PORT = 65535
_MIN_TIMEOUT = 1
_MAX_TIMEOUT = 300
_MAX_REQUEST_BYTES = 16 * 1024 * 1024
_MAX_RESPONSE_BYTES = 32 * 1024 * 1024

_PATH_TOOLS = "/api/tools"
_PATH_EXEC = "/api/exec"
_ALLOWED_PATHS = (_PATH_TOOLS, _PATH_EXEC)

_REQUIRED_TOOLS = ("project.info", "cells.read", "cells.write")

_CONSOLE_BACKUP = "__tppConsoleBackup"

_MISSING = object()

_CONSOLE_GUARD_OPEN = (
    "const " + _CONSOLE_BACKUP + " = {log: console.log, warn: console.warn, "
    "info: console.info, debug: console.debug};\n"
    "console.log = console.warn = console.info = console.debug = function () {};\n"
    "try {\n"
)

_CONSOLE_GUARD_CLOSE = (
    "\n} finally {\n"
    "  console.log = " + _CONSOLE_BACKUP + ".log;\n"
    "  console.warn = " + _CONSOLE_BACKUP + ".warn;\n"
    "  console.info = " + _CONSOLE_BACKUP + ".info;\n"
    "  console.debug = " + _CONSOLE_BACKUP + ".debug;\n"
    "}\n"
)


class TranslatorPlusPlusError(ValueError):
    """Raised for invalid input, transport failures and bridge API errors."""


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    """Refuse every HTTP redirect; the local bridge must answer directly."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise TranslatorPlusPlusError("Translator++ API redirects are not allowed")


def _bounded_text(value: Any, limit: int = 64) -> str:
    text = value if isinstance(value, str) else repr(value)
    return text[:limit]


def _json_dumps(value: Any, message: str) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise TranslatorPlusPlusError(message) from exc


def _js_literal(value: Any) -> str:
    """Serialize ``value`` as a JSON literal that is also a valid JS literal."""

    literal = _json_dumps(value, "value is not JSON serializable")
    return literal.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def _encode_json(value: Any) -> bytes:
    body = _json_dumps(value, "request payload is not JSON serializable").encode("utf-8")
    if len(body) > _MAX_REQUEST_BYTES:
        raise TranslatorPlusPlusError("Translator++ API request exceeds the 16 MiB limit")
    return body


def _normalize_endpoint(endpoint: Any) -> str:
    if not isinstance(endpoint, str):
        raise TranslatorPlusPlusError("endpoint must be a string")
    if not endpoint or "\x00" in endpoint or any(char.isspace() for char in endpoint):
        raise TranslatorPlusPlusError("endpoint must be a literal loopback http URL")
    if "://" not in endpoint:
        raise TranslatorPlusPlusError("endpoint must include the http scheme")
    remainder = endpoint.split("://", 1)[1]
    if any(char in remainder for char in "/?#@"):
        raise TranslatorPlusPlusError(
            "endpoint must not contain a path, query, fragment or userinfo"
        )
    try:
        parsed = urllib.parse.urlsplit(endpoint)
        port = parsed.port
    except ValueError as exc:
        raise TranslatorPlusPlusError("endpoint is not a valid URL") from exc
    if parsed.scheme != "http":
        raise TranslatorPlusPlusError("endpoint must use the http scheme")
    if parsed.username is not None or parsed.password is not None:
        raise TranslatorPlusPlusError("endpoint must not contain userinfo")
    if parsed.hostname != _LOOPBACK_HOST:
        raise TranslatorPlusPlusError(
            "endpoint must use the literal IPv4 loopback address 127.0.0.1"
        )
    if port is None:
        raise TranslatorPlusPlusError("endpoint must include an explicit port")
    if not _MIN_PORT <= port <= _MAX_PORT:
        raise TranslatorPlusPlusError("endpoint port must be between 1 and 65535")
    if parsed.path or parsed.query or parsed.fragment:
        raise TranslatorPlusPlusError(
            "endpoint must not contain a path, query, fragment or userinfo"
        )
    return "http://" + _LOOPBACK_HOST + ":" + str(port)


def _normalize_timeout(timeout: Any) -> Union[int, float]:
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise TranslatorPlusPlusError("timeout must be a number between 1 and 300")
    if not math.isfinite(timeout) or not _MIN_TIMEOUT <= timeout <= _MAX_TIMEOUT:
        raise TranslatorPlusPlusError("timeout must be between 1 and 300 seconds")
    return int(timeout) if isinstance(timeout, int) else float(timeout)


def _require_nonempty_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TranslatorPlusPlusError(name + " must be a nonempty string")
    return value


def _require_nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TranslatorPlusPlusError(name + " must be a nonnegative integer")
    return value


def _require_file_id(file_id: Any) -> str:
    return _require_nonempty_str(file_id, "file_id")


def _require_absolute_path(value: Any, name: str) -> str:
    try:
        path = os.fspath(value)
    except TypeError as exc:
        raise TranslatorPlusPlusError(name + " must be a filesystem path") from exc
    if not isinstance(path, str) or not path:
        raise TranslatorPlusPlusError(name + " must be a nonempty path string")
    if "\x00" in path:
        raise TranslatorPlusPlusError(name + " must not contain NUL characters")
    if not os.path.isabs(path):
        raise TranslatorPlusPlusError(name + " must be an absolute path")
    return path


def _raise_for_api_error(response: dict) -> None:
    error = response.get("error")
    if error is None:
        return
    # The upstream error value may echo the script, project data or cell text.
    # Fail with a fixed, bounded, non-sensitive message.
    raise TranslatorPlusPlusError("Translator++ API reported an error")


def _wrap_script(body: str) -> str:
    """Wrap a fixed script body in console suppression with try/finally.

    The upstream API captures console output arrays, so log/warn/info/debug are
    silenced for the duration of the script and always restored. Errors are
    never swallowed: they surface through the returned ``error`` field.
    """

    return _CONSOLE_GUARD_OPEN + body + _CONSOLE_GUARD_CLOSE


_PROBE_BODY = (
    "return {\n"
    "  version: nw.App.manifest.version,\n"
    "  install_root: process.cwd(),\n"
    "  rpg_parser: typeof addonLoader.addons.rmmv.RMMVGames === 'function',\n"
    "  open_data: typeof trans.openFromTransObj === 'function',\n"
    "  snapshot: typeof trans.getSaveData === 'function'\n"
    "};\n"
)

_PROBE_SCRIPT = _wrap_script(_PROBE_BODY)


def _open_data_script(payload_literal: str) -> str:
    body = (
        "const payload = " + payload_literal + ";\n"
        "trans.openFromTransObj(payload, {isNew: true});\n"
        "const projectId = trans.project && trans.project.projectId;\n"
        "return {project_id: typeof projectId === 'string' ? projectId : null};\n"
    )
    return _wrap_script(body)


def _snapshot_script(expected_project_id: Optional[str]) -> str:
    expected_literal = "null" if expected_project_id is None else _js_literal(expected_project_id)
    body = (
        "const expectedProjectId = " + expected_literal + ";\n"
        "if (expectedProjectId !== null) {\n"
        "  const project = trans.project;\n"
        "  if (!project || project.projectId !== expectedProjectId) {\n"
        "    throw new Error('PROJECT_ID_MISMATCH');\n"
        "  }\n"
        "}\n"
        "return trans.getSaveData();\n"
    )
    return _wrap_script(body)


def _write_translation_script(file_id: str, row: int, text: str, expected_project_id: str) -> str:
    body = (
        "const expectedProjectId = " + _js_literal(expected_project_id) + ";\n"
        "const fileId = " + _js_literal(file_id) + ";\n"
        "const rowIndex = " + _js_literal(row) + ";\n"
        "const value = " + _js_literal(text) + ";\n"
        "if (trans.project?.projectId !== expectedProjectId) throw new Error('PROJECT_ID_MISMATCH');\n"
        "const files = trans.project.files;\n"
        "if (!files || Array.isArray(files) || !Object.prototype.hasOwnProperty.call(files,fileId)) throw new Error('FILE_NOT_FOUND');\n"
        "const rows = files[fileId]?.data;\n"
        "if (!Array.isArray(rows) || !Array.isArray(rows[rowIndex]) || typeof rows[rowIndex][0] !== 'string') throw new Error('ROW_NOT_FOUND');\n"
        "rows[rowIndex][1] = value;\n"
        "trans.gridIsModified(true);\n"
        "if (trans.getSelectedId?.() === fileId) trans.grid?.render();\n"
        "return {written:true};\n"
    )
    return _wrap_script(body)


def _extract_rpg_script(entry_point: str) -> str:
    body = (
        "const entryPoint = " + _js_literal(entry_point) + ";\n"
        "const game = new addonLoader.addons.rmmv.RMMVGames(entryPoint, {});\n"
        "const project = await game.toTrans();\n"
        "trans.openFromTransObj({project}, {isNew: true});\n"
        "return trans.getSaveData();\n"
    )
    return _wrap_script(body)


def _export_rpg_script(destination: str, expected_project_id: str) -> str:
    body = (
        "const destination = " + _js_literal(destination) + ";\n"
        "const expectedProjectId = " + _js_literal(expected_project_id) + ";\n"
        "\n"
        "const project = trans.project;\n"
        "if (!project || typeof project !== 'object') {\n"
        "  throw new Error('PROJECT_UNAVAILABLE');\n"
        "}\n"
        "if (project.projectId !== expectedProjectId) {\n"
        "  throw new Error('PROJECT_ID_MISMATCH');\n"
        "}\n"
        "\n"
        "const fs = require('fs');\n"
        "if (fs.existsSync(destination)) {\n"
        "  throw new Error('DESTINATION_EXISTS');\n"
        "}\n"
        "\n"
        "await addonLoader.addons.rmmv.exportToFolder(destination, undefined, {});\n"
        "return {output_path: destination, project_id: project.projectId};\n"
    )
    return _wrap_script(body)


class TranslatorPlusPlusClient:
    """Client for the local Translator++ 8.8.9 HTTP bridge.

    ``endpoint`` must be a literal ``http://127.0.0.1:<port>`` URL and
    ``timeout`` is expressed in seconds (1..300). Mutating operations are
    performed exactly once; requests are never retried.
    """

    def __init__(
        self, endpoint: str = _DEFAULT_ENDPOINT, timeout: float = _DEFAULT_TIMEOUT
    ) -> None:
        self.endpoint = _normalize_endpoint(endpoint)
        self.timeout = _normalize_timeout(timeout)
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _RejectRedirects(),
        )

    def discover(self) -> dict:
        """Return the raw ``GET /api/tools`` response after tools validation."""

        response = self._execute("GET", _PATH_TOOLS, None)
        if not isinstance(response.get("tools"), list):
            raise TranslatorPlusPlusError(
                "Translator++ tools response is missing a tools list"
            )
        return response

    def probe(self) -> dict:
        """Verify the installed bridge version and required API surface."""

        info = self._exec_script(_PROBE_SCRIPT)
        version = info.get("version")
        if not isinstance(version, str) or version != _SUPPORTED_VERSION:
            raise TranslatorPlusPlusError(
                "unsupported Translator++ version: " + _bounded_text(version)
            )
        for field in ("rpg_parser", "open_data", "snapshot"):
            if info.get(field) is not True:
                raise TranslatorPlusPlusError(
                    "Translator++ API probe failed: " + field + " is unavailable"
                )
        tool_names = set()
        for entry in self.discover().get("tools", []):
            if isinstance(entry, dict):
                name = entry.get("name")
            elif isinstance(entry, str):
                name = entry
            else:
                name = None
            if isinstance(name, str):
                tool_names.add(name)
        missing = [name for name in _REQUIRED_TOOLS if name not in tool_names]
        if missing:
            raise TranslatorPlusPlusError(
                "Translator++ API probe failed: missing tools " + ", ".join(missing)
            )
        return {
            "version": version,
            "install_root": info.get("install_root"),
            "rpg_parser": True,
            "open_data": True,
            "snapshot": True,
        }

    def open_data(self, data: dict) -> dict:
        """Load ``data`` into Translator++ as a new project.

        Translator++ may add metadata or an empty trailing row; only the
        project id is reported back.
        """

        if not isinstance(data, dict):
            raise TranslatorPlusPlusError("data must be a dict")
        project = data.get("project")
        if not isinstance(project, dict):
            raise TranslatorPlusPlusError("data must contain a project dict")
        project_id = project.get("projectId")
        if not isinstance(project_id, str) or not project_id.strip():
            raise TranslatorPlusPlusError(
                "data must contain a nonempty projectId string"
            )
        result = self._exec_script(_open_data_script(_js_literal(data)))
        returned_id = result.get("project_id")
        if returned_id != project_id:
            raise TranslatorPlusPlusError("Translator++ project identity changed during open")
        return {"project_id": returned_id}

    def snapshot(self, expected_project_id: Optional[str] = None) -> dict:
        """Return the current ``trans.getSaveData()`` snapshot."""

        if expected_project_id is not None:
            _require_nonempty_str(expected_project_id, "expected_project_id")
        result = self._exec_script(_snapshot_script(expected_project_id))
        if not isinstance(result.get("project"), dict):
            raise TranslatorPlusPlusError(
                "Translator++ snapshot is missing project data"
            )
        return result

    def write_translation(
        self,
        file_id: Union[int, str],
        row: int,
        text: str,
        expected_project_id: str,
    ) -> dict:
        """Write ``text`` into the target column (1) of one existing row.

        This is a single-attempt mutation: the request is never retried and the
        translation string is never evaluated, only JSON-encoded.
        """

        _require_file_id(file_id)
        _require_nonnegative_int(row, "row")
        if not isinstance(text, str):
            raise TranslatorPlusPlusError("text must be a string")
        _require_nonempty_str(expected_project_id, "expected_project_id")
        result = self._exec_script(
            _write_translation_script(file_id, row, text, expected_project_id)
        )
        if result.get("written") is not True:
            raise TranslatorPlusPlusError(
                "Translator++ did not confirm the cell write"
            )
        return {"written": True}

    def extract_rpg(self, entry_point: Union[str, "os.PathLike[str]"]) -> dict:
        """Extract a private RPG Maker copy and return the loaded snapshot.

        The caller owns path boundaries; this client only requires an absolute
        ``.html`` entry point. The extraction is never retried.
        """

        path = _require_absolute_path(entry_point, "entry_point")
        if not path.lower().endswith(".html"):
            raise TranslatorPlusPlusError(
                "entry_point must point to an .html entry file"
            )
        result = self._exec_script(_extract_rpg_script(path))
        if not isinstance(result.get("project"), dict):
            raise TranslatorPlusPlusError("Translator++ extraction is missing project data")
        return result

    def export_rpg(
        self, destination: Union[str, "os.PathLike[str]"], expected_project_id: str
    ) -> dict:
        """Export the current RPG project into a non-existing destination.

        This is a single-attempt mutation. The destination directory is never
        removed and output validation belongs to the caller.
        """

        path = _require_absolute_path(destination, "destination")
        _require_nonempty_str(expected_project_id, "expected_project_id")
        result = self._exec_script(_export_rpg_script(path, expected_project_id))
        output_path = result.get("output_path")
        project_id = result.get("project_id")
        if output_path != path:
            raise TranslatorPlusPlusError(
                "Translator++ did not report an output path"
            )
        if project_id != expected_project_id:
            raise TranslatorPlusPlusError(
                "Translator++ did not report an exported project id"
            )
        return {"output_path": output_path, "project_id": project_id}

    def _exec_script(self, script: str) -> dict:
        """Run one fixed, module-private script template via ``/api/exec``."""

        response = self._execute("POST", _PATH_EXEC, {"script": script})
        result = response.get("returned")
        if not isinstance(result, dict):
            raise TranslatorPlusPlusError(
                "Translator++ exec response is missing a returned object"
            )
        return result

    def _execute(self, method: str, path: str, payload: Any) -> dict:
        """Send one JSON request to a fixed bridge path and return the object.

        Private transport only: the path is restricted to the endpoints used by
        the fixed templates above, the endpoint is re-validated on every call,
        and the request is attempted exactly once.
        """

        if path not in _ALLOWED_PATHS:
            raise TranslatorPlusPlusError("unsupported Translator++ API path")
        if method == "GET":
            body = None
        elif method == "POST":
            if not isinstance(payload, dict):
                raise TranslatorPlusPlusError(
                    "Translator++ API request payload must be a dict"
                )
            body = _encode_json(payload)
        else:
            raise TranslatorPlusPlusError("unsupported Translator++ API method")

        endpoint = _normalize_endpoint(self.endpoint)
        request = urllib.request.Request(endpoint + path, data=body, method=method)
        request.add_header("Accept", "application/json")
        if body is not None:
            request.add_header("Content-Type", "application/json; charset=utf-8")

        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
        except TranslatorPlusPlusError:
            raise
        except urllib.error.HTTPError as exc:
            raise TranslatorPlusPlusError(
                "Translator++ API returned HTTP " + str(exc.code)
            ) from exc
        except urllib.error.URLError as exc:
            raise TranslatorPlusPlusError("Translator++ API is unreachable") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise TranslatorPlusPlusError(
                "Translator++ API request timed out"
            ) from exc
        except http.client.HTTPException as exc:
            raise TranslatorPlusPlusError(
                "Translator++ API transport failed"
            ) from exc
        except OSError as exc:
            raise TranslatorPlusPlusError(
                "Translator++ API transport failed"
            ) from exc

        if len(raw) > _MAX_RESPONSE_BYTES:
            raise TranslatorPlusPlusError(
                "Translator++ API response exceeds the 32 MiB limit"
            )
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise TranslatorPlusPlusError(
                "Translator++ API response is not valid UTF-8"
            ) from exc
        try:
            parsed = json.loads(text)
        except ValueError as exc:
            raise TranslatorPlusPlusError(
                "Translator++ API response is not valid JSON"
            ) from exc
        if not isinstance(parsed, dict):
            raise TranslatorPlusPlusError(
                "Translator++ API response must be a JSON object"
            )
        _raise_for_api_error(parsed)
        return parsed
