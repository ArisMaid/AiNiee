import copy
import json
from ModuleFolders.Service.GameProject.CoverageComparison import compare_extractions
from ModuleFolders.Infrastructure.GameAdapters.ExtractionPointerPool import pack_records
from ModuleFolders.Domain.GameProject.Models import TranslationUnit,Occurrence,hash_text


def test_report_retains_unmapped_record_and_native_codec_without_inventing_locations():
    native=[{'unit_id':'u','kind':'menu','source_text':'表示','source_hash':hash_text('表示'),
        'occurrences':[{'relative_path':'data/CommonEvents.json','locator':{'pointer':'/1/list/0/parameters/4','value_codec':'event-js-json-string-v1'},
            'role':'display','expected_value_hash':hash_text('"表示"')},
            {'relative_path':'data/Other.json','locator':{'pointer':'/name'},'role':'name','expected_value_hash':hash_text('other')}]}]
    backend={'ok':True,'records':[{'text':'::0001 Label','locator':{'virtual':True,'context':['name']},'candidate_pointers':[]},
        {'text':'"表示"','locator':{'group_index':1},'candidate_pointers':['/1/list/0/parameters/4']} ]}
    before=copy.deepcopy((native,backend))
    result=compare_extractions(native,backend,'data/CommonEvents.json')
    assert (native,backend)==before
    assert result['counts']['overlap']==1 and result['counts']['backend_only']==1
    assert result['backend_records']==[{'record_index':0,'text':'::0001 Label','locator':{'virtual':True,'context':['name']}},
        {'record_index':1,'text':'"表示"','locator':{'group_index':1}}]
    row,=result['native_occurrences']
    assert row=={'unit_id':'u','pointer':'/1/list/0/parameters/4','kind':'menu','role':'display',
        'value_codec':'event-js-json-string-v1','source_text':'表示','source_hash':hash_text('表示'),'expected_value_hash':hash_text('"表示"')}
    result['backend_records'][0]['locator']['context'].append('mutate output')
    assert (native,backend)==before


def test_shared_pointer_groups_are_not_expanded_in_record_annotations():
    pointers=[f'/{i}/name' for i in range(2000)]
    backend={'ok':True,**pack_records([{'text':'同文','locator':{'i':i},'candidate_pointers':pointers} for i in range(2000)])}
    result=compare_extractions([],backend,'data/Items.json')
    assert result['counts']['ambiguous']==2000
    assert len(result['backend_records'])==2000
    assert len(result['candidate_pointer_groups'])==1
    assert all(set(row)=={'record_index','text','locator'} for row in result['backend_records'])
    assert len(json.dumps(result,ensure_ascii=False).encode())<1500000


def test_native_model_objects_and_absent_codec_work_without_other_files():
    unit=TranslationUnit(unit_id='one',kind='name',source_text='原文',source_hash=hash_text('原文'),scene_id='s',
        occurrences=(Occurrence(occurrence_id='occ',relative_path='data/Items.json',locator={'pointer':'/1/name'},
            expected_value_hash=hash_text('原文'),role='name',ordinal=0),))
    result=compare_extractions([unit],{'ok':True,'records':[]},'data/Items.json')
    assert result['native_occurrences'][0]['value_codec'] is None
    assert result['native_occurrences'][0]['role']=='name'
    assert result['backend_records']==[]
