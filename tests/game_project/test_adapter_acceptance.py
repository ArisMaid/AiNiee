import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from ModuleFolders.Infrastructure.GameAdapters.RpgMaker.Detector import detect_game
from ModuleFolders.Infrastructure.GameAdapters.RpgMaker.JsonExtractor import extract_game
from ModuleFolders.Infrastructure.GameAdapters.RpgMaker.JsonPatcher import patch_json, resolve_pointer
from ModuleFolders.Infrastructure.GameAdapters.RpgMaker.ProfileLoader import select_values


class AdapterAcceptance(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[2] / 'work' / 'acceptance'
        base.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix='adapter-', dir=base))
        (self.root/'data').mkdir(); (self.root/'js').mkdir()
        (self.root/'index.html').write_text('<script src="js/rmmz_core.js"></script>', encoding='utf-8')
        (self.root/'js/rmmz_core.js').write_text('// rmmz_core.js v1.7.0', encoding='utf-8')
        self.write('System', {'gameTitle':'テスト', 'locale':'ja_JP', 'advanced':{'gameId':1},
            'terms':{'save':'セーブ'}, 'variables':['内部名'], 'currencyUnit':'円'})
        self.write('Items', [None, {'id':1,'name':'回復薬','description':'回復する',
            'note':'<logic:保持>', 'iconIndex':4}])
        def c(code, params, indent=0):return {'code':code,'parameters':params,'indent':indent}
        self.write('Map001', {'displayName':'学校', 'data':[1,2,3], 'events':[None, {'id':1,
            'name':'内部イベント', 'pages':[{'list':[
                c(101,['face',0,0,2,'先生']),c(401,[r'\N[1]こんにちは']),
                c(102,[['はい','いいえ'],0,0,2,0]),c(402,[0,'はい']),
                c(401,['はい']),c(402,[1,'いいえ']),c(404,[]),
                c(355,['if (x === "保持") y();']),c(0,[]),
            ]}]}]})
        self.write('RandomTalk', [None, {'message':'元気ですか','voiceId':'内部资源'}])

    def write(self, stem, data):
        (self.root/'data'/f'{stem}.json').write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')

    def test_detect_and_fields(self):
        d=detect_game(self.root)
        self.assertEqual(d['engine'],'rpgmaker-mz')
        result=extract_game(self.root)
        texts=[u.source_text for u in result.units]
        for expected in ['テスト','セーブ','回復薬','回復する','学校','先生',r'\N[1]こんにちは','はい','いいえ']:
            self.assertIn(expected,texts)
        for forbidden in ['内部名','内部イベント','内部资源','元気ですか','<logic:保持>']:
            self.assertNotIn(forbidden,texts)
        self.assertEqual(result.stats['data_json_count'],4)
        self.assertEqual(result.stats['code_counts']['401'],2)
        self.assertEqual([u.unit_id for u in result.units], [u.unit_id for u in extract_game(self.root).units])

    def test_linked_choice_and_source_guard(self):
        result=extract_game(self.root)
        choice=next(u for u in result.units if u.source_text=='はい' and len(u.occurrences)==2)
        path=self.root/choice.occurrences[0].relative_path
        original=path.read_bytes()
        patched=patch_json(original,[(o,'是') for o in choice.occurrences])
        obj=json.loads(patched)
        for o in choice.occurrences:self.assertEqual(resolve_pointer(obj,o.locator['pointer']),'是')
        self.assertEqual(patch_json(original,[(o,choice.source_text) for o in choice.occurrences]),original)
        with self.assertRaises(ValueError):patch_json(patched,[(o,'否') for o in choice.occurrences])

    def test_verified_profile_and_selector_escaping(self):
        profile={'schema_version':1,'id':'test','engine':'rpgmaker-mz','json_rules':[{
            'id':'message','file':'data/RandomTalk.json','selector':'/*/message',
            'value_type':'string','role':'dialogue','evidence_status':'verified'}]}
        result=extract_game(self.root,profile)
        self.assertIn('元気ですか',[u.source_text for u in result.units])
        self.assertNotIn('内部资源',[u.source_text for u in result.units])
        self.assertEqual(select_values({'a/b':{'~key':'值'}},'/a~1b/~0key'),[('/a~1b/~0key','值')])


if __name__=='__main__':unittest.main()
