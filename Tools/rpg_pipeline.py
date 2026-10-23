"""RPG workflow CLI. Offline operations never import model clients or launch games."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
from ModuleFolders.Service.GameProject.BuildService import BuildService, write_json


def parser():
    p=argparse.ArgumentParser(description='AiNiee RPG game localization workflow')
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('capabilities',help='Show declared component capabilities and validation scope')
    scan=sub.add_parser('scan');scan.add_argument('--source',required=True);scan.add_argument('--project-root',required=True)
    for name in ['extract','summary','validate','export','import','jobs','recover','resume-scan']:
        c=sub.add_parser(name);c.add_argument('--project',required=True)
        if name=='extract':c.add_argument('--profile')
        if name in ['export','import']:c.add_argument('--file',required=True)
        if name=='validate':c.add_argument('--offline',action='store_true')
    build=sub.add_parser('build');build.add_argument('--project',required=True);build.add_argument('--output-root',required=True)
    build.add_argument('--test',action='store_true',help='Explicitly allow untranslated units to retain source')
    build.add_argument('--runtime-capture',action='store_true')
    resume=sub.add_parser('resume-build');resume.add_argument('--project',required=True);resume.add_argument('--build-id',required=True)
    resume_validation=sub.add_parser('resume-validation');resume_validation.add_argument('--project',required=True)
    resume_validation.add_argument('--job-id',required=True)
    resume_extract=sub.add_parser('resume-extract');resume_extract.add_argument('--project',required=True)
    resume_extract.add_argument('--job-id',required=True)
    capture=sub.add_parser('runtime-report');capture.add_argument('--project',required=True);capture.add_argument('--file',required=True)
    verify=sub.add_parser('verify');verify.add_argument('--build',required=True);verify.add_argument('--offline',action='store_true')
    font=sub.add_parser('font-check');font.add_argument('--project',required=True);font.add_argument('--font',required=True)
    font.add_argument('--include-source',action='store_true',help='Also inspect retained untranslated logical text')
    font_set=sub.add_parser('font-set');font_set.add_argument('--project',required=True);font_set.add_argument('--font',required=True)
    migrate=sub.add_parser('migrate');migrate.add_argument('--old-project',required=True);migrate.add_argument('--project',required=True)
    migrate.add_argument('--apply',action='store_true')
    migrate.add_argument('--confirm-lineage',action='store_true',
        help='Explicitly confirm same-game lineage when game_id is unavailable; never overrides mismatches')
    review=sub.add_parser('migration-review');review.add_argument('--project',required=True)
    review.add_argument('--old-project',required=True);review.add_argument('--confirm-lineage',action='store_true')
    apply_review=sub.add_parser('migration-apply-review');apply_review.add_argument('--project',required=True)
    apply_review.add_argument('--plan-id',required=True)
    resume_migration=sub.add_parser('resume-migration');resume_migration.add_argument('--project',required=True)
    resume_migration.add_argument('--job-id',required=True)
    backend=sub.add_parser('backend-check');backend.add_argument('--project',required=True)
    backend.add_argument('--backend',choices=['stev','rpgmtl','sextractor'],required=True)
    backend.add_argument('--backend-root',required=True);backend.add_argument('--relative-path',required=True)
    command_audit=sub.add_parser('command-audit');command_audit.add_argument('--project',required=True)
    candidate=sub.add_parser('backend-candidate');candidate.add_argument('--project',required=True)
    candidate.add_argument('--backend',choices=['stev','rpgmtl','sextractor'],required=True)
    candidate.add_argument('--backend-root',required=True);candidate.add_argument('--relative-path',required=True)
    route=sub.add_parser('backend-route');route.add_argument('--project',required=True)
    route.add_argument('--backend',choices=['native','stev','rpgmtl','sextractor'],required=True)
    route.add_argument('--backend-root');route.add_argument('--relative-path',required=True)
    tpp_probe=sub.add_parser('tpp-probe');tpp_probe.add_argument('--endpoint',default='http://127.0.0.1:22883')
    tpp_export=sub.add_parser('tpp-export');tpp_export.add_argument('--project',required=True)
    tpp_export.add_argument('--open',action='store_true');tpp_export.add_argument('--endpoint',default='http://127.0.0.1:22883')
    tpp_import=sub.add_parser('tpp-import');tpp_import.add_argument('--project',required=True)
    tpp_import.add_argument('--binding',required=True);tpp_import.add_argument('--file')
    tpp_import.add_argument('--endpoint',default='http://127.0.0.1:22883')
    audit=sub.add_parser('backend-audit');audit.add_argument('--project',required=True);audit.add_argument('--candidate',required=True)
    control=sub.add_parser('job-control');control.add_argument('--project',required=True)
    control.add_argument('--job-id',required=True);control.add_argument('--action',choices=['pause','cancel','resume'],required=True)
    patch_export=sub.add_parser('patch-export');patch_export.add_argument('--project',required=True)
    patch_export.add_argument('--build',required=True);patch_export.add_argument('--file',required=True)
    patch_apply=sub.add_parser('patch-apply');patch_apply.add_argument('--source',required=True)
    patch_apply.add_argument('--patch',required=True);patch_apply.add_argument('--output-root',required=True)
    images=sub.add_parser('images');images.add_argument('--project',required=True)
    for name in ['image-preview','image-ocr','image-regions','image-base','image-render','image-approve']:
        image=sub.add_parser(name);image.add_argument('--project',required=True);image.add_argument('--relative-path',required=True)
        if name=='image-ocr':
            image.add_argument('--executable',required=True);image.add_argument('--tessdata',required=True)
            image.add_argument('--language',default='jpn+eng')
        elif name=='image-regions':
            image.add_argument('--source-sha256',required=True);image.add_argument('--file',required=True)
        elif name=='image-base':
            image.add_argument('--clean-base',required=True);image.add_argument('--font',required=True)
        elif name=='image-approve':image.add_argument('--sha256',required=True)
    sub.add_parser('tools-list')
    for name in ('tools-install','tools-select','tools-start'):
        tool=sub.add_parser(name)
        tool.add_argument('--tool',required=True,choices=['translatorpp','ocr','stev','rpgmtl','sextractor'])
        if name=='tools-select':tool.add_argument('--path',required=True)
    return p


def main(argv=None):
    args=parser().parse_args(argv)
    try:
        if args.command.startswith('tools-'):
            from ModuleFolders.Service.GameProject.ExternalTools import ExternalTools
            manager=ExternalTools()
            if args.command=='tools-list':result={'tools':[manager.status(t) for t in manager.catalog['tools']]}
            elif args.command=='tools-install':result=manager.install(args.tool,lambda text:print(text,file=sys.stderr,flush=True))
            elif args.command=='tools-select':result=manager.select(args.tool,args.path)
            elif args.tool=='translatorpp':result=manager.start_translatorpp()
            else:raise ValueError('只有 Translator++ 需要单独启动；其他工具由具体功能调用。')
        elif args.command=='patch-apply':
            from ModuleFolders.Service.GameProject.PatchService import apply_patch
            result=apply_patch(args.source,args.patch,args.output_root)
        elif args.command=='tpp-probe':
            from ModuleFolders.Infrastructure.GameAdapters.TranslatorPlusPlusClient import TranslatorPlusPlusClient
            result=TranslatorPlusPlusClient(args.endpoint).probe()
        elif args.command=='capabilities':
            from ModuleFolders.Infrastructure.GameAdapters.Registry import AdapterRegistry
            result={'schema_version':1,'capabilities':AdapterRegistry().capability_matrix(),
                'availability':'not_probed','external_write_requires_exact_candidate':True}
        elif args.command=='scan':
            with GameProjectService.create(args.source,args.project_root) as service: result=service.summary()
        elif args.command=='verify': result=BuildService.verify(args.build)
        elif args.command=='runtime-report':
            from ModuleFolders.Service.GameProject.RuntimeCapture import associate_events
            from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
            if Path(args.file).stat().st_size>16*1024*1024:raise ValueError('CAPTURE_TOO_LARGE')
            project=Path(args.project)
            with ProjectStore(project.parent if project.is_file() else project,readonly=True) as store:
                result=associate_events(store,json.loads(Path(args.file).read_text(encoding='utf-8-sig')))
        elif args.command=='font-check':
            from ModuleFolders.Service.GameProject.FontService import inspect_project_font
            from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
            project=Path(args.project)
            with ProjectStore(project.parent if project.is_file() else project,readonly=True) as store:
                result=inspect_project_font(store,args.font,include_source=args.include_source)
        else:
            with GameProjectService(args.project) as service:
                if args.command=='images' or args.command.startswith('image-'):
                    from ModuleFolders.Service.GameProject import ImageService as images
                    if args.command=='images':result=images.inventory(service.store)
                    elif args.command=='image-preview':result=images.preview(service.store,args.relative_path)
                    elif args.command=='image-ocr':result=images.ocr(service.store,args.relative_path,args.executable,args.tessdata,args.language)
                    elif args.command=='image-regions':
                        if Path(args.file).stat().st_size>2*1024*1024:raise ValueError('IMAGE_REGIONS_FILE_TOO_LARGE')
                        result=images.confirm_regions(service.store,args.relative_path,args.source_sha256,
                            json.loads(Path(args.file).read_text(encoding='utf-8-sig')))
                    elif args.command=='image-base':result=images.prepare_base(service.store,args.relative_path,args.clean_base,args.font)
                    elif args.command=='image-render':result=images.render_candidate(service.store,args.relative_path)
                    else:result=images.approve_candidate(service.store,args.relative_path,args.sha256)
                elif args.command=='extract':result=service.extract(args.profile)
                elif args.command=='summary':result=service.summary()
                elif args.command=='patch-export':
                    from ModuleFolders.Service.GameProject.PatchService import export_patch
                    result=export_patch(service.store,args.build,args.file)
                elif args.command=='resume-scan':result=service.resume_scan()
                elif args.command=='resume-build':result=service.resume_build(args.build_id)
                elif args.command=='resume-validation':result=service.resume_validation(args.job_id)
                elif args.command=='resume-extract':result=service.resume_extract(args.job_id)
                elif args.command=='job-control':
                    from ModuleFolders.Service.GameProject.JobControl import request_action
                    job=request_action(service.store,args.job_id,args.action)
                    result={k:job[k] for k in ['job_id','run_state','stage','checkpoint']}
                elif args.command=='backend-audit':
                    from ModuleFolders.Service.GameProject.BackendWriteAudit import audit_json_output
                    result=audit_json_output(service.store,args.candidate)
                elif args.command in {'tpp-export','tpp-import'}:
                    from ModuleFolders.Service.GameProject.TranslatorPlusPlusBridge import (
                        export_exchange,open_exchange,pull_exchange,import_exchange_file)
                    from ModuleFolders.Infrastructure.GameAdapters.TranslatorPlusPlusClient import TranslatorPlusPlusClient
                    if args.command=='tpp-export':
                        result=export_exchange(service.store)
                        if args.open:result['client']=open_exchange(service.store,result['binding_id'],TranslatorPlusPlusClient(args.endpoint))
                    elif args.file:result=import_exchange_file(service.store,args.binding,args.file)
                    else:result=pull_exchange(service.store,args.binding,TranslatorPlusPlusClient(args.endpoint))
                elif args.command=='jobs':result={'jobs':service.store.jobs()}
                elif args.command=='recover':
                    from ModuleFolders.Service.GameProject.JobController import recover_jobs
                    result=recover_jobs(service.store)
                elif args.command=='font-set':result=service.configure_font(args.font)
                elif args.command=='migrate':
                    from ModuleFolders.Service.GameProject.MigrationWorkflow import prepare_review,apply_review
                    envelope=prepare_review(args.old_project,service.store.root,confirm_lineage=args.confirm_lineage)
                    result=dict(envelope['plan'],plan_id=envelope['plan_id'],plan_path=envelope['plan_path'])
                    if args.apply:
                        applied=apply_review(service.store.root,envelope['plan_id'])
                        result.update(results=applied['results'],job_id=applied['job_id'])
                elif args.command=='migration-review':
                    from ModuleFolders.Service.GameProject.MigrationWorkflow import prepare_review
                    envelope=prepare_review(args.old_project,service.store.root,confirm_lineage=args.confirm_lineage)
                    result={'plan_id':envelope['plan_id'],'plan_path':envelope['plan_path'],
                        'identity':envelope['plan']['identity'],'stats':envelope['plan']['stats'],'binding':envelope['binding']}
                elif args.command=='migration-apply-review':
                    from ModuleFolders.Service.GameProject.MigrationWorkflow import apply_review
                    result=apply_review(service.store.root,args.plan_id)
                elif args.command=='resume-migration':
                    from ModuleFolders.Service.GameProject.MigrationWorkflow import resume_review
                    result=resume_review(service.store.root,args.job_id)
                elif args.command=='backend-check':
                    from ModuleFolders.Service.GameProject.BackendComparisonService import compare_backend
                    result=compare_backend(service.store,args.backend,args.backend_root,args.relative_path)
                elif args.command=='command-audit':
                    from ModuleFolders.Service.GameProject.CommandAuditService import audit_commands
                    result=audit_commands(service.store)
                elif args.command=='backend-candidate':
                    from ModuleFolders.Service.GameProject.BackendCandidateService import generate_candidate
                    result=generate_candidate(service.store,args.backend,args.backend_root,args.relative_path)
                elif args.command=='backend-route':
                    from ModuleFolders.Service.GameProject.BackendRoutes import configure_route
                    result=configure_route(service.store,args.relative_path,args.backend,args.backend_root)
                elif args.command=='validate':result=service.validate()
                elif args.command=='build':result=service.build(args.output_root,test=args.test,runtime_capture=args.runtime_capture)
                elif args.command=='export':
                    from ModuleFolders.Service.GameProject.PathGuard import assert_disjoint
                    assert_disjoint(service.store.metadata()['source_root'],Path(args.file).absolute().parent)
                    write_json(Path(args.file),service.export_translations());result={'exported':args.file}
                else:
                    rows=json.loads(Path(args.file).read_text(encoding='utf-8-sig'))
                    results=service.import_translations(rows)
                    result={'results':[r.to_dict() for r in results]}
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0 if result.get('passed',True) else 1
    except Exception as exc:
        print(json.dumps({'error':type(exc).__name__,'message':str(exc)},ensure_ascii=False),file=sys.stderr)
        return 1


if __name__=='__main__':
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')
    raise SystemExit(main())
