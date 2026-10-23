"""Subprocess bridges for extraction and approved memory-only write candidates.

``extract_document`` and ``rewrite_document`` run the dedicated BackendWorker
in an isolated subprocess and returns its decoded JSON result. The parent process
never imports the vendored extractors and never writes into an upstream tree: the
    request/result files live in a fresh UUID work subdirectory, every write is a
temp-file + ``os.replace`` atomic write, and a UUID collision can never delete an
existing entry.

Only a minimal OS environment is forwarded (no inherited API keys or provider
configuration), stdin/stdout are UTF-8 pipes, ``shell=False`` is always used and
each worker has a 60 second timeout and a 16MB request/response bound. SExtractor
writes use separate extraction and import workers through the real main entry.

This bridge has no real source-root parameter: callers pass the document bytes
that were read elsewhere, so no game directory is opened here.
"""

from __future__ import annotations

import json
import base64
import hashlib
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from ModuleFolders.Service.GameProject.PathGuard import safe_join, atomic_write

MAX_IO_BYTES = 16 * 1024 * 1024
TIMEOUT_SECONDS = 60
WORKER_FILENAME = "BackendWorker.py"
REPO_ROOT = Path(__file__).resolve().parents[3]

EXPECTED_UPSTREAM_FILES = {
    "stev": ("jtpp.py",),
    "rpgmtl": ("plugins/json.py",),
    "sextractor": ("src/extract_RPGMV.py",),
}
ENV_ALLOWLIST = (
    "PATH",
    "Path",
    "PATHEXT",
    "SystemRoot",
    "SYSTEMROOT",
    "WINDIR",
    "windir",
    "COMSPEC",
    "TEMP",
    "TMP",
)
DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


