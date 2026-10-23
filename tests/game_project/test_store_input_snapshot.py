from contextlib import contextmanager
import pytest
from ModuleFolders.Domain.GameProject.Models import TranslationUnit,Occurrence,TranslationProposal,hash_text
from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore


def make_unit(identity,text):
    return TranslationUnit(identity,'menu',text,occurrences=(Occurrence('o-'+identity,'data/System.json',{'pointer':'/'+identity},hash_text(text)),))


@pytest.fixture
def store(tmp_path):
    with ProjectStore.create(tmp_path/'project',{'project_id':'snapshot-input','engine':'rpgmaker-mz','source_root':str(tmp_path/'source')}) as store:yield store


def test_each_generator_value_is_snapshotted_before_the_generator_continues(store):
    first=make_unit('u1','first source');expected=first.to_dict()
    def values():
        yield first
        first.source_text='late generator edit';first.source_hash=hash_text(first.source_text)
        first.occurrences[0].locator['pointer']='/late'
        yield make_unit('u2','second source')
    result=store.replace_units(values())
    assert result['inserted']==2 and store.unit('u1').to_dict()==expected


def test_invalid_mutated_typed_model_is_rejected_before_entering_any_write(store,monkeypatch):
    first=make_unit('u1','source');first.source_text='tampered without updating hash'
    def unexpected_write():pytest.fail('invalid model reached the write transaction')
    monkeypatch.setattr(store,'_write',unexpected_write)
    with pytest.raises(ValueError,match='source_hash'):store.replace_units([first])


def test_latest_manual_edit_and_lock_are_respected_after_preparation_before_transaction(store,monkeypatch):
    first=make_unit('u1','source');store.replace_units([first]);store.commit(TranslationProposal('u1','initial manual',first.source_hash))
    write=store._write;latest=[]
    @contextmanager
    def another_writer_wins_first():
        with ProjectStore(store.root) as other:
            assert other.commit(TranslationProposal('u1','newest manual',first.source_hash,expected_revision=1)).status=='accepted'
            other.set_locked('u1',True);latest.append(other.translation('u1'))
        with write() as connection:yield connection
    monkeypatch.setattr(store,'_write',another_writer_wins_first)
    store.replace_units([make_unit('u1','new source')])
    result=store.translation('u1')
    assert result['text']=='newest manual' and result['manual_locked'] and result['status']=='stale'
    assert result['revision']==latest[0]['revision']+1
