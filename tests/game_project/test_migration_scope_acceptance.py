"""Migration must retain the lexical identity introduced by scoped JS rules."""
from dataclasses import replace
from types import SimpleNamespace
import uuid

from ModuleFolders.Domain.GameProject.Models import Occurrence, TranslationUnit, hash_text
from ModuleFolders.Service.GameProject.MigrationService import canonical_occurrence_identities, plan_migration


def unit(uid, scope=None, *, context=None):
    locator={'object_path':'args','property_path':['same','name'],'start':1,'end':9}
    if scope is not None:locator['scope_function']=scope
    return TranslationUnit(uid,'menu','保存',context=context or {},occurrences=(
        Occurrence(uid+':js','js/words.js',locator,hash_text('保存'),adapter_id='js-literal'),))


def store(units, translated=False):
    project_id=uuid.uuid4().hex
    values={u.unit_id:{'text':'存档','source_hash':u.source_hash,'revision':1} for u in units} if translated else {}
    return SimpleNamespace(units=lambda:units,metadata=lambda:{'project_id':project_id,'engine':'rpgmaker-mz','game_id':'42'},translation=lambda uid:values.get(uid))


def test_scopes_have_distinct_migration_identity_and_legacy_globals_stay_stable():
    a,b=unit('a','A'),unit('b','B')
    assert canonical_occurrence_identities(a)!=canonical_occurrence_identities(b)
    assert canonical_occurrence_identities(a)!=canonical_occurrence_identities(unit('global'))
    assert canonical_occurrence_identities(unit('global'))==frozenset({
        'js/words.js|js-literal|object-path:args:["same","name"]'})
    moved=replace(a,unit_id='moved',occurrences=(replace(a.occurrences[0],locator={
        **a.occurrences[0].locator,'start':100,'end':108}),))
    assert canonical_occurrence_identities(a)==canonical_occurrence_identities(moved)


def test_different_function_never_auto_migrates_same_text():
    plan=plan_migration(store([unit('old','A')],True),store([unit('new','B')]))
    assert plan['matches']==[]
    assert plan['review'][0]['reason']=='SOURCE_TEXT_AT_DIFFERENT_LOCATOR'
    same=plan_migration(store([unit('old','A')],True),store([unit('new','A')]))
    assert len(same['matches'])==1


def test_context_fallback_and_conflicting_or_malformed_scopes_are_not_guessed():
    assert canonical_occurrence_identities(unit('a','A'))==canonical_occurrence_identities(
        unit('b',context={'scope_function':'A'}))
    for scope in [None,False,[],{},'', 'A\n','A'*129]:
        loc={**unit('a').occurrences[0].locator,'scope_function':scope}
        invalid=replace(unit('a'),occurrences=(replace(unit('a').occurrences[0],locator=loc),))
        assert not canonical_occurrence_identities(invalid)
    assert not canonical_occurrence_identities(unit('a','A',context={'scope_function':'B'}))
