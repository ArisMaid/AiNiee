"""Lossless ambiguity transport must scale with unique pointers, not row products."""
import json
from pathlib import Path
import uuid
import pytest
from ModuleFolders.Domain.GameProject.Models import TranslationUnit,Occurrence,hash_text

ROOT=Path(__file__).resolve().parents[2]


def test_shared_large_arrays_are_bounded_and_remain_ambiguous():
    from ModuleFolders.Infrastructure.GameAdapters.ExtractionPointerPool import pack_records,pointer_lists
    from ModuleFolders.Service.GameProject.CoverageComparison import compare_extractions
    pointers=[f'/{i}/name' for i in range(1997)]
    records=[{'text':'same','locator':{'ordinal':i},'candidate_pointers':pointers} for i in range(2000)]
    packed=dict(ok=True,**pack_records(records))
    assert len(json.dumps(packed).encode())<500000
    resolved=pointer_lists(packed)
    assert len(resolved)==2000 and all(row==pointers for row in resolved)
    assert resolved[0] is resolved[-1]
    assert all(row['candidate_pointers'] is pointers for row in records)
    units=[TranslationUnit('u','name','same',occurrences=(Occurrence('o','data/Items.json',{'pointer':'/1/name'},hash_text('same')),))]
    report=compare_extractions(units,packed,'data/Items.json')
    assert report['counts']=={'native_total':1,'backend_total':2000,'overlap':0,'native_only':1,'backend_only':0,'ambiguous':2000}
    assert len(json.dumps(report).encode())<500000
    for row in report['ambiguous']:
        assert report['candidate_pointer_groups'][row['candidate_pointer_group']]==pointers
        assert row['candidate_pointer_count']==1997


def test_equal_distinct_arrays_share_pool_and_small_legacy_shape_is_preserved():
    from ModuleFolders.Infrastructure.GameAdapters.ExtractionPointerPool import pack_records,pointer_lists
    rows=[{'candidate_pointers':['/1/name','/2/name']},{'candidate_pointers':['/1/name','/2/name']},{'candidate_pointers':[]}]
    original=json.dumps(rows,sort_keys=True)
    assert pack_records(rows)=={'records':rows}
    packed=pack_records(rows,threshold=2)
    assert list(packed['candidate_pointer_groups'])==['g0']
    assert pointer_lists(packed)==[['/1/name','/2/name'],['/1/name','/2/name'],[]]
    assert json.dumps(rows,sort_keys=True)==original


def test_pool_layout_errors_are_rejected(subtests):
    from ModuleFolders.Infrastructure.GameAdapters.ExtractionPointerPool import pointer_lists,pack_records
    good={'records':[{'candidate_pointer_group':'g0'}],'pointer_pool_schema':1,'candidate_pointer_groups':{'g0':['/a','/b']}}
    cases=[dict(good,pointer_pool_schema=True),dict(good,pointer_pool_schema=1.0),dict(good,pointer_pool_schema=2),
        dict(good,candidate_pointer_groups=[]),dict(good,candidate_pointer_groups={'g00':['/a']}),
        dict(good,candidate_pointer_groups={'g0':'/a'}),dict(good,candidate_pointer_groups={'g0':[None]}),
        dict(good,records=[{'candidate_pointer_group':'g1'}]),dict(good,records=[{'candidate_pointer_group':'g0','candidate_pointers':['/a']}]),
        {'records':[{'candidate_pointer_group':'g0'}]}, {'records':[],'pointer_pool_schema':1}]
    for index,case in enumerate(cases):
        with subtests.test(index=index),pytest.raises(ValueError):pointer_lists(case)
    for malformed in ([{'candidate_pointers':'bad'}],[{'candidate_pointers':[None]}],[None]):
        with pytest.raises(ValueError):pack_records(malformed)


def test_real_rpgmtl_repeated_names_fit_existing_transport_limit():
    from ModuleFolders.Infrastructure.GameAdapters.CompatibilityBridge import extract_document,MAX_IO_BYTES
    from ModuleFolders.Infrastructure.GameAdapters.ExtractionPointerPool import pointer_lists
    backend=ROOT/'work/vendor/RPGMTL'
    if not backend.is_dir():pytest.skip('Optional pinned RPGMTL not installed')
    data=[None]+[{'id':i,'name':'同名','description':'同じ説明','note':''} for i in range(1,2001)]
    raw=json.dumps(data,ensure_ascii=False).encode();work=ROOT/'work/acceptance'/('pointer-pool-'+uuid.uuid4().hex)
    result=extract_document('rpgmtl','data/Items.json',raw,work,backend)
    assert len(json.dumps(result,ensure_ascii=False).encode())<MAX_IO_BYTES
    lists=pointer_lists(result)
    assert len(lists)>=2000 and max(map(len,lists))==2000
    assert len(result['candidate_pointer_groups'])==2
    assert all(len(values)==2000 for values in result['candidate_pointer_groups'].values())
