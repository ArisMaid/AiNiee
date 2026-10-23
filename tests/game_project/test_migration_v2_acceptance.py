"""Independent version-delta, identity and reconciliation acceptance."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import copy,tempfile,uuid

import pytest

from ModuleFolders.Domain.GameProject.Models import Occurrence,TranslationUnit,TranslationProposal,hash_text
from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
from ModuleFolders.Service.GameProject.MigrationService import plan_migration,apply_migration,canonical_occurrence_identities


def unit(uid,text,pointer,*,scene='common_event:1',speaker='Alice',context=None):
    return TranslationUnit(uid,'dialogue',text,scene_id=scene,
        context={'code':401,'speaker':speaker,**(context or {})},occurrences=(Occurrence(uid+':o','data/CommonEvents.json',
        {'pointer':pointer},hash_text(text),role='dialogue'),))


def store(units,*,pid=None,meta=None,translated=False,locked=()):
    if pid is None:pid=uuid.uuid4().hex
    metadata={'engine':'rpgmaker-mz','game_id':'42','target_language':'zh-CN','project_id':pid,**(meta or {})}
    values={u.unit_id:{'text':'译文'+u.source_text,'source_hash':u.source_hash,'revision':1} for u in units} if translated else {}
    for uid in locked:values[uid]={'manual_locked':True,'revision':0}
    return SimpleNamespace(units=lambda:list(units),unit=lambda uid:next((u for u in units if u.unit_id==uid),None),
        metadata=lambda:dict(metadata),translation=lambda uid:values.get(uid),_values=values,_metadata=metadata)


def test_missing_project_id_is_unverified_even_with_equal_game_ids():
    item=unit('old','Alpha','/1/list/5/parameters/0')
    result=plan_migration(store([item],pid='',translated=True),store([replace(item,unit_id='new')]))
    assert not result['identity']['verified'] and result['matches']==[]


def delta():
    old=[unit('old-a','Alpha','/1/list/5/parameters/0'),unit('old-b','Beta','/1/list/6/parameters/0'),
        unit('old-m','Old','/1/list/20/parameters/0'),unit('old-o','Orphan','/1/list/30/parameters/0'),
        unit('old-c','Locked','/1/list/40/parameters/0')]
    new=[unit('new-n','Inserted','/1/list/5/parameters/0'),unit('new-a','Alpha','/1/list/6/parameters/0'),
        unit('new-b','Beta','/1/list/7/parameters/0'),unit('new-m','Changed','/1/list/20/parameters/0'),
        unit('new-c','Locked','/1/list/40/parameters/0')]
    return old,new


def test_shifted_occupied_locations_and_five_way_reconciliation():
    old,new=delta();a=store(old,pid='old',translated=True);b=store(new,pid='new',locked=['new-c'])
    before=copy.deepcopy(a._values);plan=plan_migration(a,b)
    assert plan['identity']['verified']
    assert {(m['old_unit_id'],m['new_unit_id'],m['match_method']) for m in plan['matches']}=={
        ('old-a','new-a','unique_scene_anchor'),('old-b','new-b','unique_scene_anchor')}
    counts=plan['stats']['reconciliation_counts']
    assert counts=={'reused':2,'new':1,'modified':1,'orphaned':1,'conflict':1}
    report=plan['reconciliation'];assert set(report)==set(counts)
    assert report['new'][0]['new_unit_id']=='new-n'
    assert report['modified'][0]['old_unit_id']=='old-m'
    assert report['orphaned'][0]['old_unit_id']=='old-o'
    assert report['conflict'][0]['reason']=='TARGET_LOCKED'
    targets=[r['new_unit_id'] for k in ['reused','new','modified','conflict'] for r in report[k]]
    assert sorted(targets)==sorted(u.unit_id for u in new)
    assert a._values==before


@pytest.mark.parametrize('change',[{'engine':'rpgmaker-mv'},{'game_id':'43'},{'target_language':'en'}])
def test_different_project_identity_refuses_before_reuse(change):
    u=unit('old','Alpha','/1/list/1/parameters/0');v=replace(u,unit_id='new')
    with pytest.raises(ValueError,match='MIGRATION_PROJECT_MISMATCH'):
        plan_migration(store([u],translated=True),store([v],meta=change))


def test_unknown_identity_and_same_project_are_not_automatic_reuse():
    u=unit('old','Alpha','/1/list/1/parameters/0');v=replace(u,unit_id='new')
    for missing in ['',None,False,0,-1,'0','00','-1','+0']:
        p=plan_migration(store([u],translated=True,meta={'game_id':missing}),store([v]))
        assert not p['identity']['verified'] and not p['matches']
        assert p['reconciliation']['conflict'][0]['reason']=='PROJECT_IDENTITY_UNVERIFIED'
    with pytest.raises(ValueError,match='MIGRATION_SAME_PROJECT'):
        plan_migration(store([u],pid='same'),store([v],pid='same'))
    with pytest.raises(ValueError,match='MIGRATION_TARGET_LANGUAGE_UNSUPPORTED'):
        plan_migration(store([u],meta={'target_language':'en'}),store([v],meta={'target_language':'en'}))


def test_moved_anchors_require_context_and_bidirectional_uniqueness():
    a=unit('a','Alpha','/1/list/1/parameters/0')
    moved=unit('new','Alpha','/1/list/9/parameters/0')
    assert len(plan_migration(store([a],translated=True),store([moved]))['matches'])==1
    for changed in [replace(moved,scene_id='common_event:2'),replace(moved,context={'code':401,'speaker':'Bob'}),
            replace(moved,kind='menu'),replace(moved,context={'code':405})]:
        assert not plan_migration(store([a],translated=True),store([changed]))['matches']
    duplicate=replace(a,unit_id='b',occurrences=(replace(a.occurrences[0],occurrence_id='b:o',locator={'pointer':'/1/list/2/parameters/0'}),))
    assert not plan_migration(store([a,duplicate],translated=True),store([moved]))['matches']
    other_new=replace(moved,unit_id='new-2',occurrences=(replace(moved.occurrences[0],occurrence_id='new-2:o',locator={'pointer':'/1/list/10/parameters/0'}),))
    assert not plan_migration(store([a],translated=True),store([moved,other_new]))['matches']


def test_partial_and_duplicate_occurrence_sets_are_not_locations():
    a=unit('a','Alpha','/1/list/1/parameters/0');valid=a.occurrences[0]
    invalid=replace(valid,occurrence_id='bad',locator={'start':1,'end':5})
    assert not canonical_occurrence_identities(replace(a,occurrences=(valid,invalid)))
    assert not canonical_occurrence_identities(replace(a,occurrences=(valid,replace(valid,occurrence_id='dup'))))
    target=replace(a,unit_id='b',occurrences=(replace(valid,role='choice'),))
    assert not plan_migration(store([a],translated=True),store([target]))['matches']


def test_overlapping_owners_cannot_be_rescued_by_anchor_phase():
    a=unit('a','Alpha','/1/list/1/parameters/0');b=replace(a,unit_id='new-a')
    other=unit('new-b','Beta','/1/list/1/parameters/0')
    p=plan_migration(store([a],translated=True),store([b,other]))
    assert not p['matches'] and p['stats']['reconciliation_counts']['conflict']==2
    linked=replace(b,occurrences=b.occurrences+(replace(b.occurrences[0],occurrence_id='linked',locator={'pointer':'/1/list/2/parameters/0'}),))
    other=unit('new-b','Beta','/1/list/2/parameters/0')
    assert not plan_migration(store([a],translated=True),store([linked,other]))['matches']


def test_js_array_indexes_can_move_but_named_field_and_scope_are_retained():
    def js(uid,index,field='name',scope='Words'):
        path=['rows',index,field]
        return TranslationUnit(uid,'menu','Alpha',scene_id=scope,context={'scope_function':scope,'object_path':'args','property_path':path},
            occurrences=(Occurrence(uid+':js','js/words.js',{'object_path':'args','scope_function':scope,'property_path':path},hash_text('Alpha'),adapter_id='js-literal'),))
    p=plan_migration(store([js('old',0)],translated=True),store([js('new',1)]))
    assert len(p['matches'])==1 and p['matches'][0]['match_method']=='unique_scene_anchor'
    for candidate in [js('new',1,'id'),js('new',1,scope='Other')]:
        assert not plan_migration(store([js('old',0)],translated=True),store([candidate]))['matches']


def test_unused_policy_addition_is_compatible_but_new_interpretation_is_not():
    a=unit('a','Alpha','/1/list/1/parameters/0');b=replace(a,unit_id='b')
    p=plan_migration(store([a],translated=True),store([b],meta={'token_commands':['R']}))
    assert len(p['matches'])==1 and p['matches'][0]['match_method']=='exact_location'
    for source,meta in [(r'Alpha\R',{'token_commands':['R']}),('Alpha[word]',{'token_literals':['[word]']})]:
        a=unit('a',source,'/1/list/1/parameters/0');b=replace(a,unit_id='b')
        assert not plan_migration(store([a],translated=True),store([b],meta=meta))['matches']
    a=unit('a',r'Alpha\N[1]','/1/list/1/parameters/0');b=replace(a,unit_id='b')
    old=store([a],translated=True);old._values['a']['text']=r'译文\N[2]'
    assert not plan_migration(old,store([b]))['matches']
    a=unit('a','One\nTwo','/1/list/1/parameters/0');b=replace(a,unit_id='b',context={'code':401,'value_constraints':{'preserve_newlines':True}})
    old=store([a],translated=True);old._values['a']['text']='一\n二\n三'
    assert not plan_migration(old,store([b]))['matches']


def test_real_sqlite_apply_replans_rejects_duplicates_and_keeps_old_store():
    base=Path(__file__).resolve().parents[2]/'work/acceptance';base.mkdir(parents=True,exist_ok=True)
    root=Path(tempfile.mkdtemp(prefix='migration-v2-',dir=base));old,new=delta()
    with ProjectStore.create(root/'old',{'engine':'rpgmaker-mz','game_id':'42','project_id':'old','source_root':str(root/'source-old')}) as a, \
            ProjectStore.create(root/'new',{'engine':'rpgmaker-mz','game_id':'42','project_id':'new','source_root':str(root/'source-new')}) as b:
        a.replace_units(old);b.replace_units(new)
        for u in old:assert a.commit(TranslationProposal(u.unit_id,'译文'+u.source_text,u.source_hash)).status=='accepted'
        before={u.unit_id:a.translation(u.unit_id) for u in old};plan=plan_migration(a,b)
        # No locks here: both moved units plus the unchanged unit are reusable.
        assert len(plan['matches'])==3
        forged=copy.deepcopy(plan);forged['matches'].append(copy.deepcopy(plan['matches'][0]))
        with pytest.raises(ValueError,match='MIGRATION_PLAN_INVALID'):apply_migration(a,b,forged)
        assert all(b.translation(u.unit_id) is None for u in new)
        forged=copy.deepcopy(plan);forged['matches'][0]['text']='伪造'
        with pytest.raises(ValueError,match='MIGRATION_PLAN_INVALID'):apply_migration(a,b,forged)
        assert all(r.status=='accepted' for r in apply_migration(a,b,plan))
        assert b.translation('new-a')['text']=='译文Alpha' and b.translation('new-b')['text']=='译文Beta'
        assert b.translation('new-n') is None and b.translation('new-m') is None
        assert {u.unit_id:a.translation(u.unit_id) for u in old}==before


def test_old_translation_is_rechecked_between_submissions(monkeypatch):
    import ModuleFolders.Service.GameProject.MigrationService as migration
    old=[unit('old-a','Alpha','/1/list/1/parameters/0'),unit('old-b','Beta','/1/list/2/parameters/0')]
    new=[replace(u,unit_id='new-'+u.unit_id) for u in old]
    a=store(old,translated=True);b=store(new);plan=plan_migration(a,b);submitted=[]
    class ConcurrentWriter:
        def __init__(self,store):pass
        def submit(self,proposal):
            submitted.append(proposal.unit_id)
            a._values['old-b']['text']='同时更新的旧译文'
            return SimpleNamespace(status='accepted')
    monkeypatch.setattr(migration,'TranslationCommitter',ConcurrentWriter)
    with pytest.raises(ValueError,match='MIGRATION_SOURCE_STALE'):apply_migration(a,b,plan)
    assert submitted==['new-old-a']
