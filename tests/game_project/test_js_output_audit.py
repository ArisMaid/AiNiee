import pytest
from ModuleFolders.Infrastructure.GameAdapters.JsWorker.JsBridge import _call


def span(source, spelling):
    start = source.index(spelling)
    return len(source[:start].encode()), len(source[:start + len(spelling)].encode())


def audit(source, output, rows):
    return _call({'operation':'audit','source':source,'output':output,'replacements':rows})


def test_ast_and_exact_unchanged_bytes_allow_only_literal_spelling_variation():
    source = 'const emoji="😀";\r\nconst UI={a:\'同文\',b:"同文"}; // keep\r\n'
    a,b = span(source,"'同文'")
    c,d = span(source,'"同文"')
    output = source.replace("'同文'", "'\\u7532'").replace('"同文"','"乙"')
    rows = [{'start':a,'end':b,'expected':'同文','text':'甲'}, {'start':c,'end':d,'expected':'同文','text':'乙'}]
    result = audit(source,output,rows)
    assert result['approved_count']==2
    assert [(r['start'],r['end']) for r in result['output_spans']]==[(a,b),(c,d)]
    first = result['output_spans'][0]
    assert output.encode()[first['output_start']:first['output_end']] == b"'\\u7532'"


@pytest.mark.parametrize('mutation', ['comment','whitespace','other-value','other-quote','operator','wrong-value','template'])
def test_unapproved_or_semantically_wrong_changes_rejected(mutation):
    source = 'const UI={a:"原文", id:"keep"}; // original\n'
    start,end = span(source,'"原文"')
    output = source.replace('"原文"','"译文"')
    if mutation=='comment': output=output.replace('original','changed')
    if mutation=='whitespace': output=output.replace('const UI','const  UI')
    if mutation=='other-value': output=output.replace('"keep"','"other"')
    if mutation=='other-quote': output=output.replace('"keep"',"'keep'")
    if mutation=='operator': output=output.replace('const UI','let UI')
    if mutation=='wrong-value': output=output.replace('"译文"','"wrong"')
    if mutation=='template': output=output.replace('"译文"','`译文`')
    with pytest.raises(ValueError): audit(source,output,[{'start':start,'end':end,'expected':'原文','text':'译文'}])


@pytest.mark.parametrize('invalid', ['duplicate','bool','float','inside','wrong-source'])
def test_invalid_span_or_expected_value_rejected(invalid):
    source='const UI={a:"原文"};'
    start,end=span(source,'"原文"');row={'start':start,'end':end,'expected':'原文','text':'译文'}
    rows=[row]
    if invalid=='duplicate': rows.append(dict(row))
    if invalid=='bool': row['start']=True
    if invalid=='float': row['start']=float(start)
    if invalid=='inside': row['start']+=1
    if invalid=='wrong-source': row['expected']='another'
    with pytest.raises(ValueError):audit(source,source.replace('原文','译文'),rows)


def test_noop_does_not_allow_comment_edits_or_evaluate_source():
    source='globalThis.doNotExecute(); const UI={a:"原文"}; // keep\n'
    assert audit(source,source,[])['approved_count']==0
    with pytest.raises(ValueError):audit(source,source.replace('keep','edit'),[])