def extract_document(backend, relative_path, payload, work_root, backend_root):
    """Run one read-only extraction and return the decoded worker response.

    ``payload`` is the raw JSON document as bytes. Every rejected input or failed
    worker run raises ``ValueError`` with an actionable message; otherwise the
    decoded result dict (``{"ok", "backend", "records", "capabilities"}``) is
    returned unchanged.
    """
    backend = _validate_backend(backend)
    safe_relative_path = _validate_relative_path(relative_path)
    source_text = _validate_payload(payload)
    backend_dir = _validate_backend_root(backend_root, backend)
    case_dir = _create_case_dir(_validate_work_root(work_root))
    run_dir = case_dir / "cwd"
    try:
        run_dir.mkdir()
    except OSError as exc:
        raise ValueError(f"could not create an isolated cwd under {case_dir}: {exc}") from exc

    request_bytes = json.dumps(
        {
            "backend": backend,
            "backend_root": str(backend_dir),
            "relative_path": safe_relative_path,
            "source": source_text,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    if len(request_bytes) > MAX_IO_BYTES:
        raise ValueError(
            f"request exceeds the {MAX_IO_BYTES} byte bound "
            f"({len(request_bytes)} bytes)"
        )
    _atomic_write_bytes(case_dir / "request.json", request_bytes)

    completed = _run_worker(request_bytes, run_dir, backend)
    stdout = completed.stdout or b""
    if isinstance(stdout, str):
        stdout = stdout.encode("utf-8")
    if len(stdout) > MAX_IO_BYTES:
        raise ValueError(
            f"backend {backend!r} produced more than the {MAX_IO_BYTES} byte bound"
        )
    _atomic_write_bytes(case_dir / "result.json", stdout)
    return _decode_result(stdout, completed, backend)


def rewrite_document(backend,relative_path,payload,changes,work_root,backend_root,*,javascript=False):
    """Run the selected isolated write path and retain its sidecar.

    The caller must compare the result with its approved native write plan before
    publishing. SExtractor uses two real main-entry phases; other writers use
    their memory APIs. No original game directory is available to a worker.
    """
    backend=_validate_backend(backend)
    relative_path=_validate_relative_path(relative_path,formats=('.js',) if javascript else ('.json',))
    if javascript:
        if backend!='rpgmtl':raise ValueError('BACKEND_FILE_UNSUPPORTED')
        if any(isinstance(row,dict) and row.get('node_kind')=='template-part' for row in changes):
            raise ValueError('BACKEND_JS_TEMPLATE_UNSUPPORTED: use the native JS writer for this file')
        if not isinstance(payload,(bytes,bytearray,memoryview)) or len(payload)>MAX_IO_BYTES:
            raise ValueError('BACKEND_SOURCE_INVALID')
        bytes(payload).decode('utf-8-sig')
    else:_validate_payload(payload)
    payload=bytes(payload)
    root=_validate_backend_root(backend_root,backend)
    if backend=='sextractor' and not javascript:
        # Default SExtractor write path: the actual two-phase main_extract
        # pipeline. There is deliberately no fallback to the memory-only writer.
        from .SExtractorMainBridge import rewrite_document as rewrite_sextractor_main
        return rewrite_sextractor_main(relative_path,payload,changes,work_root,root)
    if javascript and not safe_join(root,'plugins/javascript.py',must_exist=True).is_file():
        raise ValueError('BACKEND_UPSTREAM_MISSING: plugins/javascript.py')
    case_dir=_create_case_dir(_validate_work_root(work_root));run_dir=case_dir/'cwd';run_dir.mkdir()
    request={'operation':'write_js' if javascript else 'write','backend':backend,'relative_path':relative_path,
        'backend_root':str(root),'source_base64':base64.b64encode(payload).decode('ascii'),'changes':changes}
    raw=json.dumps(request,ensure_ascii=False).encode('utf-8')
    if len(raw)>MAX_IO_BYTES:raise ValueError('BACKEND_REQUEST_TOO_LARGE')
    atomic_write(case_dir/'request.json',raw)
    completed=_run_worker(raw,run_dir,backend)
    if len(completed.stdout)>MAX_IO_BYTES:raise ValueError('BACKEND_RESPONSE_TOO_LARGE')
    atomic_write(case_dir/'result.json',completed.stdout)
    result=_decode_result(completed.stdout,completed,backend)
    encoded=result.pop('output_base64',None)
    if not isinstance(encoded,str):raise ValueError('BACKEND_OUTPUT_INVALID')
    try:output=base64.b64decode(encoded,validate=True)
    except ValueError as error:raise ValueError('BACKEND_OUTPUT_INVALID') from error
    if len(output)>MAX_IO_BYTES:raise ValueError('BACKEND_OUTPUT_TOO_LARGE')
    sidecar=result.get('sidecar')
    if not isinstance(sidecar,dict) or sidecar.get('source_sha256')!=hashlib.sha256(payload).hexdigest():
        raise ValueError('BACKEND_SOURCE_HASH_MISMATCH')
    atomic_write(case_dir/'sidecar.json',json.dumps(sidecar,ensure_ascii=False,indent=2).encode('utf-8'))
    result.update(output_bytes=output,sidecar_path=str(case_dir/'sidecar.json'))
    return result


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------
def _validate_backend(backend):
    if not isinstance(backend, str) or backend not in EXPECTED_UPSTREAM_FILES:
        raise ValueError(
            f"unknown backend {backend!r}; expected one of "
            f"{', '.join(sorted(EXPECTED_UPSTREAM_FILES))}"
        )
    return backend


def _validate_relative_path(relative_path,*,formats=('.json',)):
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise ValueError("relative_path must be a non-empty string")
    normalized = relative_path.strip().replace("\\", "/")
    if any(ord(character) < 32 for character in normalized):
        raise ValueError("relative_path must not contain control characters")
    if normalized.startswith("/") or DRIVE_PREFIX.match(normalized):
        raise ValueError(
            f"relative_path must be relative to the upstream data root: {relative_path!r}"
        )
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise ValueError(
            f"relative_path must not escape the upstream data root: {relative_path!r}"
        )
    if not parts[-1].lower().endswith(formats):
        raise ValueError(
            f"relative_path must point to a .json document: {relative_path!r}"
        )
    return "/".join(parts)


def rewrite_js_document(backend,relative_path,payload,changes,work_root,backend_root):
    return rewrite_document(backend,relative_path,payload,changes,work_root,backend_root,javascript=True)


def _validate_payload(payload):
    if isinstance(payload, (bytes, bytearray, memoryview)):
        data = bytes(payload)
    else:
        raise ValueError("payload must be the raw JSON document bytes")
    if len(data) > MAX_IO_BYTES:
        raise ValueError(
            f"payload exceeds the {MAX_IO_BYTES} byte bound ({len(data)} bytes)"
        )
    try:
        source_text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"payload is not valid UTF-8 JSON text: {exc}") from exc
    try:
        document = json.loads(source_text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"payload is not valid JSON ({exc.msg} at line {exc.lineno} column {exc.colno})"
        ) from exc
    if not isinstance(document, (dict, list)):
        raise ValueError("payload JSON must be an object or array document")
    return source_text


def _validate_backend_root(backend_root, backend):
    if backend_root is None:
        raise ValueError("backend_root is required")
    if not isinstance(backend_root, (str, os.PathLike)):
        raise ValueError("backend_root must be a filesystem path")
    path = Path(backend_root)
    if not path.is_absolute():
        raise ValueError(f"backend_root must be an absolute path: {backend_root!r}")
    path = path.absolute()
    if not path.is_dir():
        raise ValueError(f"backend_root is not an existing directory: {path}")
    missing = [
        relative
        for relative in EXPECTED_UPSTREAM_FILES[backend]
        if not safe_join(path,relative,must_exist=True).is_file()
    ]
    if missing:
        raise ValueError(
            f"backend_root {path} does not look like the {backend!r} upstream tree; "
            f"missing: {', '.join(missing)}"
        )
    return path


def _validate_work_root(work_root):
    if work_root is None:
        raise ValueError("work_root is required")
    if not isinstance(work_root, (str, os.PathLike)):
        raise ValueError("work_root must be a filesystem path")
    path = Path(work_root)
    if not path.is_absolute():
        raise ValueError(f"work_root must be an absolute path: {work_root!r}")
    path = safe_join(path.absolute().parent, path.name)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"could not create work_root {path}: {exc}") from exc
    return path


