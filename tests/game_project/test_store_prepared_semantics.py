from dataclasses import replace
import pytest
from ModuleFolders.Domain.GameProject.Models import TranslationUnit,Occurrence,hash_text
from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore


@pytest.fixture
def store(tmp_path):
    with ProjectStore.create(tmp_path/'project',{'project_id':'prepared-semantics','engine':'rpgmaker-mz','source_root':str(tmp_path/'source')}) as store:yield store


def value(context):
    text='source'
    return TranslationUnit('u1','menu',text,context=context,occurrences=(Occurrence('o1','data/Items.json',{'pointer':'/a'},hash_text(text)),))


@pytest.mark.parametrize(('stored','incoming'),[
    ('{"bad":NaN}',{'good':1}),
    ('{"n":Infinity}',{'n':'different type'}),
    ('{"n":[NaN,0]}',{'n':[]}),
])
def test_nonfinite_stored_json_is_refused_even_in_a_different_or_unvisited_branch(store,stored,incoming):
    store.replace_units([value({'n':1})])
    with store._write() as connection:connection.execute('UPDATE units SET context_json=? WHERE unit_id=?',(stored,'u1'))
    before=store.metadata()
    with pytest.raises(ValueError):store.replace_units([value(incoming)])
    assert store.metadata()==before
    assert store._fetch_one('SELECT context_json FROM units WHERE unit_id=?',('u1',))['context_json']==stored


def test_occurrence_array_order_remains_a_meaningful_graph_change(store):
    first=value({'n':1});second=Occurrence('o2','data/Items.json',{'pointer':'/b'},first.source_hash,ordinal=1)
    first=replace(first,occurrences=(first.occurrences[0],second))
    store.replace_units([first]);before=store.metadata()['dataset_revision']
    changed=replace(first,occurrences=tuple(reversed(first.occurrences)))
    result=store.replace_units([changed])
    assert result['updated']==1 and result['dataset_revision']==before+1
    assert [occurrence.occurrence_id for occurrence in store.unit('u1').occurrences]==['o2','o1']


@pytest.mark.parametrize('column',['kind','source_text'])
def test_blob_in_a_text_column_is_refused_instead_of_being_overwritten(store,column):
    store.replace_units([value({'n':1})])
    with store._write() as connection:
        connection.execute('UPDATE units SET '+column+'=? WHERE unit_id=?',(b'invalid text scalar','u1'))
    before=store.metadata()
    with pytest.raises((TypeError,ValueError)):store.replace_units([value({'n':2})])
    assert store.metadata()==before
    assert store._fetch_one('SELECT '+column+' FROM units WHERE unit_id=?',('u1',))[column]==b'invalid text scalar'
