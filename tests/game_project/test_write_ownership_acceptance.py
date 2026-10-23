"""Independent physical-address ownership checks, not writer-output snapshots."""
from dataclasses import replace
import copy

from ModuleFolders.Domain.GameProject.Models import Occurrence,TranslationUnit,hash_text
from ModuleFolders.Domain.GameProject.WriteOwnership import ownership_issues


def unit(uid,loc,path='data/Items.json',adapter='rpgmaker-native'):
    return TranslationUnit(uid,'menu','Text',occurrences=(Occurrence(uid+':o',path,loc,hash_text('Text'),adapter_id=adapter),))


def conflicts(units):
    return [i for i in ownership_issues(units) if i.code=='WRITE_OWNERSHIP_CONFLICT']


def test_json_escaped_paths_prefixes_and_distinct_linked_locations():
    a=unit('a',{'pointer':'/a~1b/~0key'})
    b=unit('b',{'pointer':'/a~1b/~0key/child'})
    c=unit('c',{'pointer':'/a~1bc/~0key'})
    issues=conflicts([a,b,c]);assert len(issues)==1
    assert {issues[0].unit_id,issues[0].details['other_unit_id']}=={'a','b'}
    assert not ownership_issues([unit('x',{'pointer':'/name'}),unit('y',{'pointer':'/names'}),
        unit('z',{'pointer':'/1/name'}),unit('q',{'pointer':'/01/name'}),unit('empty',{'pointer':'/'})])
    linked=replace(a,occurrences=a.occurrences+(replace(a.occurrences[0],occurrence_id='a:other',locator={'pointer':'/other'}),))
    assert not ownership_issues([linked])
    duplicate=replace(a,occurrences=a.occurrences+(replace(a.occurrences[0],occurrence_id='a:duplicate'),))
    assert len(conflicts([duplicate]))==1


def test_case_slashes_and_producer_ids_do_not_split_physical_ownership():
    first=unit('first',{'pointer':'/1/name'})
    other=unit('other',{'pointer':'/1/name'},'DATA\\items.JSON','stev')
    issues=conflicts([first,other]);assert len(issues)==1
    assert issues[0].path in {first.occurrences[0].relative_path,other.occurrences[0].relative_path}
    assert not ownership_issues([first,unit('elsewhere',{'pointer':'/1/name'},'data/Actors.json')])


def test_js_exact_nested_partial_intervals_and_touching_ends():
    def js(uid,a,b,**extra):return unit(uid,{'start':a,'end':b,**extra},'js/words.js','js-literal')
    first=js('root',5,20,object_path='Root')
    alias=js('alias',5,20,object_path='Root.words',property_path=['name'])
    nested=js('nested',8,12);partial=js('partial',19,25);touching=js('touch',25,30)
    assert len(conflicts([first,alias,nested,partial,touching]))==3
    assert not ownership_issues([first,js('next',20,25)])
    # Bounds are UTF-8 byte positions supplied by the parser, never UTF-16 ids.
    assert len(conflicts([js('unicode',4,14),js('unicode-alias',4,14)]))==1


def test_real_locator_metadata_does_not_change_physical_ownership():
    json_loc={'pointer':'/events/1/pages/0/list/2/parameters/4',
        'value_codec':'js-string-literal-v1','raw_expression':"'Text'"}
    js_loc={'start':4,'end':20,'expected':'Text','source_sha256':'a'*64,
        'object_path':'words','scope_function':'ShowNews','property_fields':['title'],
        'property_path':['title']}
    assert not ownership_issues([unit('json',json_loc),unit('js',js_loc,'js/news.js','js-literal')])
    assert len(conflicts([unit('json',json_loc),unit('codec-alias',{'pointer':json_loc['pointer']})]))==1
    assert len(conflicts([unit('js',js_loc,'js/news.js','js-literal'),
        unit('js-alias',dict(js_loc,object_path='Other',scope_function='Other'), 'js/news.js','other')]))==1


def test_indexes_match_independent_pairwise_reference_with_out_of_order_claims():
    import random
    rng=random.Random(98130)
    spans=[(rng.randrange(300),rng.randrange(1,45)) for _ in range(350)]
    spans=[(start,start+length) for start,length in spans]
    units=[unit(str(i),{'start':a,'end':b},'js/random.js','js-literal') for i,(a,b) in enumerate(spans)]
    expected={str(i) for i,(a,b) in enumerate(spans) if any(a<d and c<b for c,d in spans[:i])}
    assert {i.unit_id for i in conflicts(units)}==expected
    paths=[tuple(rng.choice(['a','a/b','~c','01','1','long']) for _ in range(rng.randrange(1,5)))
        for _ in range(170)]
    pointer=lambda tokens:'/'+'/'.join(t.replace('~','~0').replace('/','~1') for t in tokens)
    units=[unit(str(i),{'pointer':pointer(tokens)}) for i,tokens in enumerate(paths)]
    expected={str(i) for i,tokens in enumerate(paths) if any(
        tokens[:len(other)]==other or other[:len(tokens)]==tokens for other in paths[:i])}
    assert {i.unit_id for i in conflicts(units)}==expected


def image(uid,rid,box):
    return unit(uid,{'pointer':'region/'+rid,'region_id':rid,'box':box,'source_sha256':'b'*64},
        'img/title.png_','image-region')


def test_confirmed_image_regions_have_one_pixel_owner():
    a=image('a','a'*32,[0,0,40,20]);b=image('b','b'*32,[40,0,40,20])
    assert not ownership_issues([a,b])
    assert len(conflicts([a,image('c','c'*32,[39,1,30,10])]))==1
    assert len(conflicts([a,image('same-id','a'*32,[90,0,40,20])]))==1


def test_malformed_shapes_report_errors_without_guessing_or_mutation():
    malformed=[{'pointer':''},{'pointer':'bad'},{'pointer':'/bad~2key'},{'pointer':'/../bad'},
        {'start':True,'end':3},{'start':0,'end':0},{'start':-1,'end':3},{'start':1,'end':2,'pointer':'/x'},{}]
    for index,loc in enumerate(malformed):
        path='js/words.js' if 'start' in loc else 'data/Items.json'
        u=unit('invalid-'+str(index),loc,path);before=copy.deepcopy(u.to_dict())
        issues=ownership_issues([u]);assert issues and all(i.code=='WRITE_LOCATOR_INVALID' for i in issues)
        assert u.to_dict()==before
    assert ownership_issues([TranslationUnit('ownerless','menu','Text')])[0].code=='WRITE_LOCATOR_INVALID'
    bad=image('bad','a'*32,[0,0,False,10]);assert ownership_issues([bad])[0].code=='WRITE_LOCATOR_INVALID'


def test_deterministic_bounded_diagnostics_and_many_separate_fields():
    rows=[unit(str(i),{'pointer':'/rows/'+str(i)+'/name'}) for i in range(12000)]
    assert not ownership_issues(rows)
    duplicates=[unit('dup-'+str(i),{'pointer':'/same'}) for i in range(80)]
    first=[i.to_dict() for i in ownership_issues(duplicates)]
    assert first==[i.to_dict() for i in ownership_issues(duplicates)] and len(first)<=80
    assert all('Text' not in i['message'] and i['severity']=='error' for i in first)