def _create_case_dir(work_root):
    for _ in range(8):
        case_dir = work_root / uuid.uuid4().hex
        try:
            case_dir.mkdir()
        except FileExistsError:
            continue
        except OSError as exc:
            raise ValueError(
                f"could not create a work subdirectory under {work_root}: {exc}"
            ) from exc
        return case_dir
    raise ValueError(f"could not allocate a unique work subdirectory under {work_root}")


# ---------------------------------------------------------------------------
# execution
# ---------------------------------------------------------------------------
def _worker_env():
    allowed={key.upper() for key in ENV_ALLOWLIST}
    env={key:value for key,value in os.environ.items() if key.upper() in allowed and value}
    # Explicit trusted project path so the worker can reach project modules.
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _run_worker(request_bytes, run_dir, backend):
    from ModuleFolders.Infrastructure.Platform.WorkerProtocol import run_json_worker
    from ModuleFolders.Infrastructure.Platform.OwnedProcess import OutputLimitExceeded
    worker_path = Path(__file__).resolve().parent / WORKER_FILENAME
    if not worker_path.is_file() and not getattr(sys,'frozen',False):
        raise ValueError(f"extraction worker script is missing: {worker_path}")
    try:
        return run_json_worker(
            ([sys.executable,'--backend-worker'] if getattr(sys,'frozen',False)
                else [sys.executable, str(worker_path)]),
            payload=json.loads(request_bytes),
            cwd=str(run_dir),
            env=_worker_env(),
            timeout=TIMEOUT_SECONDS,
            stdout_limit=MAX_IO_BYTES,
        )
    except OutputLimitExceeded as exc:
        raise ValueError('BACKEND_OUTPUT_LIMIT') from exc
    except subprocess.TimeoutExpired as exc:
        raise ValueError(
            f"backend {backend!r} timed out after {TIMEOUT_SECONDS} seconds"
        ) from exc
    except OSError as exc:
        raise ValueError(f"could not start the extraction worker: {exc}") from exc


def _decode_result(stdout, completed, backend):
    if completed.returncode:
        raise ValueError(f'BACKEND_FAILED: {backend} exited {completed.returncode}')
    try:
        text = stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"backend {backend!r} produced output that is not valid UTF-8: {exc}"
        ) from exc
    text = text.strip()
    if not text:
        raise ValueError(
            f"backend {backend!r} produced no result (exit code "
            f"{completed.returncode}): {_stderr_excerpt(completed)}"
        )
    try:
        result = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"backend {backend!r} produced invalid JSON ({exc.msg}); exit code "
            f"{completed.returncode}: {_stderr_excerpt(completed)}"
        ) from exc
    if not isinstance(result, dict):
        raise ValueError(f"backend {backend!r} returned a non-object result")
    if result.get("ok") is not True:
        error = result.get("error")
        raise ValueError(
            f"backend {backend!r} failed: "
            f"{error if isinstance(error, str) else 'unknown error'}"
        )
    if 'records' in result:
        from .ExtractionPointerPool import pointer_lists
        pointer_lists(result)  # Validate references without expanding arrays.
    return result


def _stderr_excerpt(completed, limit=600):
    stderr = completed.stderr or b""
    if isinstance(stderr, str):
        stderr = stderr.encode("utf-8", errors="replace")
    text = " ".join(stderr.decode("utf-8", errors="replace").split())
    if len(text) > limit:
        text = "..." + text[-limit:]
    return text or "<no stderr>"


def _atomic_write_bytes(path, data):
    atomic_write(path,data)
