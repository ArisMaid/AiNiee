"""Codex acceptance for feature gates and retained pre-upgrade backups."""
import importlib
import json
import sqlite3
import unittest
from contextlib import closing
from unittest.mock import patch
import test_foundation_acceptance as fixtures
from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
from ModuleFolders.Service.GameProject.BuildService import file_hash


class FormatV2Acceptance(unittest.TestCase):
    setUp=fixtures.FoundationAcceptance.setUp
    make_unit=fixtures.FoundationAcceptance.make_unit

    def create(self,name='project'):
        return ProjectStore.create(self.root/name,{'project_id':name,'engine':'rpgmaker-mz',
            'source_root':str(self.root/'source')})

    def legacy(self,name='legacy'):
        store=self.create(name);store.replace_units([self.make_unit()]);root=store.root;store.close()
        with closing(sqlite3.connect(root/'project.sqlite3')) as db:
            with db:
                db.execute('UPDATE metadata SET value=? WHERE key=?',('1','schema_version'))
                db.execute("DELETE FROM metadata WHERE key='required_features'")
        return root

    def test_fresh_gate_legacy_readonly_and_ordinary_writes(self):
        with self.create() as store:
            self.assertEqual(store.metadata()['schema_version'],2)
            self.assertEqual(store.metadata()['required_features'],[])
            for key,value in [('schema_version',1),('required_features',['literal_tokens_v1'])]:
                with self.subTest(key=key),self.assertRaises(ValueError):store.update_metadata({key:value})
            with self.assertRaises(ValueError):store.update_metadata({'token_literals':['bad']})
        root=self.legacy();before=file_hash(root/'project.sqlite3')
        with ProjectStore(root,readonly=True) as store:self.assertEqual(store.metadata()['schema_version'],1)
        self.assertEqual(file_hash(root/'project.sqlite3'),before)
        with ProjectStore(root) as store:
            store.update_metadata({'ordinary':'data'});store.replace_units([self.make_unit()])
            self.assertEqual(store.metadata()['schema_version'],1)
        self.assertFalse((root/'migrations').exists())

    def test_upgrade_backup_is_exact_pre_mutation_and_features_are_monotonic(self):
        root=self.legacy()
        with ProjectStore(root) as store:
            before=store.metadata();unit=self.make_unit();unit.context={'value_constraints':{'exclude_values':['sentinel']}}
            store.replace_units([unit],extraction_metadata={'token_literals':['[word]'],'token_policy_id':'rpgmaker-v3'})
            meta=store.metadata();self.assertEqual(meta['schema_version'],2)
            self.assertEqual(meta['required_features'],['display_value_constraints_v1','literal_tokens_v1'])
            self.assertEqual(meta['dataset_revision'],before['dataset_revision']+1)
            backups=list((root/'migrations/v1-to-v2').glob('*/project.sqlite3'));self.assertEqual(len(backups),1)
            with ProjectStore(backups[0].parent,readonly=True) as backup:
                self.assertEqual(backup.metadata(),before)
                self.assertFalse(backup.unit(unit.unit_id).context)
            store.replace_units([self.make_unit()],extraction_metadata={'token_literals':[],'token_policy_id':'rpgmaker-v2'})
            self.assertEqual(store.metadata()['required_features'],meta['required_features'])

    def test_upgrade_failure_rolls_back_units_and_format_retains_backup(self):
        root=self.legacy()
        with ProjectStore(root) as store:
            before=store.metadata();old=store.unit('u1').to_dict();module=importlib.import_module(ProjectStore.__module__)
            actual=module._write_metadata_value
            def fail(connection,key,value):
                if key=='token_literals':raise OSError('injected metadata failure')
                return actual(connection,key,value)
            with patch.object(module,'_write_metadata_value',side_effect=fail):
                with self.assertRaisesRegex(OSError,'injected metadata failure'):
                    store.replace_units([self.make_unit('改写')],extraction_metadata={'token_literals':['[word]']})
            self.assertEqual(store.metadata(),before);self.assertEqual(store.unit('u1').to_dict(),old)
            self.assertEqual(len(list((root/'migrations/v1-to-v2').glob('*/project.sqlite3'))),1)

    def test_backup_failure_aborts_and_retry_preserves_both_attempts(self):
        root=self.legacy()
        with ProjectStore(root) as store:
            before=store.metadata();unit=self.make_unit('改写')
            module=importlib.import_module(ProjectStore.__module__)
            with patch.object(module.sqlite3,'connect',side_effect=sqlite3.OperationalError('injected backup failure')):
                with self.assertRaisesRegex(ValueError,'cannot back up'):
                    store.replace_units([unit],extraction_metadata={'token_literals':['[word]']})
            self.assertEqual(store.metadata(),before);self.assertEqual(store.unit('u1').source_text,'保存')
            store.replace_units([unit],extraction_metadata={'token_literals':['[word]']})
            self.assertEqual(store.metadata()['schema_version'],2)
            self.assertEqual(len(list((root/'migrations/v1-to-v2').glob('*/project.sqlite3'))),2)

    def test_long_open_writer_rechecks_gate_and_rolls_back(self):
        with self.create() as store:
            with sqlite3.connect(store.root/'project.sqlite3') as db:
                db.execute('UPDATE metadata SET value=? WHERE key=?',(json.dumps(['future_feature']),'required_features'))
            with self.assertRaises(ValueError):store.update_metadata({'forbidden':'write'})
            self.assertNotIn('forbidden',store.metadata())
            with self.assertRaises(ValueError):ProjectStore(store.root)
            with sqlite3.connect(store.root/'project.sqlite3') as db:
                db.execute('UPDATE metadata SET value=? WHERE key=?',('[]','required_features'))
            store.update_metadata({'recovered':True});self.assertTrue(store.metadata()['recovered'])

    def test_new_metadata_rejects_unknown_features_and_bool_schema(self):
        for i,fields in enumerate([{'schema_version':True},{'schema_version':1},
                {'required_features':['future']},{'required_features':'literal_tokens_v1'},
                {'required_features':['literal_tokens_v1','literal_tokens_v1']},{'token_literals':['bad']}]):
            with self.subTest(fields=fields),self.assertRaises(ValueError):
                ProjectStore.create(self.root/str(i),dict(project_id='x',engine='rpgmaker-mz',
                    source_root=str(self.root/'source'),**fields))

    def test_readonly_rejects_live_wal_and_commit_revalidates_changed_grammar(self):
        from ModuleFolders.Domain.GameProject.Models import TranslationProposal
        from ModuleFolders.Service.GameProject.TranslationCommitter import TranslationCommitter
        with self.create() as store:
            unit=self.make_unit('通常[word]');store.replace_units([unit])
            old=TranslationCommitter(store)
            with self.assertRaisesRegex(ValueError,'pending WAL'):ProjectStore(store.root,readonly=True)
            unit.context={'value_constraints':{'exclude_values':['sentinel']}}
            store.replace_units([unit],extraction_metadata={'token_literals':['[word]'],'token_policy_id':'rpgmaker-v3'})
            # Old cached validator allows the stripped marker; the store must not.
            self.assertFalse(old.policy.validate(unit.source_text,'中文'))
            rejected=old.submit(TranslationProposal(unit.unit_id,'中文',unit.source_hash))
            self.assertEqual(rejected.status,'rejected')
            self.assertTrue(any(i.code=='TOKEN_MISMATCH' for i in rejected.issues))
            rejected=store.commit(TranslationProposal(unit.unit_id,'sentinel',unit.source_hash))
            self.assertEqual(rejected.status,'rejected')
            self.assertTrue(any(i.code=='RESERVED_DISPLAY_VALUE' for i in rejected.issues))
            self.assertEqual(store.commit(TranslationProposal(unit.unit_id,'中文[word]',unit.source_hash)).status,'accepted')


if __name__=='__main__':unittest.main()
