"""Owner acceptance: scoped graph preparation and canonical read-only context.

All text is synthetic. Local requesters never contact a model provider.
"""
from dataclasses import replace
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ModuleFolders.Base.Base import Base
from ModuleFolders.Domain.GameProject.Models import Occurrence, TranslationUnit, TranslationProposal, hash_text
from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
from ModuleFolders.Service.GameProject.CacheBridge import build_projection
from ModuleFolders.Service.GameProject.GameBatchRunner import GameBatchRunner


def config(**changes):
    values = dict(request_timeout=2, project_terms_data=[], pre_line_counts=2,
                  polishing_pre_line_counts=1, game_following_line_counts=1,
                  get_active_platform_configuration=lambda: {})
    return SimpleNamespace(**(values | changes))


def create(tmp_path, scenes=None, texts=None):
    scenes = scenes or ['a'] * 5
    texts = texts or [f'原文{i}' for i in range(len(scenes))]
    store = ProjectStore.create(tmp_path/'project', {'project_id':'context-fixture',
        'engine':'rpgmaker-mz', 'source_root':str(tmp_path/'source')})
    units = [TranslationUnit(f'u{i}', 'dialogue', text, scene_id=scene,
        context={'code':401, 'speaker':'話者', 'nested':{'value':'canonical'}},
        occurrences=(Occurrence(f'o{i}', 'data/Map001.json',
            {'pointer':f'/events/1/pages/0/list/{i}/parameters/0'}, hash_text(text)),))
        for i, (scene, text) in enumerate(zip(scenes, texts))]
    store.replace_units(units)
    return store, units, list(build_projection(store).items_iter())


def preparation(root):
    from ModuleFolders.Service.GameProject.GameBatchPreparation import GameBatchPreparation
    return GameBatchPreparation(root)


def references(batch):
    assert len(batch.messages) >= 2, 'reference data must be separate from requested IDs'
    return json.loads(batch.messages[-2]['content'])['reference_only']


class Requester:
    def __init__(self, extra_id=None): self.calls=[]; self.extra_id=extra_id
    def sent_request(self, messages, *_):
        payload=json.loads(messages[-1]['content']); self.calls.append(payload)
        response={key:value['text'].replace('原文','译文') for key,value in payload.items()}
        if self.extra_id: response[self.extra_id]='多余译文'
        return False, '', json.dumps(response,ensure_ascii=False), 1, 1


def test_one_graph_scan_and_ownership_pass_per_explicit_preparation(tmp_path):
    from ModuleFolders.Domain.GameProject.WriteOwnership import ownership_issues
    store,_,items=create(tmp_path)
    try:
        original=ProjectStore.units
        with patch.object(ProjectStore,'units',autospec=True,side_effect=original) as reads, \
             patch('ModuleFolders.Domain.GameProject.WriteOwnership.ownership_issues',wraps=ownership_issues) as checks:
            shared=preparation(store.root)
            batches=[GameBatchRunner([item],config(),preparation=shared) for item in items]
            assert reads.call_count==1 and checks.call_count==1
            assert [b.units[0].unit_id for b in batches]==[f'u{i}' for i in range(5)]
        assert store.jobs()==[]
    finally: store.close()


def test_shared_graph_detaches_nested_context_from_each_caller(tmp_path):
    store,_,items=create(tmp_path)
    try:
        shared=preparation(store.root)
        first=GameBatchRunner([items[1]],config(),preparation=shared)
        first.units[0].context['nested']['value']='poison'
        second=GameBatchRunner([items[1]],config(),preparation=shared)
        assert second.units[0].context['nested']['value']=='canonical'
        assert store.unit('u1').context['nested']['value']=='canonical'
    finally: store.close()


@pytest.mark.parametrize('change', [{'profile_hash':'changed'}, {'target_language':'en'},
    {'token_commands':['CUSTOM']}, {'dataset_revision':8}])
