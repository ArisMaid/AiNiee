"""A scoped graph must not publish mixed revisions or mutable internal units."""
from dataclasses import replace
from unittest.mock import patch
import pytest
from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
from test_game_batch_preparation import create,preparation,config,references


def test_public_unit_view_cannot_mutate_future_snapshot_reads(tmp_path):
    store,_,_=create(tmp_path)
    try:
        shared=preparation(store.root)
        exposed=shared.unit('u1')
        exposed.context['nested']['value']='poisoned through snapshot lookup'
        assert shared.unit('u1').context['nested']['value']=='canonical'
    finally:store.close()


def test_metadata_and_units_are_one_consistent_read_despite_store_level_writer(tmp_path):
    """ProjectLock does not serialize a direct public ProjectStore writer."""
    store,units,_=create(tmp_path)
    revision=store.metadata()['dataset_revision']; original=ProjectStore.metadata; injected=False
    changed=[replace(units[0],source_text='新来源',source_hash=''),*units[1:]]
    def between_reads(connection):
        nonlocal injected
        result=original(connection)
        if not injected and connection.root==store.root:
            injected=True
            # A separate WAL writer can commit while a read transaction is open.
            with ProjectStore(store.root) as other:other.replace_units(changed)
        return result
    try:
        with patch.object(ProjectStore,'metadata',between_reads):
            try:shared=preparation(store.root)
            except ValueError as exc:
                assert 'REVISION_CONFLICT' in str(exc)
            else:
                assert shared.dataset_revision==revision
                assert shared.unit('u0').source_hash==units[0].source_hash
        assert injected and store.metadata()['dataset_revision']==revision+1
    finally:store.close()


def test_incremental_global_sequence_interleaving_does_not_split_a_single_file_run(tmp_path):
    """replace_units preserves seq: a new unit in an old file may append globally."""
    from ModuleFolders.Service.GameProject.CacheBridge import build_projection
    from ModuleFolders.Service.GameProject.GameBatchRunner import GameBatchRunner
    store,units,_=create(tmp_path,['a','other','a'])
    try:
        other=replace(units[1],occurrences=(replace(units[1].occurrences[0],relative_path='data/Map002.json'),))
        store.replace_units([units[0],other,units[2]])
        project=build_projection(store)
        items=project.get_file('data/Map001.json').items
        assert [item.get_extra('unit_id') for item in items]==['u0','u2']
        batch=GameBatchRunner(items,config(),preparation=preparation(store.root))
        assert [u.unit_id for u in batch.units]==['u0','u2']
        first=GameBatchRunner(items[:1],config(),preparation=batch.preparation)
        assert [row['unit_id'] for row in references(first)['following']]==['u2']
    finally:store.close()
