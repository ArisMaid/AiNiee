import copy
import pytest
from ModuleFolders.Infrastructure.GameAdapters.RpgmtlJsMapping import TrackedJs,encode_translation,map_js_groups


def setup(bom=0):
    source=TrackedJs('const emoji="😀";const UI={a:\'同文\',b:"同文"};')
    positions=[];items=[]
    for spelling in ("'同文'",'"同文"'):
        start=str(source).index(spelling);end=start+len(spelling)
        positions.append((bom+len(str(source)[:start].encode()),bom+len(str(source)[:end].encode()),spelling))
        items.append(source[start+1:end-1].replace("\\'","'").replace('\\\n','\n'))
    groups=[['group',*items]]
    changes=[{'start':a,'end':b,'source_literal':old,'text':new} for (a,b,old),new in zip(positions,('甲','乙'))]
    return source,groups,changes


@pytest.mark.parametrize('bom',[0,3])
def test_origin_byte_spans_and_per_occurrence_ids(bom):
    source,groups,changes=setup(bom)
    before=copy.deepcopy(changes)
    result=map_js_groups(source,'js/words.js',groups,changes,bom=bom)
    assert changes==before
    assert len({row['global_id'] for row in result['found']})==2
    assert [(row['start'],row['end']) for row in result['found']]==[(c['start'],c['end']) for c in changes]
    built=result['project_strings'];assert all(row[1] is None for row in built['strings'].values())
    assert [row[1] for row in built['files']['js/words.js'][0][1:]]==[encode_translation('甲'),encode_translation('乙')]


def test_encoding_controls_quotes_backslashes_and_astral():
    text='a\'"\\\r\n\t\0\u2028😀'
    wire=encode_translation(text)
    assert len(wire)%6==0 and wire.isascii()
    assert bytes.fromhex(wire.replace('\\u','')).decode('utf-16-be')==text
    assert encode_translation('')==''
    with pytest.raises(ValueError):encode_translation('\ud800')


@pytest.mark.parametrize('bad',['lost','forged-root','duplicate','bad-spelling','bool','overlap','virtual'])
def test_no_guessing_or_invalid_mapping(bad):
    source,groups,changes=setup()
    if bad=='lost':groups[0][1]=str(groups[0][1])
    if bad=='forged-root':
        other,other_groups,_=setup();groups[0][1]=other_groups[0][1]
    if bad=='duplicate':groups[0].append(groups[0][1])
    if bad=='bad-spelling':changes[0]['source_literal']='"wrong"'
    if bad=='bool':changes[0]['start']=True
    if bad=='overlap':changes.append(dict(changes[0],start=changes[0]['start']+1))
    if bad=='virtual':groups[0][0]='::plugin'
    with pytest.raises(ValueError,match='RPGMTL_JS_MAPPING_INVALID'):map_js_groups(source,'js/words.js',groups,changes)


def test_transform_preserves_whole_provenance_without_forging_subslice():
    root=TrackedJs("'a\\\nb'");item=root[1:-1].replace('\\\n','\n')
    assert str(item)=='a\nb' and item.start==1 and item.end==5 and item.origin is root.origin
    assert type(item[:1]) is str and type(root[0]) is str
