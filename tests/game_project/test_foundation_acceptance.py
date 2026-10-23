"""Codex-owned independent acceptance tests. Artifacts are deliberately retained."""
import json
import tempfile
import unittest
from pathlib import Path

from ModuleFolders.Domain.GameProject.Models import (
    Issue, Occurrence, TranslationUnit, TranslationProposal, hash_text,
)
from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
from ModuleFolders.Service.GameProject.PathGuard import safe_join, assert_disjoint, atomic_write


class FoundationAcceptance(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[2] / 'work' / 'acceptance'
        base.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix='foundation-', dir=base))

    def make_unit(self, text='保存'):
        return TranslationUnit('u1', 'menu', text, scene_id='menu', occurrences=(
            Occurrence('o1', 'data/System.json', {'pointer': '/terms/save'}, hash_text(text)),
        ))

    def test_model_roundtrip(self):
        u = self.make_unit()
        restored = TranslationUnit.from_dict(json.loads(json.dumps(u.to_dict())))
        self.assertEqual(restored, u)
        with self.assertRaises(ValueError):
            TranslationUnit('bad', 'menu', 'abc', source_hash='f' * 64)

    def test_two_connections_compare_revision_atomically(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        with ProjectStore.create(self.root/'concurrent',{'project_id':'concurrent',
                'engine':'rpgmaker-mz','source_root':str(self.root/'source')}) as first:
            unit=self.make_unit();first.replace_units([unit])
            barrier=threading.Barrier(2)
            def submit(text):
                with ProjectStore(first.root) as connection:
                    barrier.wait(timeout=3)
                    return connection.commit(TranslationProposal(unit.unit_id,text,unit.source_hash)).status
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures=[pool.submit(submit,text) for text in ('甲','乙')]
                self.assertEqual(sorted(f.result() for f in futures),['accepted','conflict'])
            self.assertEqual(first.translation(unit.unit_id)['revision'],1)

    def test_contention_and_schema_rejection(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading,sqlite3
        root=self.root/'contention'
        with ProjectStore.create(root,{'project_id':'contention','engine':'rpgmaker-mz',
                'source_root':str(self.root/'source')}) as first:
            unit=self.make_unit();first.replace_units([unit]);barrier=threading.Barrier(8)
            def submit(index):
                with ProjectStore(root) as connection:
                    barrier.wait(timeout=5)
                    return connection.commit(TranslationProposal(unit.unit_id,'译文'+str(index),unit.source_hash)).status
            with ThreadPoolExecutor(max_workers=8) as pool:
                results=list(pool.map(submit,range(8)))
            self.assertEqual(results.count('accepted'),1);self.assertEqual(results.count('conflict'),7)
            self.assertEqual(first.translation(unit.unit_id)['revision'],1)
        for version in ['999','true','0']:
            with sqlite3.connect(root/'project.sqlite3') as db:db.execute('UPDATE metadata SET value=? WHERE key=?',(version,'schema_version'))
            with self.subTest(version=version),self.assertRaisesRegex(ValueError,'schema_version'):
                ProjectStore(root)

    def test_frozen_snapshot_is_readonly_and_does_not_create_wal(self):
        from ModuleFolders.Service.GameProject.BuildService import file_hash
        live=self.root/'live';frozen=self.root/'frozen';frozen.mkdir()
        with ProjectStore.create(live,{'project_id':'snapshot','engine':'rpgmaker-mz','source_root':str(self.root/'source')}) as store:
            store.replace_units([self.make_unit()]);store.snapshot(frozen/'project.sqlite3')
        before=file_hash(frozen/'project.sqlite3')
        with ProjectStore(frozen,readonly=True) as snapshot:
            self.assertEqual(len(snapshot.units()),1)
            with self.assertRaisesRegex(ValueError,'Frozen input snapshots'):
                snapshot.update_metadata({'unexpected':'write'})
        self.assertEqual(file_hash(frozen/'project.sqlite3'),before)
        self.assertFalse((frozen/'project.sqlite3-wal').exists())

    def test_path_scope_and_no_overwrite(self):
        for rel in ['../outside', 'C:/other/file', '//server/share', 'data/a:stream', 'CON.txt', 'a/../b']:
            with self.subTest(rel=rel), self.assertRaises(ValueError):
                safe_join(self.root, rel)
        with self.assertRaises(ValueError):
            assert_disjoint(self.root, self.root / 'nested')
        assert_disjoint(self.root / 'a', self.root / 'b')
        target = safe_join(self.root, '合法 路径/file.txt')
        atomic_write(target, b'original')
        with self.assertRaises((ValueError, FileExistsError)):
            atomic_write(target, b'other')
        self.assertEqual(target.read_bytes(), b'original')

    def test_transaction_revision_lock_and_restart(self):
        store = ProjectStore.create(self.root / 'project', {
            'project_id': 'p1', 'source_root': str(self.root / 'source'), 'engine': 'rpgmaker-mz',
        })
        self.addCleanup(store.close)
        unit = self.make_unit()
        store.replace_units([unit])
        result = store.commit(TranslationProposal('u1', '存档', unit.source_hash,
            job_id='j1', request_item_id='r1'))
        self.assertEqual(result.status, 'accepted')
        self.assertEqual(store.translation('u1')['text'], '存档')
        self.assertEqual(store.translation('u1')['revision'], 1)
        self.assertEqual(store.commit(TranslationProposal('u1', '存档', unit.source_hash,
            job_id='j1', request_item_id='r1')).status, 'duplicate')
        self.assertEqual(store.commit(TranslationProposal('u1', '旧结果', unit.source_hash)).status, 'conflict')
        store.set_locked('u1', True)
        self.assertEqual(store.commit(TranslationProposal('u1', '覆盖', unit.source_hash, 1)).status, 'locked')
        self.assertEqual(store.translation('u1')['text'], '存档')
        store.snapshot(self.root / 'snapshot.sqlite3')
        store.close()
        reopened = ProjectStore(self.root / 'project')
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.translation('u1')['text'], '存档')
        self.assertTrue(reopened.translation('u1')['manual_locked'])
        self.assertGreaterEqual(reopened.metadata()['content_revision'], 2)

    def test_invalid_proposal_preserves_accepted_translation(self):
        with ProjectStore.create(self.root / 'project', {'project_id': 'p2',
                'source_root': str(self.root / 'source'), 'engine': 'rpgmaker-mz'}) as store:
            unit = self.make_unit()
            store.replace_units([unit])
            store.commit(TranslationProposal('u1', '存档', unit.source_hash))
            result = store.commit(TranslationProposal('u1', '损坏', unit.source_hash, 1),
                issues=[Issue('TOKEN_MISMATCH', 'error', 'missing token', 'u1')])
            self.assertEqual(result.status, 'rejected')
            self.assertEqual(store.translation('u1')['text'], '存档')
            self.assertEqual(store.translation('u1')['revision'], 1)
            self.assertTrue(store.proposals())


if __name__ == '__main__':
    unittest.main()
