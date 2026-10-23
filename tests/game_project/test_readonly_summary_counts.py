"""Reading legacy cached statistics reports the current graph without repair writes."""
from test_external_tasks import project


def test_summary_derives_counts_without_rewriting_legacy_metadata(project):
    store=project.store
    store.update_metadata({'extraction_stats':{'unit_count':0,'occurrence_count':0,'data_json_count':4}})
    before=store.metadata();units=store.units()
    summary=project.summary()
    assert summary['stats']['unit_count']==len(units)>0
    assert summary['stats']['occurrence_count']==sum(len(u.occurrences) for u in units)>0
    assert summary['stats']['data_json_count']==4
    assert store.metadata()==before
