"""Explicit JSON layers and fixed text boundaries in approved JS literals."""
from __future__ import annotations
import json
import re
from .Models import hash_text

FEATURE = 'js_nested_json_v1'
AFFIX_FEATURE = 'js_fixed_affixes_v1'


def text_affixes(value):
    """Exact source-only boundaries for one approved AST string node."""
    if (not isinstance(value,dict) or set(value)!={'prefix','suffix'} or
            any(not isinstance(value[k],str) or len(value[k])>256 or
                '\n' in value[k] or '\r' in value[k] for k in ('prefix','suffix')) or
            not (value['prefix'] or value['suffix'])):
        raise ValueError('JS_TEXT_AFFIXES_INVALID')
    return dict(value)


def source_span_body(expected,affixes=None):
    if not isinstance(expected,str):raise ValueError('JS_TEXT_AFFIX_SOURCE_INVALID')
    if affixes is None:return expected
    parts=text_affixes(affixes);prefix=parts['prefix'];suffix=parts['suffix']
    if (len(prefix)+len(suffix)>len(expected) or not expected.startswith(prefix) or
            not expected.endswith(suffix)):
        raise ValueError('JS_TEXT_AFFIX_SOURCE_MISMATCH')
    end=len(expected)-len(suffix) if suffix else len(expected)
    return expected[len(prefix):end]


def literal_path(value):
    if (not isinstance(value,list) or not 1<=len(value)<=32 or any(
            not ((type(part) is int and part>=0) or (isinstance(part,str) and 0<len(part)<=512)) for part in value)):
        raise ValueError('JS_LITERAL_PATH_INVALID')
    return list(value)


def pointer_tokens(pointer):
    if not isinstance(pointer,str) or len(pointer)>4096 or (pointer and not pointer.startswith('/')) or re.search(r'~(?![01])',pointer):
        raise ValueError('JS_JSON_POINTER_INVALID')
    return tuple(p.replace('~1','/').replace('~0','~') for p in pointer[1:].split('/')) if pointer else ()


def normalize_steps(steps):
    if not isinstance(steps,list) or not 1<=len(steps)<=16:
        raise ValueError('JS_JSON_STEPS_INVALID')
    for step in steps:pointer_tokens(step)
    return list(steps)


def ownership_tokens(steps):
    result=[]
    for step in normalize_steps(steps):
        result.append(('decode',''))
        result.extend(('key',token) for token in pointer_tokens(step))
    return tuple(result)


def script_span(value):
    if (not isinstance(value,dict) or type(value.get('start')) is not int or type(value.get('end')) is not int or
            not 0<=value['start']<value['end'] or value.get('node_kind') not in ('literal','template-part') or
            not isinstance(value.get('id'),str) or not re.fullmatch('[A-Za-z0-9_-]{1,128}',value['id']) or
            not isinstance(value.get('source_sha256'),str) or not re.fullmatch('[a-f0-9]{64}',value['source_sha256'])):
        raise ValueError('JS_JSON_SCRIPT_SPAN_INVALID')
    return value


def validate_spec(locator):
    steps=normalize_steps(locator.get('json_steps'))
    hashes=locator.get('json_hashes');types=locator.get('json_types')
    if (not isinstance(hashes,list) or len(hashes)!=len(steps) or any(
            not isinstance(h,str) or not re.fullmatch('[a-f0-9]{64}',h) for h in hashes) or
            not isinstance(types,list) or len(types)!=len(steps) or any(t not in ('object','array','string') for t in types)):
        raise ValueError('JS_JSON_LAYERS_INVALID')
    if 'script_span' in locator:script_span(locator['script_span'])
    return steps


def _pairs(items):
    result={}
    for key,value in items:
        if key in result:raise ValueError('JS_JSON_DUPLICATE_KEY')
        result[key]=value
    return result


def _load(value):
    if not isinstance(value,str):raise ValueError('JS_JSON_LAYER_NOT_STRING')
    def reject_constant(_):raise ValueError('JS_JSON_NONFINITE')
    try:return json.loads(value,object_pairs_hook=_pairs,parse_constant=reject_constant)
    except (ValueError,TypeError) as error:raise ValueError('JS_JSON_LAYER_INVALID: '+str(error)) from error


def _key(value,token):
    if isinstance(value,dict) and token in value:return token
    if isinstance(value,list) and re.fullmatch('0|[1-9][0-9]*',token) and int(token)<len(value):return int(token)
    raise ValueError('JS_JSON_PATH_MISSING')


def _get(value,pointer):
    for token in pointer_tokens(pointer):value=value[_key(value,token)]
    return value


def _kind(value):
    return 'object' if isinstance(value,dict) else 'array' if isinstance(value,list) else 'string' if isinstance(value,str) else 'other'


def read_value(outer,steps):
    steps=normalize_steps(steps);value=outer;hashes=[];types=[]
    for pointer in steps:
        if not isinstance(value,str):raise ValueError('JS_JSON_LAYER_NOT_STRING')
        hashes.append(hash_text(value));document=_load(value);types.append(_kind(document))
        if types[-1]=='other':raise ValueError('JS_JSON_LAYER_TYPE')
        value=_get(document,pointer)
    if not isinstance(value,str):raise ValueError('JS_JSON_LEAF_NOT_STRING')
    return value,dict(json_steps=steps,json_hashes=hashes,json_types=types)


def _write(value,steps,text):
    document=_load(value);tokens=pointer_tokens(steps[0]);parent=document
    for token in tokens[:-1]:parent=parent[_key(parent,token)]
    old=_get(document,steps[0]);updated=_write(old,steps[1:],text) if len(steps)>1 else text
    if tokens:parent[_key(parent,tokens[-1])]=updated
    else:document=updated
    return json.dumps(document,ensure_ascii=False,separators=(',',':'),allow_nan=False)


def patch_values(outer,edits,patch_script=None):
    """Validate all fields against the same original, then serialize each layer."""
    paths=[];scripts={};plain=[]
    for locator,text in edits:
        steps=validate_spec(locator);value,spec=read_value(outer,steps)
        if not isinstance(text,str) or any(spec[k]!=locator[k] for k in spec):
            raise ValueError('JS_JSON_SOURCE_CHANGED')
        address=ownership_tokens(steps)
        if 'script_span' in locator:
            span=script_span(locator['script_span'])
            if hash_text(value)!=span['source_sha256']:raise ValueError('JS_JSON_SCRIPT_CHANGED')
            address+=(('script',''),('range',str(span['start'])+':'+str(span['end'])))
            scripts.setdefault(tuple(steps),[]).append((locator,text))
        else:
            if value!=locator['expected']:raise ValueError('JS_JSON_SOURCE_CHANGED')
            plain.append((locator,text))
        paths.append(address)
    ordered=sorted(paths)
    if any(right[:len(left)]==left for left,right in zip(ordered,ordered[1:])):
        raise ValueError('JS_JSON_OVERLAPPING_WRITES')
    if all(locator['expected']==text for locator,text in edits):return outer
    # Each script is assembled once by the existing AST writer, before JSON encoding.
    for steps,group in scripts.items():
        if patch_script is None:raise ValueError('JS_JSON_SCRIPT_WRITER_REQUIRED')
        body=read_value(outer,list(steps))[0];updated=patch_script(body,group)
        plain.append(({'json_steps':list(steps)},updated))
    output=outer
    for locator,text in plain:output=_write(output,locator['json_steps'],text)
    for locator,text in plain:
        if read_value(output,locator['json_steps'])[0]!=text:raise ValueError('JS_JSON_WRITE_MISMATCH')
    return output
