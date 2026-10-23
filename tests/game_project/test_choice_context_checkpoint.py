"""Question provenance must not reuse pre-provenance extraction checkpoints."""
from dataclasses import replace
import importlib
from unittest.mock import patch
import pytest
from test_extraction_recovery import extraction_case, cancel_at
from ModuleFolders.Infrastructure.GameAdapters.Registry import RpgMakerAdapter
from ModuleFolders.Infrastructure.GameAdapters.RpgMaker import JsonExtractor


def test_old_algorithm_checkpoint_is_refused_without_reparsing_or_dataset_change(extraction_case):
    service,_,profile=extraction_case
    module=importlib.import_module('ModuleFolders.Service.GameProject.ExtractionService')
    with patch.object(module,'ALGORITHM','rpg-extraction-event-write-guard-v2'):
        old=cancel_at(service,profile,2)
    before=service.store.metadata()
    with patch.object(JsonExtractor,'extract_document',side_effect=AssertionError('old checkpoint reparsed')):
        with pytest.raises(ValueError,match='EXTRACTION_CHECKPOINT_VERSION_CHANGED'):
            service.resume_extract(old)
    assert service.store.metadata()==before and service.store.units()==[]


def test_reextract_upgrades_readonly_context_without_changing_ids_or_accepted_text(extraction_case):
    service,_,profile=extraction_case
    service.extract(profile)
    current=service.store.units()
    legacy=[replace(u,context={k:v for k,v in u.context.items() if k!='choice_question_pointers'}) for u in current]
    service.store.replace_units(legacy)
    choice=next(u for u in legacy if u.kind=='choice')
    assert service.import_translations({choice.unit_id:'批准的选项'})[0].status=='accepted'
    service.store.set_locked(choice.unit_id,True)
    before=service.store.translation(choice.unit_id)
    revision=service.store.metadata()['dataset_revision']
    service.extract(profile)
    assert service.store.metadata()['dataset_revision']==revision+1
    assert service.store.metadata()['adapter_version']==RpgMakerAdapter.version=='1.1.0'
    assert service.store.translation(choice.unit_id)==before
    assert [u.unit_id for u in service.store.units()]==[u.unit_id for u in current]
    updated=service.store.unit(choice.unit_id)
    assert updated.context['choice_question_pointers']==['/events/1/pages/0/list/1/parameters/0']
    assert updated.occurrences==choice.occurrences and updated.source_hash==choice.source_hash
