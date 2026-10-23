import json
from pathlib import Path
import tempfile
import unittest
from ModuleFolders.Infrastructure.GameAdapters.CompatibilityBridge import extract_document
from ModuleFolders.Service.GameProject.CoverageComparison import compare_extractions
from ModuleFolders.Domain.GameProject.Models import TranslationUnit,Occurrence,hash_text

ROOT=Path(__file__).resolve().parents[2]

class CompatibilityAcceptance(unittest.TestCase):
    def check_backend(self,name,path):
        if not path.is_dir():self.skipTest('Optional pinned upstream source is not installed')
        base=ROOT/'work/acceptance';base.mkdir(parents=True,exist_ok=True)
        run=Path(tempfile.mkdtemp(prefix='compat-',dir=base))
        data=[None,{'id':1,'name':'名前','description':'説明','note':'内部'},
              {'id':2,'name':'名前','description':'別の説明','note':''}]
        payload=json.dumps(data,ensure_ascii=False).encode()
        result=extract_document(name,'data/Items.json',payload,run,path)
        self.assertTrue(result['ok']);self.assertFalse(result['capabilities']['write'])
        self.assertIn('名前',[r['text'] for r in result['records']])
        u=TranslationUnit('u','name','名前',occurrences=(Occurrence('o','data/Items.json',
            {'pointer':'/1/name'},hash_text('名前')),))
        comparison=compare_extractions([u],result,'data/Items.json')
        if name=='rpgmtl':self.assertTrue(comparison['ambiguous'])
        else:self.assertEqual(comparison['counts']['overlap'],1)
        elsewhere=TranslationUnit('other','name','名前',occurrences=(Occurrence('else','data/Actors.json',
            {'pointer':'/1/name'},hash_text('名前')),))
        self.assertEqual(compare_extractions([u,elsewhere],result,'data/Items.json')['counts']['native_total'],1)
        self.assertEqual(payload,json.dumps(data,ensure_ascii=False).encode())
        self.assertEqual(list(run.glob('*/cwd/*')),[])

    def test_stev_memory_parser(self):self.check_backend('stev',ROOT/'StevExtraction')
    def test_rpgmtl_duplicate_context(self):self.check_backend('rpgmtl',ROOT/'work/vendor/RPGMTL')
    def test_sextractor_process_parser(self):self.check_backend('sextractor',ROOT/'work/vendor/SExtractor')
