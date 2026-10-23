import json
from pathlib import Path
import sqlite3
import tempfile
import pytest

from ModuleFolders.Service.GameProject.OperationJournal import OperationJournal,JournalError


@pytest.fixture
def journal_case():
    base=Path(__file__).resolve().parents[2]/'work/acceptance';base.mkdir(parents=True,exist_ok=True)
    return Path(tempfile.mkdtemp(prefix='operation-journal-',dir=base))/'journal.sqlite3'


def descriptor(**kwargs):
    return dict(operation='validate',algorithm='unit-v1',input_digest='a'*64,item_count=4,**kwargs)


def test_roundtrip_exclusive_and_copies(journal_case):
    expected=descriptor()
    with OperationJournal.create(journal_case,expected) as journal:
        assert journal.completed==0
        rows=[{'unit_id':'a','issues':[]},{'unit_id':'b','issues':[{'code':'X'}]}]
        journal.append(rows);rows[0]['unit_id']='changed'
        assert journal.completed==2
        returned=journal.results();returned[0]['unit_id']='changed-again'
        assert journal.results()[0]['unit_id']=='a'
    with pytest.raises(FileExistsError):OperationJournal.create(journal_case,expected)
    with OperationJournal.open(journal_case,expected) as journal:
        assert journal.completed==2
        journal.append([{'unit_id':'c'},{'unit_id':'d'}])
    with OperationJournal.open(journal_case,expected) as journal:assert journal.completed==4
    changed=dict(expected,input_digest='b'*64)
    with pytest.raises(JournalError,match='JOURNAL_INPUT_CHANGED'):OperationJournal.open(journal_case,changed)


def test_invalid_batch_is_atomic_and_does_not_overwrite(journal_case):
    with OperationJournal.create(journal_case,descriptor()) as journal:
        journal.append([{'unit_id':'a'}])
        for rows in ([{'unit_id':'b'},{'unit_id':'a'}],[{'unit_id':'b'},{'unit_id':'c','number':float('nan')}],
                [{'unit_id':'b'},{'unit_id':'b'}],[{'unit_id':'b',1:'non-string-key'}]):
            with pytest.raises(JournalError):journal.append(rows)
            assert journal.completed==1
        with pytest.raises(JournalError):journal.append([{'unit_id':str(i)} for i in range(4)])
        assert journal.results()==({'unit_id':'a'},)


def test_missing_and_invalid_descriptor_create_nothing(journal_case):
    with pytest.raises(FileNotFoundError):OperationJournal.open(journal_case,descriptor())
    for changed in (dict(descriptor(),item_count=True),dict(descriptor(),input_digest='wrong'),
            dict(descriptor(),operation=''),dict(descriptor(),extra=1)):
        with pytest.raises(JournalError,match='JOURNAL_DESCRIPTOR_INVALID'):
            OperationJournal.create(journal_case,changed)
        assert not journal_case.exists()


def test_truncated_journal_is_retained(journal_case):
    journal_case.write_bytes(b'not-a-sqlite-journal')
    with pytest.raises(JournalError,match='JOURNAL_CORRUPT'):
        OperationJournal.open(journal_case,descriptor())
    assert journal_case.read_bytes()==b'not-a-sqlite-journal'


def test_open_does_not_rewrite_an_unsupported_journal_mode(journal_case):
    with OperationJournal.create(journal_case,descriptor()) as journal:journal.append([{'unit_id':'a'}])
    with sqlite3.connect(journal_case) as db:db.execute('PRAGMA journal_mode=WAL')
    before=journal_case.read_bytes()
    with pytest.raises(JournalError,match='JOURNAL_CORRUPT'):
        OperationJournal.open(journal_case,descriptor())
    assert journal_case.read_bytes()==before


@pytest.mark.parametrize('mutation',[
    "UPDATE journal_items SET payload_json='{}' WHERE idx=0",
    "UPDATE journal_items SET idx=2 WHERE idx=0",
    "UPDATE journal_meta SET schema_version=99",
])
def test_corrupt_rows_or_descriptor_never_get_rebuilt(journal_case,mutation):
    with OperationJournal.create(journal_case,descriptor()) as journal:journal.append([{'unit_id':'a'}])
    with sqlite3.connect(journal_case) as db:db.execute(mutation)
    before=journal_case.read_bytes()
    with pytest.raises(JournalError,match='JOURNAL_CORRUPT'):
        OperationJournal.open(journal_case,descriptor())
    assert journal_case.read_bytes()==before


def test_sql_error_halfway_through_batch_rolls_back_every_new_row(journal_case):
    with OperationJournal.create(journal_case,descriptor()) as journal:
        journal.append([{'unit_id':'old'}])
        with sqlite3.connect(journal_case) as db:
            db.execute("CREATE TRIGGER fail_second BEFORE INSERT ON journal_items WHEN NEW.idx=2 "
                "BEGIN SELECT RAISE(ABORT,'injected write failure'); END")
        with pytest.raises(JournalError,match='JOURNAL_CORRUPT'):
            journal.append([{'unit_id':'first-new'},{'unit_id':'second-new'}])
        with sqlite3.connect(journal_case) as db:
            assert db.execute('SELECT idx FROM journal_items ORDER BY idx').fetchall()==[(0,)]


def test_real_subprocess_exit_after_append_preserves_rows(journal_case):
    import os,subprocess,sys
    code='''import os,sys,json
from ModuleFolders.Service.GameProject.OperationJournal import OperationJournal
journal=OperationJournal.create(sys.argv[1],json.loads(sys.argv[2]))
journal.append([{'unit_id':'persisted','issues':[]}])
os._exit(37)
'''
    result=subprocess.run([sys.executable,'-c',code,str(journal_case),json.dumps(descriptor())],
        cwd=Path(__file__).resolve().parents[2],capture_output=True,timeout=10)
    assert result.returncode==37,result.stderr
    with OperationJournal.open(journal_case,descriptor()) as journal:
        assert journal.results()==({'unit_id':'persisted','issues':[]},)
