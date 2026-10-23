from contextlib import contextmanager
import json
from unittest.mock import patch
import pytest
from ModuleFolders.Domain.GameProject.Models import TranslationUnit,Occurrence,TranslationProposal,Issue,hash_text
from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore,StoreViolation
import ModuleFolders.Service.GameProject.ProjectStore as module


def unit(identity,text=None,context=None):
    text=text or 'source-'+identity
    return TranslationUnit(identity,'menu',text,context=context or {'payload_marker':identity,'nested':[1,{'n':1}]},
        occurrences=(Occurrence('o-'+identity,'data/Items.json',{'pointer':'/'+identity},hash_text(text)),))


@pytest.fixture
def store(tmp_path):
    with ProjectStore.create(tmp_path/'project',{'project_id':'prepared','engine':'rpgmaker-mz','source_root':str(tmp_path/'source')}) as store:yield store


@pytest.mark.parametrize('phase',['insert','unchanged','update'])
def test_normal_unit_serialization_does_not_hold_the_write_transaction(store,phase):
    original=unit('u1');replacement=original
    if phase!='insert':store.replace_units([original])
    if phase=='update':replacement=unit('u1',context={'payload_marker':'updated','nested':[1,{'n':2}]})
    canonical=module._canonical_json;to_dict=Occurrence.to_dict
    incoming_marker=replacement.context['payload_marker']
    def encode(value):
        if isinstance(value,dict) and value.get('payload_marker')==incoming_marker:
            assert not store._connection.in_transaction,'unit context encoded while holding SQLite write transaction'
        return canonical(value)
    def serialize(occurrence):
        assert not store._connection.in_transaction,'occurrence encoded while holding SQLite write transaction'
        return to_dict(occurrence)
    with patch.object(module,'_canonical_json',side_effect=encode),patch.object(Occurrence,'to_dict',serialize):
        summary=store.replace_units([replacement])
    assert summary[{'insert':'inserted','unchanged':'unchanged','update':'updated'}[phase]]==1
    assert store.unit('u1').context==replacement.context


def test_input_is_detached_before_waiting_for_the_database_write_lock(store,monkeypatch):
    value=unit('u1');expected=value.to_dict();write=store._write
    @contextmanager
    def mutate_at_boundary():
        value.source_text='late change';value.context['nested'][1]['n']=999
        value.occurrences[0].locator['pointer']='/late-location'
        with write() as connection:yield connection
    monkeypatch.setattr(store,'_write',mutate_at_boundary)
    store.replace_units([value])
    assert store.unit('u1').to_dict()==expected


def test_legacy_json_formatting_is_semantically_equal_and_is_not_rewritten(store):
    value=unit('u1');store.replace_units([value]);before=store.metadata()
    context=json.dumps(value.context,ensure_ascii=True,indent=3)
    occurrences=json.dumps([value.occurrences[0].to_dict()],ensure_ascii=True,indent=4)
    with store._write() as connection:connection.execute('UPDATE units SET context_json=?,occurrences_json=? WHERE unit_id=?',(context,occurrences,value.unit_id))
    result=store.replace_units([value])
    assert result['unchanged']==1 and result['updated']==0 and store.metadata()==before
    row=store._fetch_one('SELECT context_json,occurrences_json FROM units WHERE unit_id=?',('u1',))
    assert row['context_json']==context and row['occurrences_json']==occurrences


@pytest.mark.parametrize('new_value',[1.0,True])
def test_json_numeric_and_boolean_types_are_not_collapsed_by_python_equality(store,new_value):
    first=unit('u1',context={'n':1});store.replace_units([first]);before=store.metadata()['dataset_revision']
    changed=unit('u1',context={'n':new_value});result=store.replace_units([changed])
    assert result['updated']==1 and result['dataset_revision']==before+1
    assert type(store.unit('u1').context['n']) is type(new_value)


def test_mixed_inserts_obsolete_revival_order_and_locked_stale_translation_are_preserved(store):
    first,second,third=[unit('u'+str(i)) for i in range(1,4)]
    store.replace_units([first,second,third]);store.commit(TranslationProposal('u1','manual text',first.source_hash));store.set_locked('u1',True)
    old=store.translation('u1');changed=unit('u1','changed-source')
    result=store.replace_units([third,unit('u4'),changed,unit('u5')])
    assert [value.unit_id for value in store.units()]==['u1','u3','u4','u5']
    assert (result['inserted'],result['updated'],result['obsolete'],result['unchanged'])==(2,1,1,1)
    translated=store.translation('u1')
    assert translated['manual_locked'] and translated['text']==old['text'] and translated['status']=='stale'
    assert translated['revision']==old['revision']+1
    result=store.replace_units([unit('u5'),second,third,changed,unit('u4')])
    assert result['updated']==1 and [value.unit_id for value in store.units()]==['u1','u2','u3','u4','u5']
    assert store.translation('u1')==translated


def test_completion_failure_rolls_back_units_stale_flags_metadata_issues_and_job(store):
    first=unit('u1');store.replace_units([first]);store.commit(TranslationProposal('u1','locked manual',first.source_hash));store.set_locked('u1',True)
    job=store.create_job('EXTRACT');store.update_job(job['job_id'],run_state='RUNNING');store.update_job(job['job_id'],run_state='COMMITTING')
    with store._write() as connection:
        connection.execute("CREATE TRIGGER refuse_completion BEFORE UPDATE OF run_state ON jobs WHEN NEW.run_state='COMPLETED' BEGIN SELECT RAISE(ABORT,'completion fixture'); END")
    before=(store.metadata(),store.unit('u1').to_dict(),store.translation('u1'),store.issues(),store.get_job(job['job_id']))
    with pytest.raises(StoreViolation,match='completion fixture'):
        store.replace_units([unit('u1','new source'),unit('u2')],
            extraction_metadata={'extraction_complete':True,'profile_id':'changed'},
            extraction_issues=[Issue('FIXTURE_ISSUE','warning','must roll back','u1')],
            extraction_completion={'job_id':job['job_id'],'result':{'fixture':True},'checkpoint':2})
    assert store.unit('u2') is None
    assert (store.metadata(),store.unit('u1').to_dict(),store.translation('u1'),store.issues(),store.get_job(job['job_id']))==before
