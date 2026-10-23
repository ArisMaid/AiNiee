"""Audit a local RPG portable build, then create a no-overwrite ZIP and hashes."""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import zipfile
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ModuleFolders.Domain.GameProject.Version import VERSION
from ModuleFolders.Service.GameProject.PathGuard import assert_disjoint,safe_join


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def audit(package,output,source_manifest=None):
    package=Path(package).absolute();output=Path(output).absolute()
    safe_join(package,'.audit-boundary');safe_join(output,'.audit-boundary')
    if output.exists():raise ValueError('DELIVERY_PATH_EXISTS')
    if package==output or package in output.parents or output in package.parents:raise ValueError('DELIVERY_PATH_OVERLAP')
    known_root={'_internal','Tools','AiNieeRPG.exe','portable.txt','使用说明.md','IMPLEMENTATION_STATUS.md',
        'BACKEND_EVIDENCE.md','TRANSLATORPP_EVIDENCE.md','JOB_RECOVERY.md','IMAGE_EVIDENCE.md','DEVELOPMENT_PLAN.md',
        'FORMAT_V2_EVIDENCE.md','NUIIT_EVIDENCE.md','FONT_ALIAS_EVIDENCE.md','PROFILE3_EVIDENCE.md',
        'MIGRATION_V2_EVIDENCE.md','CONTROL_R_EVIDENCE.md','F02_UI_BATTLE_EVIDENCE.md','C04_OWNERSHIP_EVIDENCE.md',
        'VALIDATION_RECOVERY_EVIDENCE.md','EXTRACTION_RECOVERY_EVIDENCE.md','MIGRATION_REVIEW_EVIDENCE.md','MIGRATION_RECOVERY_EVIDENCE.md',
        'NATIVE_PROCESS_CONTRACT.md','PROCESS_OWNERSHIP_EVIDENCE.md','PROFILE5_EVIDENCE.md','BACKEND_COMPARISON_EVIDENCE.md',
        'COMMAND_AUDIT_EVIDENCE.md','RPGMTL_COMMON_EVIDENCE.md','RPGMTL_JS_EVIDENCE.md','TALKLIST_EXCLUSION_EVIDENCE.md','COMPARISON_REVIEW_EVIDENCE.md','GUI_WORKFLOW_EVIDENCE.md','STORE_PREPARATION_EVIDENCE.md','COMPACT_UI_EVIDENCE.md',
        'BACKEND_CURRENT_GAME_EVIDENCE.md','SEXTRACTOR_MAIN_EVIDENCE.md','STEV_PROJECT_EVIDENCE.md',
        'MANUAL_EDIT_ATOMIC_EVIDENCE.md','SCENE_BATCH_EVIDENCE.md','E02_REMAINING_FIELDS_EVIDENCE.md','WRITE_ENTRYPOINT_AUDIT.md','CONTEXT_PREPARATION_EVIDENCE.md',
        'MAIN_TASK_SCOPE_EVIDENCE.md','TABLE_TASK_SCOPE_EVIDENCE.md','PROOFREAD_SCOPE_EVIDENCE.md','ANALYSIS_WORKFLOW_EVIDENCE.md','PROFILE6_EVIDENCE.md','PROFILE7_EVIDENCE.md','PROFILE8_EVIDENCE.md','RUNTIME_CAPTURE_EVIDENCE.md','CURRENT_BUILD_RECOVERY_EVIDENCE.md','PORTABLE_SCOPE.md','FONT_LAYOUT_EVIDENCE.md','FONT_COVERAGE_EVIDENCE.md','NOTE_TAG_EVIDENCE.md','NOTE_GROUPS_EVIDENCE.md','NOTE_CONSUMERS_EVIDENCE.md','NOTE_FOLLOWUPS_EVIDENCE.md'}
    known_root.add('FULL_OUTPUT_RUNTIME_EVIDENCE.md')
    known_root.update({'EXTERNAL_TOOLS.md','RELEASE_7.2.4.1.md','EXTERNAL_TOOLS_EVIDENCE_7.2.4.1.md'})
    known_root.update({'Start-AiNieeRPG.cmd','Start-AiNieeRPG.ps1'})
    known_root.add('CUSTOM_JSON_SCOPE_EVIDENCE.md')
    known_root.add('DIRECT_DISPLAY_EVIDENCE.md')
    known_root.add('DISPLAY_LABELS_EVIDENCE.md')
    known_root.add('E03_FOLLOWUPS_EVIDENCE.md')
    known_root.update({'FAILED_RETRIES_EVIDENCE.md','SCAN_EVIDENCE.md','WORKER_PROTOCOL_DECISION.md',
        'REQUIREMENT_COMPLETION_AUDIT.md','SANDBOX_ACCEPTANCE.md','KIND_PROMPTS_EVIDENCE.md','DERIVED_STATUS_EVIDENCE.md'})
    if {p.name for p in package.iterdir()}!=known_root:raise ValueError('PACKAGE_ROOT_UNEXPECTED')
    required=['AiNieeRPG.exe','_internal/runtime/node.exe','_internal/runtime/js/node_modules/acorn/LICENSE',
        '_internal/licenses/AiNiee/LICENSE','_internal/licenses/CPython/LICENSE.txt','_internal/licenses/node-license.txt']
    for rel in required:
        if not(package/rel).is_file():raise ValueError('PACKAGE_REQUIRED_MISSING: '+rel)
    forbidden={'.git','.tools','.venv-rpg','work','__pycache__','tests','deepseek-worker','save','source','projects'}
    secret_name=re.compile(r'(^\.env($|\.)|credentials|api[_-]?keys?\.json|\.rmmzsave$|\.trans$)',re.I)
    key_pattern=re.compile(rb'(?<![A-Za-z0-9])(?:sk-proj-|sk-ant-api|sk-)[A-Za-z0-9_-]{24,}')
    game_hashes=set()
    if source_manifest:
        manifest_path=Path(source_manifest).absolute()
        with sqlite3.connect(manifest_path.as_uri()+'?mode=ro',uri=True) as db:
            source_root=json.loads(db.execute('SELECT value FROM metadata WHERE key=?',('source_root',)).fetchone()[0])
            assert_disjoint(source_root,package,output)
            # Empty files carry no private content and commonly occur as py.typed/REQUESTED.
            game_hashes={r[0] for r in db.execute('SELECT sha256 FROM files WHERE size > 0')}
    files=[];failures=[];public_examples=0;dependency_documents=0
    for folder,dirs,names in os.walk(package,followlinks=False):
        for name in [*dirs,*names]:
            p=Path(folder)/name
            if p.is_symlink() or p.is_junction():raise ValueError('PACKAGE_REPARSE_POINT: '+p.relative_to(package).as_posix())
        for name in names:
            path=Path(folder)/name;rel=path.relative_to(package).as_posix()
            if path.stat().st_nlink>1:raise ValueError('PACKAGE_HARDLINK: '+rel)
            dependency_readme=(rel=='_internal/langcodes/tests/README.md' and
                sha(path)=='9cbb997a2a481cd614786e72955ee3225a350d9eed206544c3aa6b75c58c369d')
            if dependency_readme:dependency_documents+=1
            if (forbidden.intersection(Path(rel).parts) and not dependency_readme) or secret_name.search(name):failures.append('private_path:'+rel)
            if path.suffix.lower() in {'.log','.sqlite3','.db','.traineddata','.rpgmvp','.png_'}:failures.append('private_type:'+rel)
            digest=sha(path)
            if digest in game_hashes:failures.append('game_content_match:'+rel)
            if path.suffix.lower() in {'.json','.yaml','.yml','.toml','.ini','.txt','.md','.ps1','.js','.cjs','.py'} and path.stat().st_size<2*1024*1024:
                for match in key_pattern.finditer(path.read_bytes()):
                    # Exact known example in the baseline UI's "for example" localization.
                    # A different value, file or future real credential still fails.
                    if (rel=='_internal/Resource/Localization/APIManagement.json' and
                        hashlib.sha256(match.group()).hexdigest()=='d510f69fa8bd64f09ab05c3707be38f6251e56df7a79552b575c3119c7de9ffc'):
                        public_examples+=1
                    else:failures.append('credential_pattern:'+rel)
            files.append({'path':rel,'size':path.stat().st_size,'sha256':digest})
    if failures:raise ValueError('PACKAGE_AUDIT_FAILED: '+json.dumps(failures,ensure_ascii=False))
    source_commit=subprocess.run(['git','rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()
    report={'schema_version':1,'version':VERSION,'created_utc':datetime.now(timezone.utc).isoformat(),
        'source_commit':source_commit,'file_count':len(files),'total_bytes':sum(r['size'] for r in files),
        'files':sorted(files,key=lambda r:r['path']),'audit':{'passed':True,'original_game_content_matches':0,
            'credential_patterns':0,'private_work_files':0,'original_game_hashes_checked':bool(source_manifest),
            'public_ui_example_patterns':public_examples,
            'verified_third_party_test_readme':dependency_documents,'empty_file_matches_excluded':True},
        'limits':['Local Windows isolated PATH checks; no clean-machine or remote CI acceptance',
            'Current game and synthetic fixtures only; H03 deferred by user',
            'Real translation API and complete gameplay acceptance remain pending',
            'Optional Translator++, OCR, external backend sources and game/font assets are not bundled']}
    output.mkdir(parents=True,exist_ok=False)
    manifest=output/'PACKAGE_MANIFEST.json';manifest.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    archive=output/('AiNieeRPG-'+VERSION+'-windows-x64.zip')
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for row in report['files']:z.write(package/row['path'],'AiNieeRPG/'+row['path'])
        z.write(manifest,'AiNieeRPG/PACKAGE_MANIFEST.json')
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:raise ValueError('ZIP_CRC_FAILURE')
        for row in report['files']:
            if hashlib.sha256(z.read('AiNieeRPG/'+row['path'])).hexdigest()!=row['sha256']:raise ValueError('ZIP_HASH_FAILURE')
    archive_hash=sha(archive)
    (output/'SHA256SUMS.txt').write_text(archive_hash+'  '+archive.name+'\n'+sha(manifest)+'  '+manifest.name+'\n',encoding='utf-8')
    return {'passed':True,'archive':str(archive),'sha256':archive_hash,'file_count':len(files),'bytes':archive.stat().st_size}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--package',required=True);p.add_argument('--output',required=True)
    p.add_argument('--source-manifest')
    a=p.parse_args();print(json.dumps(audit(a.package,a.output,a.source_manifest),ensure_ascii=False,indent=2))