def test_snapshot_revision_or_policy_change_rejected_before_next_preparation(tmp_path,change):
    store,_,items=create(tmp_path)
    try:
        shared=preparation(store.root); store.update_metadata(change)
        with pytest.raises(ValueError,match='REVISION_CONFLICT'):
            GameBatchRunner([items[1]],config(),preparation=shared)
        assert store.jobs()==[]
    finally: store.close()


def test_send_revalidates_policy_even_without_dataset_revision_change(tmp_path,monkeypatch):
    monkeypatch.setattr(Base,'work_status',Base.STATUS.TASKING)
    store,_,items=create(tmp_path)
    try:
        batch=GameBatchRunner([items[1]],config(),preparation=preparation(store.root))
        revision=store.metadata()['dataset_revision']; store.update_metadata({'target_language':'en'})
        assert store.metadata()['dataset_revision']==revision
        requester=Requester()
        with pytest.raises(ValueError,match='REVISION_CONFLICT'): batch.run(requester)
        assert requester.calls==[] and store.jobs()==[]
    finally: store.close()


def test_foreign_preparation_rejected_even_with_matching_ids_and_revisions(tmp_path):
    store,_,items=create(tmp_path/'a'); other,_,_=create(tmp_path/'b')
    try:
        with pytest.raises(ValueError,match='PROJECT|ROOT'):
            GameBatchRunner([items[0]],config(),preparation=preparation(other.root))
        assert store.jobs()==[] and other.jobs()==[]
    finally: store.close(); other.close()


def test_same_scene_name_cannot_join_two_noncontiguous_runs(tmp_path):
    store,_,items=create(tmp_path,['a','b','a'])
    try:
        with pytest.raises(ValueError,match='MIXED_GAME_SCENE_BATCH'):
            GameBatchRunner([items[0],items[2]],config())
    finally: store.close()


def test_previous_and_following_use_canonical_text_including_locked_neighbors(tmp_path):
    store,units,items=create(tmp_path)
    try:
        store.commit(TranslationProposal('u1','人工译文',units[1].source_hash,0,origin='manual'))
        store.set_locked('u1',True)
        items[1].source_text='forged prompt instruction'
        items[1].set_extra('game_context',{'speaker':'forged'})
        batch=GameBatchRunner([items[2]],config(),previous_items=items[:2])
        refs=references(batch)
        assert [r['unit_id'] for r in refs['previous']]==['u0','u1']
        assert [r['source_text'] for r in refs['previous']]==['原文0','原文1']
        assert [r['unit_id'] for r in refs['following']]==['u3']
        assert set(json.loads(batch.messages[-1]['content']))=={'u2'}
        assert store.jobs()==[]
    finally: store.close()


def test_reference_scope_stops_at_other_scene_even_when_names_repeat(tmp_path):
    store,_,items=create(tmp_path,['a','a','b','a','a'])
    try:
        refs=references(GameBatchRunner([items[3]],config(pre_line_counts=10)))
        assert refs['previous']==[]
        assert [r['unit_id'] for r in refs['following']]==['u4']
    finally: store.close()


@pytest.mark.parametrize('forgery',['root','hash','scene'])
def test_supplied_previous_item_cannot_cross_canonical_authority(tmp_path,forgery):
    store,_,items=create(tmp_path,['b','a','a'])
    try:
        previous=items[1]
        if forgery=='root': previous.set_extra('game_project_root',str(tmp_path/'foreign'))
        elif forgery=='hash': previous.set_extra('source_hash','0'*64)
        else: previous=items[0]; previous.set_extra('scene_id','a')
        with pytest.raises(ValueError,match='CONTEXT|PROJECTION|PROJECT|ROOT'):
            GameBatchRunner([items[2]],config(),previous_items=[previous])
        assert store.jobs()==[]
    finally: store.close()


