import io
import json
from pathlib import Path
import unittest
import zipfile

import test_adapter_acceptance as fixtures
from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
from ModuleFolders.Service.GameProject.BuildService import BuildService,file_hash
from ModuleFolders.Service.GameProject.PatchService import export_patch,apply_patch


class PatchAcceptance(unittest.TestCase):
    setUp=fixtures.AdapterAcceptance.setUp
    write=fixtures.AdapterAcceptance.write

    def build_patch(self,capture=False):
        project=self.root.parent/(self.root.name+'-patch-project')
        output=self.root.parent/(self.root.name+'-patch-build')
        patch=self.root.parent/(self.root.name+'-patches')/'translation.zip'
        with GameProjectService.create(self.root,project) as service:
            service.extract()
            unit=next(u for u in service.store.units() if u.source_text=='学校')
            service.import_translations({unit.unit_id:'学院'})
            build=service.build(output,test=True,runtime_capture=capture)
            result=export_patch(service.store,build['output_path'],patch)
        return project,build,patch,result

    def test_roundtrip_changed_only_and_new_output_files(self):
        hashes={p.relative_to(self.root).as_posix():file_hash(p) for p in self.root.rglob('*') if p.is_file()}
        project,build,patch,result=self.build_patch(capture=True)
        with zipfile.ZipFile(patch) as archive:
            names=set(archive.namelist())
        self.assertEqual(names,{'rpg-patch.json','files/data/Map001.json','files/index.html','files/js/AiNieeCapture.js'})
        applied=apply_patch(self.root,patch,self.root.parent/(self.root.name+'-patch-applied'))
        self.assertTrue(BuildService.verify(applied['output_path'])['passed'])
        self.assertEqual(json.loads((Path(applied['output_path'])/'data/Map001.json').read_text(encoding='utf-8'))['displayName'],'学院')
        for rel,digest in hashes.items():self.assertEqual(file_hash(self.root/rel),digest)
        self.assertFalse((self.root/'js/AiNieeCapture.js').exists())
        with GameProjectService(project) as service,self.assertRaises((ValueError,FileExistsError)):
            export_patch(service.store,build['output_path'],patch)

    def test_source_and_zip_tampering_are_rejected(self):
        _,_,patch,_=self.build_patch()
        with zipfile.ZipFile(patch) as archive:
            members={name:archive.read(name) for name in archive.namelist()}
        for case in ['payload_hash','traversal','extra_file','case_collision','source_size','bool_version']:
            changed=dict(members)
            manifest=json.loads(changed['rpg-patch.json'])
            if case=='payload_hash':
                changed['files/data/Map001.json']=changed['files/data/Map001.json'].replace('学院'.encode(),'院校'.encode())
            elif case=='traversal':
                changed['files/../outside.json']=changed.pop('files/data/Map001.json')
                manifest['files'][0]['path']='../outside.json'
            elif case=='extra_file':changed['files/extra.json']=b'{}'
            elif case=='source_size':manifest['source_files'][0]['size']=0
            elif case=='bool_version':manifest['version']=True
            else:
                extra=dict(manifest['source_files'][0]);extra['path']=extra['path'].upper()
                manifest['source_files'].append(extra)
            changed['rpg-patch.json']=json.dumps(manifest).encode()
            forged=patch.with_name(patch.stem+'-'+case+'.zip')
            with zipfile.ZipFile(forged,'x') as archive:
                for name,payload in changed.items():archive.writestr(name,payload)
            with self.subTest(case=case),self.assertRaises(ValueError):
                apply_patch(self.root,forged,self.root.parent/(self.root.name+'-rejected-'+case))
        original=(self.root/'data/Items.json').read_bytes()
        (self.root/'data/Items.json').write_text('[]',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'SOURCE_HASH'):
            apply_patch(self.root,patch,self.root.parent/(self.root.name+'-wrong-version'))
        (self.root/'data/Items.json').write_bytes(original)
        (self.root/'new-file.json').write_text('{}',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'SOURCE_FILE_SET_CHANGED'):
            apply_patch(self.root,patch,self.root.parent/(self.root.name+'-extra-source'))
