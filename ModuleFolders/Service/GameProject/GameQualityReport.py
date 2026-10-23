"""One canonical static game report, including existing quality heuristics."""
import uuid
from .CacheBridge import build_projection
from .GameOutputPolicy import preflight_game_output,write_game_json
from .ProjectLock import ProjectLock
from .ProjectStore import ProjectStore
from .ValidationService import inspect_project
from ModuleFolders.Service.Cache.CacheItem import TranslationStatus


def create_game_quality_report(checker,config,project,output_path=None):
    destination=output_path if output_path is not None else getattr(config,'label_output_path',None)
    output=preflight_game_output(project,destination)
    with ProjectLock(project.get_extra('game_project_root')),ProjectStore(project.get_extra('game_project_root')) as store:
        connection=store._connection;connection.execute('BEGIN')
        try:
            metadata=store.metadata()
            canonical=build_projection(store)
            deterministic=inspect_project(store)
            scheduling={'untranslated':0,'translated':0,'polished':0,'excluded':0}
            names={TranslationStatus.UNTRANSLATED:'untranslated',TranslationStatus.TRANSLATED:'translated',
                TranslationStatus.POLISHED:'polished',TranslationStatus.EXCLUDED:'excluded'}
            lookup={}
            for cache_file in canonical.files.values():
                for item in cache_file.items:
                    lookup[(cache_file.storage_path,item.text_index)]=item.get_extra('unit_id')
                    scheduling[names[item.translation_status]]+=1
                    # Quality of accepted text is independent of scheduling or
                    # human lock state; deterministic checks cover exclusions.
                    if item.translated_text and not item.get_extra('blocked_token_codes'):
                        item.translation_status=TranslationStatus.TRANSLATED
            quality=checker._check_cache(config,canonical,collect_only=True,output_path=output)
            for row in quality['errors']:
                row['unit_id']=lookup[(row['storage_path'],row['text_index'])]
            identifier=uuid.uuid4().hex
            report_path=output/f'game-validation-{identifier}.json'
            report={'schema_version':1,'project_id':metadata['project_id'],
                'dataset_revision':metadata['dataset_revision'],'content_revision':metadata['content_revision'],
                'passed':deterministic['passed'] and not quality['errors'],
                'runtime_validation':'not_run','model_quality_validation':'not_run',
                'deterministic':deterministic,'quality':quality,'scheduling':scheduling,
                'report_path':str(report_path)}
            write_game_json(project,output,'game-validation',report,store=store,output_id=identifier)
        finally:connection.rollback()
    print(f"[INFO] 游戏静态质量报告已保存：{report_path}；运行与模型质量验收未执行。")
    return report