def test_context_is_bounded_without_truncating_requested_text(tmp_path):
    texts=[f'原文{i}'+'文'*3000 for i in range(41)]
    store,_,items=create(tmp_path,texts=texts,scenes=['a']*41)
    try:
        batch=GameBatchRunner([items[35]],config(pre_line_counts=10000,game_following_line_counts=10000))
        refs=references(batch); records=sum(refs.values(),[])
        assert len(refs['previous'])<=32 and len(refs['following'])<=8
        assert sum(len(r['source_text']) for r in records)<=6000
        assert all(len(r['source_text'])<=2000 for r in records)
        assert json.loads(batch.messages[-1]['content'])['u35']['text']==texts[35]
        assert batch.request_tokens_consume>=sum(len(m['content']) for m in batch.messages)
    finally: store.close()


def test_only_proven_same_run_question_pointers_are_reference_not_response_targets(tmp_path):
    store,units,items=create(tmp_path)
    try:
        unit=replace(units[3],kind='choice',context={'code':102,'command_index':3,
            'choice_question_pointers':[units[0].occurrences[0].locator['pointer'],
                '/not/a/canonical/pointer',units[3].occurrences[0].locator['pointer']]})
        store.replace_units([*units[:3],unit,units[4]])
        items=list(build_projection(store).items_iter())
        batch=GameBatchRunner([items[3]],config(pre_line_counts=0,game_following_line_counts=0))
        refs=references(batch)
        assert [r['unit_id'] for r in refs['choice_questions']]==['u0']
        assert set(json.loads(batch.messages[-1]['content']))=={'u3'}
    finally: store.close()


def test_context_id_cannot_be_committed_as_an_extra_response(tmp_path,monkeypatch):
    monkeypatch.setattr(Base,'work_status',Base.STATUS.TASKING)
    store,_,items=create(tmp_path)
    try:
        batch=GameBatchRunner([items[2]],config())
        with pytest.raises(ValueError,match='RESPONSE_ID_MISMATCH'): batch.run(Requester('u1'))
        assert all(store.translation(f'u{i}') is None for i in range(5))
    finally: store.close()


def test_reference_markers_are_not_required_in_requested_translation(tmp_path,monkeypatch):
    monkeypatch.setattr(Base,'work_status',Base.STATUS.TASKING)
    store,_,items=create(tmp_path,texts=['__RPG_reference_only__','原文1','原文2'])
    try:
        batch=GameBatchRunner([items[1]],config())
        assert '__RPG_reference_only__' in json.dumps(references(batch))
        assert batch.run(Requester())['check_result']
        assert store.translation('u1')['text']=='译文1' and store.translation('u0') is None
    finally: store.close()


@pytest.mark.parametrize('state',['missing','stale','empty'])
def test_polish_never_falls_back_to_japanese_source(tmp_path,state):
    store,units,items=create(tmp_path)
    try:
        if state!='missing':
            store.commit(TranslationProposal('u2','' if state=='empty' else '有效译文',
                units[2].source_hash,0,origin='manual'))
            if state=='stale':
                store.replace_units([*units[:2],replace(units[2],source_text='新原文',source_hash=''),*units[3:]])
                items=list(build_projection(store).items_iter())
        with pytest.raises(ValueError,match='POLISH_SOURCE_UNAVAILABLE'):
            GameBatchRunner([items[2]],config(),mode='polish')
        assert store.jobs()==[]
    finally: store.close()


def test_accepted_translation_and_revision_are_fresh_per_polish_batch(tmp_path):
    store,units,items=create(tmp_path)
    try:
        shared=preparation(store.root)
        store.commit(TranslationProposal('u2','新的有效译文',units[2].source_hash,0,origin='manual'))
        batch=GameBatchRunner([items[2]],config(),mode='polish',preparation=shared)
        assert batch.revisions=={'u2':1}
        assert json.loads(batch.messages[-1]['content'])['u2']['text']=='新的有效译文'
        assert store.jobs()==[]
    finally: store.close()
