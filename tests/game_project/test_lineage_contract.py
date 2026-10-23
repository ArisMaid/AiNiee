import copy
import pytest
from ModuleFolders.Service.GameProject.Lineage import game_identity,build_confirmation,has_confirmation


def pair():
    return ({'project_id':'old','engine':'rpgmaker-mv','source_manifest_hash':'a'*64,'game_id':0,'target_language':'zh-CN'},
        {'project_id':'new','engine':'rpgmaker-mv','source_manifest_hash':'b'*64,'game_id':None,'target_language':'zh-CN'})


def test_canonical_game_identity_never_turns_missing_values_into_matches():
    for value in (None,False,True,0,-1,'','  ','0','00','-2','+0',{},1.5):assert game_identity(value)==('','')
    assert game_identity(11)==('11',11)
    assert game_identity(' +0011 ')==('11','+0011')
    assert game_identity('title-A')==('title-A','title-A')


def test_explicit_confirmation_is_required_and_only_changes_target_binding():
    old,new=pair();before=copy.deepcopy((old,new))
    for value in (False,None,1,'true'):
        with pytest.raises(ValueError,match='MIGRATION_LINEAGE_CONFIRMATION_REQUIRED'):
            build_confirmation(old,new,confirmed=value)
    record=build_confirmation(old,new,confirmed=True)
    assert record['method']=='user_confirmed_same_game' and record['old_game_id']==record['new_game_id']==''
    assert (old,new)==before and not has_confirmation(old,new)
    new['migration_lineage']=record
    assert has_confirmation(old,new)
    for version in (True,1.0):
        new['migration_lineage']=dict(record,schema_version=version)
        assert not has_confirmation(old,new)
    new['migration_lineage']=record
    record['unexpected']=True
    assert not has_confirmation(old,new)


def test_manifest_project_engine_and_known_id_bindings_cannot_be_reused():
    old,new=pair();new['migration_lineage']=build_confirmation(old,new,confirmed=True)
    for key,value in [('project_id','other'),('source_manifest_hash','c'*64),('engine','rpgmaker-mz'),
            ('target_language','en'),('game_id',23)]:
        changed=copy.deepcopy(new);changed[key]=value
        assert not has_confirmation(old,changed)
    changed=copy.deepcopy(old);changed['source_manifest_hash']='c'*64
    assert not has_confirmation(changed,new)
    old['game_id']=1;new['game_id']=2
    with pytest.raises(ValueError,match='MIGRATION_PROJECT_MISMATCH'):
        build_confirmation(old,new,confirmed=True)


def test_unbound_or_same_project_is_not_confirmable():
    old,new=pair()
    for key,value in [('source_manifest_hash',''),('source_manifest_hash','x'*64),('project_id',''),('engine','')]:
        invalid=dict(old,**{key:value})
        with pytest.raises(ValueError,match='MIGRATION_LINEAGE_UNBOUND'):
            build_confirmation(invalid,new,confirmed=True)
    with pytest.raises(ValueError,match='MIGRATION_SAME_PROJECT'):
        build_confirmation(old,dict(new,project_id='old'),confirmed=True)
    assert not has_confirmation(None,new)
