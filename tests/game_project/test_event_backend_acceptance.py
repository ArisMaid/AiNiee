"""Real isolated third-party writers receive encoded event string values."""
import json,unittest
from pathlib import Path
import test_adapter_acceptance as fixtures
from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
from ModuleFolders.Service.GameProject.BackendRoutes import configure_route
from ModuleFolders.Service.GameProject.BuildService import BuildService,file_hash
from ModuleFolders.Infrastructure.GameAdapters.RpgMaker.JsonPatcher import semantic_differences

ROOT=Path(__file__).resolve().parents[2]
BACKENDS={'stev':ROOT/'StevExtraction','rpgmtl':ROOT/'work/vendor/RPGMTL','sextractor':ROOT/'work/vendor/SExtractor'}


class EventBackendAcceptance(unittest.TestCase):
    setUp=fixtures.AdapterAcceptance.setUp
    write=fixtures.AdapterAcceptance.write

    def check(self,backend):
        folder=BACKENDS[backend]
        if not folder.is_dir():self.skipTest('Pinned optional backend not installed')
        path=self.root/'data/Map001.json';data=json.loads(path.read_text(encoding='utf-8-sig'))
        commands=data['events'][1]['pages'][0]['list'];index=len(commands)
        commands.append({'code':122,'indent':0,'parameters':[1938,1938,0,4,'"日本語"']})
        path.write_bytes(b'\xef\xbb\xbf'+json.dumps(data,ensure_ascii=False,indent=2).replace('\n','\r\n').encode())
        original_hash=file_hash(path)
        profile={'schema_version':3,'id':'backend-codec','engine':'rpgmaker-mz','required_features':['event_js_string_v1'],
            'event_literals':[{'id':'word','file':'data/Map001.json','scene_ids':['Map001:event:1:page:0'],
                'variable_id':1938,'role':'display_keyword','codec':'event-js-json-string-v1','evidence_status':'verified'}]}
        with GameProjectService.create(self.root,self.root.parent/(self.root.name+'-typed-'+backend)) as service:
            service.extract(profile)
            unit=next(u for u in service.store.units() if u.occurrences[0].locator.get('value_codec'))
            target='中文";globalThis.pwned=1;//'
            self.assertEqual(service.import_translations({unit.unit_id:target})[0].status,'accepted')
            route=configure_route(service.store,'data/Map001.json',backend,folder)
            self.assertEqual(route['proof']['changed_occurrences'],1)
            build=service.build(self.root.parent/(self.root.name+'-typed-output'),test=True)
            self.assertTrue(BuildService.verify(build['output_path'])['passed'])
            written=json.loads((Path(build['output_path'])/'data/Map001.json').read_text(encoding='utf-8-sig'))
            actual=written['events'][1]['pages'][0]['list'][index]['parameters'][4]
            self.assertEqual(json.loads(actual),target)
            self.assertEqual(semantic_differences(data,written),{f'/events/1/pages/0/list/{index}/parameters/4'})
            row=next(r for r in build['files'] if r['path']=='data/Map001.json')
            self.assertEqual(row['writer']['id'],backend)
        self.assertEqual(file_hash(path),original_hash)

    def test_stev_event_literal(self):self.check('stev')
    def test_rpgmtl_event_literal(self):self.check('rpgmtl')
    def test_sextractor_event_literal(self):self.check('sextractor')


if __name__=='__main__':unittest.main()
