"""RPG patch packaging (contract v1).

`export_patch` turns a verified build into an immutable `rpg-patch.json` archive.
`apply_patch` copies the original sources into a new build directory and overlays
the archive's changed files.  Nothing here deletes files, mutates the source
tree, mutates an existing output directory or executes game code.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import stat
import uuid
import zipfile
from pathlib import Path

from .BuildService import BuildService, file_hash, write_json, source_file_set
from .PathGuard import assert_disjoint, atomic_write, safe_join

from .ProjectLock import ProjectLock

PATCH_FORMAT = 'ainiee-rpg-patch'
PATCH_VERSION = 1
PATCH_MANIFEST = 'rpg-patch.json'
PATCH_FILES = 'files/'
_HEX64 = re.compile(r'\A[0-9a-f]{64}\Z')
_MANIFEST_LIMIT = 16 * 1024 * 1024
_CHANGES_LIMIT = 256 * 1024 * 1024
_SOURCE_LIMIT = 16 * 1024 ** 3
_DISK_MARGIN = 64 * 1024 * 1024
_BLOCK = 1024 * 1024


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------

def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _HEX64.match(value) is not None


def _is_size(value: object) -> bool:
    """True for a non-negative int that is not a bool."""

    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _unique_json_object(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('PATCH_DUPLICATE_JSON_KEY')
        result[key]=value
    return result


def _require_path(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f'PATCH_INVALID_PATH: {label} must be a non-empty string')
    return value


def _case_key(path: str) -> str:
    return path.replace('\\', '/').casefold()


def _claim_casefold(seen: dict, path: str) -> None:
    """Reject paths that differ from another path only by case or separators."""

    key = _case_key(path)
    other = seen.get(key)
    if other is not None and other != path:
        raise ValueError(f'PATCH_PATH_CASE_CONFLICT: {path!r} conflicts with {other!r}')
    seen[key] = path


def _member_name(path: str) -> str:
    return PATCH_FILES + path.replace('\\', '/')


def _within(path: object, root: object) -> bool:
    child = os.path.normcase(os.path.abspath(os.fspath(path)))
    parent = os.path.normcase(os.path.abspath(os.fspath(root)))
    if child == parent:
        return True
    return child.startswith(parent.rstrip('\\/') + os.sep)


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

def export_patch(store, build_path, target_file):
    """Archive the changed files of a verified build; refuses to overwrite."""

    with ProjectLock(store.root):
        return _export_locked(store, build_path, target_file)


def _export_locked(store, build_path, target_file):
    metadata = store.metadata()
    project_id = metadata.get('project_id')
    if not isinstance(project_id, str) or not project_id:
        raise ValueError('PROJECT_ID_MISSING')
    source_root = metadata.get('source_root')
    if not source_root:
        raise ValueError('SOURCE_ROOT_MISSING')
    source = Path(os.path.abspath(os.fspath(source_root)))
    build = Path(os.path.abspath(os.fspath(build_path)))
    assert_disjoint(source, build)
    requested = Path(os.path.abspath(os.fspath(target_file)))
    target = safe_join(requested.parent, requested.name)
    assert_disjoint(source, target.parent)
    if os.path.lexists(target):
        raise ValueError(f'PATCH_TARGET_EXISTS: {target}')

    manifest = json.loads(
        safe_join(build, 'rpg-build-manifest.json', must_exist=True).read_text(encoding='utf-8'),object_pairs_hook=_unique_json_object
    )
    if not isinstance(manifest, dict):
        raise ValueError('BUILD_MANIFEST_INVALID')
    if manifest.get('project_id') != project_id:
        raise ValueError('BUILD_PROJECT_MISMATCH: build belongs to another project')
    declared = manifest.get('schema_version', 1)
    if type(declared) is not int or declared != 1:
        raise ValueError(f'BUILD_MANIFEST_VERSION_UNSUPPORTED: {declared!r}')
    build_id = manifest.get('build_id')
    if not isinstance(build_id, str) or not build_id:
        raise ValueError('BUILD_ID_MISSING')
    registered=store.get_build_record(build_id)
    if registered is None:raise ValueError('BUILD_NOT_REGISTERED: recover or rebuild the output before exporting')
    registered=dict(registered);registered.pop('recorded_at',None)
    if manifest!=registered:raise ValueError('BUILD_MANIFEST_CHANGED: output differs from the project build record')
    report = BuildService.verify(build)
    if not report.get('passed'):
        raise ValueError('BUILD_VERIFY_FAILED: ' + ', '.join(report.get('changed_files') or []))
    input_digest = manifest.get('input_digest')
    if not _is_sha256(input_digest):
        raise ValueError('BUILD_INPUT_DIGEST_MISSING')
    mode = manifest.get('mode') or 'complete'
    if not isinstance(mode,str) or mode not in {'test','complete'}:
        raise ValueError('BUILD_MODE_INVALID')

    records = {}
    for record in store.files():
        relative = record.get('relative_path')
        if not isinstance(relative, str) or not relative:
            raise ValueError('STORE_RECORD_INVALID')
        records[relative] = record

    source_files = []
    changed = []
    seen = set()
    for row in manifest.get('files') or []:
        if not isinstance(row, dict):
            raise ValueError('BUILD_MANIFEST_ROW_INVALID')
        path = row.get('path')
        if not isinstance(path, str) or not path:
            raise ValueError('BUILD_MANIFEST_ROW_INVALID')
        if path in seen:
            raise ValueError(f'BUILD_MANIFEST_DUPLICATE_PATH: {path}')
        seen.add(path)
        safe_join(build, path)
        original = row.get('original_sha256')
        output = row.get('output_sha256')
        if original is None and output is None:
            raise ValueError(f'BUILD_MANIFEST_ROW_INVALID: {path}')
        if original is not None:
            if not _is_sha256(original):
                raise ValueError(f'BUILD_ORIGINAL_HASH_INVALID: {path}')
            record = records.get(path)
            if record is None:
                raise ValueError(f'SOURCE_RECORD_MISSING: {path}')
            if record.get('sha256') != original:
                raise ValueError(f'SOURCE_RECORD_HASH_MISMATCH: {path}')
            size = record.get('size')
            if not _is_size(size):
                raise ValueError(f'SOURCE_RECORD_SIZE_INVALID: {path}')
            safe_join(source, path)
            source_files.append({'path': path, 'sha256': original, 'size': size})
        if output != original:
            if not _is_sha256(output):
                raise ValueError(f'BUILD_OUTPUT_HASH_INVALID: {path}')
            changed.append((path, original, output))

    files = []
    payloads = []
    total = 0
    for path, original, output in changed:
        with safe_join(build,path,must_exist=True).open('rb') as stream:
            blob=stream.read(_CHANGES_LIMIT-total+1)
        if len(blob)>_CHANGES_LIMIT-total:
            raise ValueError('PATCH_TOO_LARGE: changed files exceed 256 MiB')
        if hashlib.sha256(blob).hexdigest() != output:
            raise ValueError(f'BUILD_OUTPUT_CHANGED: {path}')
        total += len(blob)
        if total > _CHANGES_LIMIT:
            raise ValueError('PATCH_TOO_LARGE: changed files exceed 256 MiB')
        files.append({'path': path, 'original_sha256': original,
            'output_sha256': output, 'size': len(blob)})
        payloads.append((path, blob))

    document = {'format': PATCH_FORMAT, 'version': PATCH_VERSION, 'project_id': project_id,
        'source_build_id': build_id, 'input_digest': input_digest, 'mode': mode,
        'source_files': source_files, 'files': files,
        'untranslated_unit_count':len(manifest.get('missing_translation_unit_ids',[])),
        'runtime_capture_script_present':any(row['path']=='js/AiNieeCapture.js' for row in manifest['files'])}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(PATCH_MANIFEST,
            (json.dumps(document, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
        for path, blob in payloads:
            archive.writestr(_member_name(path), blob)
    data = buffer.getvalue()
    atomic_write(target, data)
    return {'patch_path': str(target), 'sha256': hashlib.sha256(data).hexdigest(),
        'changed_files': len(files), 'source_file_count': len(source_files), 'mode': mode,
        'runtime_capture_script_present':document['runtime_capture_script_present']}


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------

def _open_patch(patch):
    try:
        return zipfile.ZipFile(patch, 'r')
    except zipfile.BadZipFile as error:
        raise ValueError(f'PATCH_ZIP_INVALID: {error}') from error


def _members(archive):
    try:
        infos = archive.infolist()
    except zipfile.BadZipFile as error:
        raise ValueError(f'PATCH_ZIP_INVALID: {error}') from error
    names = [info.filename for info in infos]
    if len(names) != len(set(names)):
        raise ValueError('PATCH_DUPLICATE_MEMBER')
    for info in infos:
        if info.flag_bits & 0x1:
            raise ValueError(f'PATCH_ENCRYPTED_MEMBER: {info.filename}')
        if stat.S_ISLNK(info.external_attr >> 16):
            raise ValueError(f'PATCH_SYMLINK_MEMBER: {info.filename}')
    return infos


def _document(archive, infos):
    info = next((item for item in infos if item.filename == PATCH_MANIFEST), None)
    if info is None:
        raise ValueError('PATCH_MANIFEST_MISSING')
    if info.file_size > _MANIFEST_LIMIT:
        raise ValueError('PATCH_MANIFEST_TOO_LARGE')
    raw = _member_bytes(archive, info, _MANIFEST_LIMIT)
    if len(raw) > _MANIFEST_LIMIT:
        raise ValueError('PATCH_MANIFEST_TOO_LARGE')
    document = json.loads(raw.decode('utf-8'),object_pairs_hook=_unique_json_object)
    if not isinstance(document, dict):
        raise ValueError('PATCH_MANIFEST_INVALID')
    if document.get('format') != PATCH_FORMAT:
        raise ValueError('PATCH_FORMAT_UNSUPPORTED')
    version = document.get('version', document.get('schema_version'))
    if type(version) is not int or version != PATCH_VERSION or type(document.get('schema_version',PATCH_VERSION)) is not int or document.get('schema_version', PATCH_VERSION) != PATCH_VERSION:
        raise ValueError(f'PATCH_VERSION_UNSUPPORTED: {version!r}')
    if not isinstance(document.get('project_id'), str) or not document.get('project_id'):
        raise ValueError('PATCH_PROJECT_ID_INVALID')
    if not isinstance(document.get('source_build_id'), str) or not document.get('source_build_id'):
        raise ValueError('PATCH_SOURCE_BUILD_ID_INVALID')
    if not _is_sha256(document.get('input_digest')):
        raise ValueError('PATCH_INPUT_DIGEST_INVALID')
    if not isinstance(document.get('source_files'), list):
        raise ValueError('PATCH_SCHEMA_INVALID: source_files must be a list')
    if not isinstance(document.get('files'), list):
        raise ValueError('PATCH_SCHEMA_INVALID: files must be a list')
    if not isinstance(document.get('mode'),str) or document['mode'] not in {'test','complete'}:
        raise ValueError('PATCH_MODE_INVALID')
    if not document['source_files'] or len(document['source_files'])>50000 or len(document['files'])>50000:
        raise ValueError('PATCH_FILE_COUNT_INVALID')
    if not _is_size(document.get('untranslated_unit_count',0)):
        raise ValueError('PATCH_UNTRANSLATED_COUNT_INVALID')
    return document


def _member_bytes(archive, info, limit):
    try:
        with archive.open(info) as handle:
            return handle.read(limit + 1)
    except (zipfile.BadZipFile, EOFError) as error:
        raise ValueError(f'PATCH_ZIP_INVALID: {error}') from error


def _source_requirement(row):
    if not isinstance(row, dict):
        raise ValueError('PATCH_SOURCE_ROW_INVALID')
    path = _require_path(row.get('path'), 'source_files.path')
    digest = row.get('sha256')
    if not _is_sha256(digest):
        raise ValueError(f'PATCH_SOURCE_HASH_INVALID: {path}')
    size = row.get('size')
    if not _is_size(size):
        raise ValueError(f'PATCH_SOURCE_SIZE_INVALID: {path}')
    return {'path': path, 'sha256': digest, 'size': size}


def _changed_entry(row, source_lookup):
    if not isinstance(row, dict):
        raise ValueError('PATCH_FILE_ROW_INVALID')
    path = _require_path(row.get('path'), 'files.path')
    original = row.get('original_sha256')
    if original is not None and not _is_sha256(original):
        raise ValueError(f'PATCH_ORIGINAL_HASH_INVALID: {path}')
    output = row.get('output_sha256')
    if not _is_sha256(output):
        raise ValueError(f'PATCH_OUTPUT_HASH_INVALID: {path}')
    size = row.get('size')
    if not _is_size(size):
        raise ValueError(f'PATCH_FILE_SIZE_INVALID: {path}')
    if original is None:
        if path in source_lookup:
            raise ValueError(f'PATCH_NEW_FILE_LISTED_AS_SOURCE: {path}')
    elif source_lookup.get(path) != original:
        raise ValueError(f'PATCH_ORIGINAL_NOT_IN_SOURCE: {path}')
    return {'path': path, 'original_sha256': original,
        'output_sha256': output, 'size': size}


def apply_patch(source_root, patch_file, output_root, progress=None):
    """Copy the sources into a new build directory and overlay patch changes."""

    source = Path(os.path.abspath(os.fspath(source_root)))
    output = Path(os.path.abspath(os.fspath(output_root)))
    patch = Path(os.path.abspath(os.fspath(patch_file)))
    safe_join(source, '.boundary-check')
    safe_join(output, '.boundary-check')
    assert_disjoint(source, output)
    if _within(patch, source):
        raise ValueError(f'PATCH_INSIDE_SOURCE: {patch}')
    patch = safe_join(patch.parent, patch.name, must_exist=True)
    if not patch.is_file():
        raise ValueError(f'PATCH_FILE_INVALID: {patch}')

    with _open_patch(patch) as archive:
        infos = _members(archive)
        document = _document(archive, infos)

        source_rows = []
        source_lookup = {}
        changed_rows = []
        changed_seen = set()
        casefold = {}
        source_total = 0
        changes_total = 0
        for row in document['source_files']:
            parsed = _source_requirement(row)
            if parsed['path'] in source_lookup:
                raise ValueError(f'PATCH_DUPLICATE_SOURCE_PATH: {parsed["path"]}')
            safe_join(source, parsed['path'])
            _claim_casefold(casefold, parsed['path'])
            source_lookup[parsed['path']] = parsed['sha256']
            source_total += parsed['size']
            source_rows.append(parsed)
        if source_total > _SOURCE_LIMIT:
            raise ValueError('PATCH_SOURCE_TOTAL_TOO_LARGE: sources exceed 16 GiB')
        if source_file_set(source)!=set(source_lookup):raise ValueError('PATCH_SOURCE_FILE_SET_CHANGED')
        for row in document['files']:
            parsed = _changed_entry(row, source_lookup)
            if parsed['path'] in changed_seen:
                raise ValueError(f'PATCH_DUPLICATE_CHANGED_PATH: {parsed["path"]}')
            safe_join(source, parsed['path'])
            _claim_casefold(casefold, parsed['path'])
            if parsed['original_sha256'] is None and safe_join(source,parsed['path']).exists():
                raise ValueError('PATCH_NEW_FILE_EXISTS_IN_SOURCE')
            changed_seen.add(parsed['path'])
            changes_total += parsed['size']
            changed_rows.append(parsed)
        if changes_total > _CHANGES_LIMIT:
            raise ValueError('PATCH_CHANGES_TOTAL_TOO_LARGE: changes exceed 256 MiB')

        members = {info.filename: info for info in infos}
        expected = {PATCH_MANIFEST} | {_member_name(row['path']) for row in changed_rows}
        if set(members) != expected:
            raise ValueError('PATCH_MEMBERS_MISMATCH: extra={0} missing={1}'.format(
                sorted(set(members) - expected), sorted(expected - set(members))))
        payloads={}
        for row in changed_rows:
            info=members[_member_name(row['path'])]
            if info.file_size != row['size']:
                raise ValueError(f'PATCH_ZIP_SIZE_MISMATCH: {row["path"]}')
            blob=_member_bytes(archive,info,row['size'])
            if len(blob)!=row['size'] or hashlib.sha256(blob).hexdigest()!=row['output_sha256']:
                raise ValueError('PATCH_HASH_MISMATCH')
            payloads[row['path']]=blob

        required = source_total + changes_total + _DISK_MARGIN
        probe = output
        while not probe.exists() and probe.parent != probe:
            probe = probe.parent
        if shutil.disk_usage(probe).free < required:
            raise ValueError(f'INSUFFICIENT_DISK_SPACE: need at least {required} bytes')

        for row in source_rows:
            original = safe_join(source, row['path'])
            if not original.is_file():
                raise ValueError(f'PATCH_SOURCE_MISSING: {row["path"]}')
            if original.stat().st_size != row['size'] or file_hash(original) != row['sha256']:
                raise ValueError(f'PATCH_SOURCE_HASH_MISMATCH: {row["path"]}')

        output.mkdir(parents=True, exist_ok=True)
        build_id = uuid.uuid4().hex
        staging = safe_join(output, f'.staging-patch-{build_id}')
        final = safe_join(output, f'game-zh-CN-patch-{build_id}')
        if os.path.lexists(final):
            raise ValueError(f'PATCH_OUTPUT_EXISTS: {final}')
        staging.mkdir(parents=False, exist_ok=False)

        total = len(source_rows)
        for index, row in enumerate(source_rows):
            destination = safe_join(staging, row['path'])
            destination.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            with open(safe_join(source, row['path']), 'rb') as source_file:
                with open(destination, 'xb') as staged_file:
                    for block in iter(lambda: source_file.read(_BLOCK), b''):
                        staged_file.write(block)
                        digest.update(block)
                    staged_file.flush()
                    os.fsync(staged_file.fileno())
            if digest.hexdigest() != row['sha256']:
                raise ValueError(f'PATCH_SOURCE_CHANGED: {row["path"]}')
            if progress:
                progress(index + 1, total, row['path'])

        for row in changed_rows:
            blob = payloads[row['path']]
            if len(blob) != row['size']:
                raise ValueError(f'PATCH_SIZE_MISMATCH: {row["path"]}')
            if hashlib.sha256(blob).hexdigest() != row['output_sha256']:
                raise ValueError(f'PATCH_HASH_MISMATCH: {row["path"]}')
            destination = safe_join(staging, row['path'])
            if row['original_sha256'] is None:
                atomic_write(destination, blob)
                continue
            if not destination.is_file():
                raise ValueError(f'PATCH_SOURCE_NOT_COPIED: {row["path"]}')
            atomic_write(destination, blob, overwrite=True)

        for row in source_rows:
            current = safe_join(source, row['path'])
            if not current.is_file() or file_hash(current) != row['sha256']:
                raise ValueError(f'PATCH_SOURCE_CHANGED: {row["path"]}')

        if source_file_set(source)!=set(source_lookup):raise ValueError('PATCH_SOURCE_FILE_SET_CHANGED_DURING_COPY')
        changed_lookup = {row['path']: row for row in changed_rows}
        output_files = []
        for row in source_rows:
            change = changed_lookup.get(row['path'])
            output_files.append({'path': row['path'], 'original_sha256': row['sha256'],
                'output_sha256': change['output_sha256'] if change else row['sha256']})
        for row in changed_rows:
            if row['original_sha256'] is None:
                output_files.append({'path': row['path'], 'original_sha256': None,
                    'output_sha256': row['output_sha256']})
        manifest = {'schema_version': 1, 'build_id': build_id,
            'project_id': document['project_id'], 'input_digest': document['input_digest'],
            'mode': document.get('mode') or 'complete', 'runtime_validation': 'not_run',
            'files': output_files, 'output_path': str(final),
            'runtime_capture_script_present':any(row['path']=='js/AiNieeCapture.js' for row in output_files),
            'untranslated_unit_count':document.get('untranslated_unit_count',0)}
        write_json(staging / 'rpg-build-manifest.json', manifest)
        write_json(staging / 'rpg-build-complete.json',
            {'build_id': build_id, 'input_digest': document['input_digest']})
        staging.rename(final)
    return manifest
