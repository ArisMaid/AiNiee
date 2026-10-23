import copy
import pytest
from ModuleFolders.Service.GameProject.MigrationLedger import reconstruct_receipts


def data():
    matches=[{'old_unit_id':'o'+str(i),'new_unit_id':'n'+str(i),'text':'译文'+str(i),'source_hash':'a'*64,
        'expected_revision':i,'match_method':'exact_location','extra':{'items':[i]}} for i in range(3)]
    rows=[{'proposal_id':10+i,'job_id':'operation','unit_id':m['new_unit_id'],'target_language':'zh-CN',
        'origin':'migration','status':'accepted','text':m['text'],'expected_source_hash':m['source_hash'],
        'expected_revision':m['expected_revision'],'revision':m['expected_revision']+1,
        'request_item_id':'project:'+m['old_unit_id']+':'+m['new_unit_id'],
        'metadata':{'old_project_id':'project','old_unit_id':m['old_unit_id'],'new_unit_id':m['new_unit_id']}}
        for i,m in enumerate(matches)]
    return matches,rows


def restore(matches,rows):return reconstruct_receipts(matches,rows,delivery_job_id='operation',old_project_id='project')


def test_receipt_prefix_is_independent_of_input_and_unrelated_deliveries():
    matches,rows=data();before=copy.deepcopy((matches,rows))
    actual=restore(matches,[{'job_id':'other'},rows[0]])
    assert actual['completed']==1 and actual['results'][0]['revision']==1
    actual['pending_matches'][0]['extra']['items'].append(99)
    assert (matches,rows)==before
    assert restore(matches,[])['completed']==0
    assert restore(matches,rows)['pending_matches']==[]


def test_reordered_holey_duplicate_or_nonaccepted_receipts_are_never_skipped(subtests):
    matches,rows=data()
    for bad in ([rows[1]],[rows[0],rows[0]],list(reversed(rows)),rows+[rows[0]]):
        with subtests.test(bad=bad),pytest.raises(ValueError,match='MIGRATION_LEDGER_INVALID'):restore(matches,bad)
    for status in ('rejected','late','duplicate',None):
        with subtests.test(status=status):
            bad=copy.deepcopy(rows[:1]);bad[0]['status']=status
            with pytest.raises(ValueError,match='MIGRATION_LEDGER_REJECTED'):restore(matches,bad)


def test_receipts_check_every_binding_and_strict_numeric_type(subtests):
    matches,rows=data()
    changes={'proposal_id':[True,0,-1,'10'],'expected_revision':[False,0.0,'0',1],
        'revision':[True,1.0,'1',2],'target_language':['ja',None],'origin':['manual',None],
        'unit_id':['n1',None],'text':['different',None],'expected_source_hash':['b'*64,None],
        'request_item_id':['different',None],'metadata':[{},dict(rows[0]['metadata'],extra=True)]}
    for key,values in changes.items():
        for value in values:
            with subtests.test(key=key,value=value):
                bad=copy.deepcopy(rows[:1]);bad[0][key]=value;before=copy.deepcopy(bad)
                with pytest.raises(ValueError,match='MIGRATION_LEDGER_INVALID'):restore(matches,bad)
                assert bad==before


def test_receipt_reconstruction_refuses_invalid_frozen_match_input(subtests):
    matches,rows=data()
    changes={'old_unit_id':['',None],'new_unit_id':['',None],'text':['','   ',None],
        'source_hash':['A'*64,'a'*63,None],'expected_revision':[True,-1,'0'],
        'match_method':['fuzzy',None,[]]}
    for key,values in changes.items():
        for value in values:
            with subtests.test(key=key,value=value):
                bad=copy.deepcopy(matches);bad[0][key]=value
                with pytest.raises(ValueError,match='MIGRATION_LEDGER_INVALID'):restore(bad,rows)
    with pytest.raises(ValueError,match='MIGRATION_LEDGER_INVALID'):restore(matches,[None])
    with pytest.raises(ValueError,match='MIGRATION_LEDGER_INVALID'):restore(matches+[matches[0]],[])
