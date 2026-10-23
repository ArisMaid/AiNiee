"""Structural question ownership follows command101's immediate401/102 path.

No inference from text or branch names. These documents are synthetic.
"""
import json
import pytest
from ModuleFolders.Infrastructure.GameAdapters.RpgMaker.JsonExtractor import extract_document


PREFIX='/events/1/pages/0/list'


def c(code,parameters=None,indent=0):
    return dict(code=code,parameters=parameters or [],indent=indent)


def choices(commands):
    document={'events':[None,{'id':1,'pages':[{'list':commands}]}]}
    result=extract_document('data/Map001.json',json.dumps(document,ensure_ascii=False).encode(),{})
    return result,[u for u in result.units if u.kind=='choice']


def test_blank_speaker_message_block_proves_all_immediate_question_lines():
    result,options=choices([c(101,['',0,0,2,'']),c(401,['問い一']),c(401,['問い二']),
        c(102,[['はい','いいえ']]),c(402,[0,'はい']),c(402,[1,'いいえ']),c(404)])
    expected=[PREFIX+'/1/parameters/0',PREFIX+'/2/parameters/0']
    assert len(options)==2
    for option in options:
        assert option.context['choice_question_pointers']==expected
        assert len(option.occurrences)==2
    assert len(result.units)==4


@pytest.mark.parametrize('separator',[c(108,['comment']),c(0),c(111,[0]),c(355,['script']),c(402,[0,'branch'])])
def test_intervening_command_does_not_assign_prior_message_as_owned_question(separator):
    _,options=choices([c(101,['',0,0,2,'話者']),c(401,['前の文章']),separator,c(102,[['選択']])])
    assert not options[0].context.get('choice_question_pointers')


@pytest.mark.parametrize('prefix',[
    [c(401,['孤立した文章'])],
    [c(105),c(405,['スクロール'])],
    [c(101,['',0,0,2,'話者'])],
    [c(101,['',0,0,2,'話者'],1),c(401,['階層違い'],1)],
    [c(101,['',0,0,2,'話者']),c(401,['階層違い'],1)],
])
def test_unproven_or_malformed_message_does_not_acquire_question_ownership(prefix):
    _,options=choices(prefix+[c(102,[['選択']],0)])
    assert not options[0].context.get('choice_question_pointers')


def test_nested_choices_keep_distinct_questions_and_write_occurrences():
    _,options=choices([c(101,['',0,0,2,'外側']),c(401,['外の問い']),c(102,[['外選択']]),
        c(402,[0,'外選択']),c(101,['',0,0,2,'内側'],1),c(401,['内の問い'],1),
        c(102,[['内選択']],1),c(402,[0,'内選択'],1),c(404,[],1),c(404)])
    by_text={u.source_text:u for u in options}
    assert by_text['外選択'].context['choice_question_pointers']==[PREFIX+'/1/parameters/0']
    assert by_text['内選択'].context['choice_question_pointers']==[PREFIX+'/5/parameters/0']
    assert [o.locator['pointer'] for o in by_text['外選択'].occurrences]==[
        PREFIX+'/2/parameters/0/0',PREFIX+'/3/parameters/1']
    assert [o.locator['pointer'] for o in by_text['内選択'].occurrences]==[
        PREFIX+'/6/parameters/0/0',PREFIX+'/7/parameters/1']
