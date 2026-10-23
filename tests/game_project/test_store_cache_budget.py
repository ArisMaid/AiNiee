import sqlite3
from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore


def test_cache_tuning_keeps_wal_sync_and_foreign_key_guards_and_does_not_persist_a_database_setting(tmp_path):
    root=tmp_path/'project'
    with ProjectStore.create(root,{'project_id':'cache-budget','engine':'rpgmaker-mz','source_root':str(tmp_path/'source')}) as store:
        connection=store._connection
        assert connection.execute('PRAGMA cache_size').fetchone()[0]==-32768
        assert connection.execute('PRAGMA journal_mode').fetchone()[0]=='wal'
        assert connection.execute('PRAGMA synchronous').fetchone()[0]==1
        assert connection.execute('PRAGMA foreign_keys').fetchone()[0]==1
    with sqlite3.connect(root/'project.sqlite3') as raw:
        assert raw.execute('PRAGMA cache_size').fetchone()[0]!=-32768
    with ProjectStore(root) as reopened:
        assert reopened._connection.execute('PRAGMA cache_size').fetchone()[0]==-32768
