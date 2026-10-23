"""Consumer-approved display fields leave Japanese identities/enums untouched."""
import json
from pathlib import Path
import unittest
import test_adapter_acceptance as fixtures
from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
from ModuleFolders.Infrastructure.GameAdapters.RpgMaker.ProfileLoader import load_profile

ROOT=Path(__file__).resolve().parents[2]


class Profile5Fields(unittest.TestCase):
    setUp=fixtures.AdapterAcceptance.setUp
    write=fixtures.AdapterAcceptance.write

    def test_unverified_consumer_fingerprint_refuses_extraction(self):
        import hashlib
        folder=self.root/'js/plugins';folder.mkdir();(folder/'Gaya.js').write_text('// changed consumer',encoding='utf-8')
        profile={'schema_version':1,'id':'consumer-fingerprint','engine':'rpgmaker-mz','json_rules':[],
            'match':{'game_id':1,'fingerprints':{'js/plugins/Gaya.js':hashlib.sha256(b'// reviewed consumer').hexdigest()}},
            'plugin_commands':[{'plugin':'Gaya','command':'show','fields':['text'],'evidence_status':'verified'}]}
        with GameProjectService.create(self.root,self.root.parent/(self.root.name+'-fingerprint')) as service:
            with self.assertRaisesRegex(ValueError,'PROFILE_UNVERIFIED'):service.extract(profile)
            self.assertEqual(service.store.units(),[])
            self.assertEqual(service.store.jobs()[-1]['run_state'],'FAILED')

    def test_two_display_arguments_roundtrip_without_logic_field_changes(self):
        actual=load_profile(ROOT/'Resource/GameProfiles/selenoxia-test-0.141.yaml')
        rules=[r for r in actual['plugin_commands'] if (r['plugin'],r['command']) in
            {('Gaya','show'),('SH_BenriCommands2','AddEstrus')}]
        self.assertEqual(len(rules),2)
        def command(plugin,name,args):return {'code':357,'indent':0,'parameters':[plugin,name,'editor metadata',args]}
        rows=[command('SH_BenriCommands2','AddEstrus',{'text':r'表示\V[1]','num':'3'}),
            command('Gaya','show',{'text':'表示コメント','fontSize':'24','duration':'180'}),
            command('EventReSpawn','MAKE',{'id':'日本イベント','template':'true'}),
            command('FilterControllerMZ','createFilter',{'filterId':'日本識別子','filterType':'blur'}),
            command('AnimationByPoint','SHOW_ANIMATION',{'label':'日本ラベル','id':'1'}),
            command('keke/Keke_VignetteEffect','ビネット表示',{'レイヤー':'レイヤーA1','…挿入位置':'上','内枠-フォーム':'スクエア'})]
        data=json.loads((self.root/'data/Map001.json').read_text(encoding='utf-8'))
        data['events'][1]['pages'][0]['list']=rows+[{'code':0,'indent':0,'parameters':[]}]
        self.write('Map001',data)
        profile={'schema_version':1,'id':'profile5-synthetic','engine':'rpgmaker-mz','json_rules':[], 'plugin_commands':rules}
        project=self.root.parent/(self.root.name+'-profile5')
        with GameProjectService.create(self.root,project) as service:
            service.extract(profile);units=service.store.units()
            targets=[u for u in units if u.kind=='plugin_text']
            self.assertEqual({u.source_text for u in targets},{r'表示\V[1]','表示コメント'})
            translations={u.unit_id:(r'显示\V[1]' if '\\V' in u.source_text else '显示评论') for u in targets}
            self.assertTrue(all(r.status=='accepted' for r in service.import_translations(translations)))
            build=service.build(self.root.parent/(self.root.name+'-profile5-output'),test=True)
            output=json.loads((Path(build['output_path'])/'data/Map001.json').read_text(encoding='utf-8'))
            commands=output['events'][1]['pages'][0]['list']
            self.assertEqual(commands[0]['parameters'][3],{'text':r'显示\V[1]','num':'3'})
            self.assertEqual(commands[1]['parameters'][3],{'text':'显示评论','fontSize':'24','duration':'180'})
            self.assertEqual(commands[2:],data['events'][1]['pages'][0]['list'][2:])
