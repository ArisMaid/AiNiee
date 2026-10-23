"""Tiny synthetic MV/MZ round trip; no network, model request or game launch."""
import json
from pathlib import Path
import uuid
from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
from ModuleFolders.Service.GameProject.BuildService import BuildService


def self_check(work_root):
    root=Path(work_root)/uuid.uuid4().hex
    source=root/'fixture';(source/'data').mkdir(parents=True);(source/'js').mkdir()
    (source/'index.html').write_text('<!doctype html><title>synthetic acceptance fixture</title>',encoding='utf-8')
    (source/'js/rmmz_core.js').write_text('// synthetic rmmz_core.js v1.7.0',encoding='utf-8')
    (source/'data/System.json').write_text(json.dumps({'gameTitle':'保存','terms':{'commands':['設定']}}),encoding='utf-8')
    with GameProjectService.create(source,root/'project') as service:
        service.extract()
        units=service.store.units()
        results=service.import_translations({u.unit_id:'存档' if u.source_text=='保存' else '设置' for u in units})
        assert all(r.status=='accepted' for r in results)
        build=service.build(root/'output')
        verified=BuildService.verify(build['output_path'])
        from ModuleFolders.Service.GameProject.PatchService import export_patch,apply_patch
        patch=export_patch(service.store,build['output_path'],root/'patches/fixture.zip')
        applied=apply_patch(source,patch['patch_path'],root/'patch-output')
        patch_verified=BuildService.verify(applied['output_path'])
        from ModuleFolders.Infrastructure.GameAdapters.JsWorker.JsBridge import _call
        js=_call({'operation':'extract','source':'var Kd={}; Kd.words={save:"保存"};','object_path':'Kd.words'})
        from PIL import Image
        from io import BytesIO
        from ModuleFolders.Service.GameProject.ImageCodec import encode_image,decode_image
        image=Image.new('RGBA',(8,8),(10,20,30,120));buffer=BytesIO();image.save(buffer,format='PNG')
        raw=buffer.getvalue();key='00112233445566778899aabbccddeeff'
        decoded,info=decode_image(encode_image(raw,'.png_',key),'.png_',key)
        image_ok=decoded==raw and (info['width'],info['height'])==(8,8)
        return {'passed':verified['passed'] and patch_verified['passed'] and len(js)==1 and image_ok,'native_roundtrip':'passed',
            'patch_roundtrip':'passed',
            'encrypted_image_roundtrip':'passed' if image_ok else 'failed',
            'js_parser':'passed','model_requests':0,'game_launches':0,
            'runtime_validation':'not_run','retained_artifacts':str(root)}
