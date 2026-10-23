"""Source-only duplicate-key inventory for unrequested directory discovery.

Write targets must have unique keys. An unrouted source can be inspected using
the SDK and RPG Maker JSON.parse last-key semantics, with every duplicate key
reported. Such a file never obtains a proven writable locator. Outputs are
still parsed strictly by both the worker and parent; no output repair occurs.
"""
import json
from collections import Counter

class _Pairs(list):pass

def parse_source_json(raw,*,writable=False):
    def invalid(_):raise ValueError('BACKEND_SOURCE_JSON_INVALID')
    try:tree=json.loads(raw.decode('utf-8-sig'),object_pairs_hook=_Pairs,parse_constant=invalid)
    except (UnicodeError,ValueError,RecursionError):raise ValueError('BACKEND_SOURCE_JSON_INVALID') from None
    duplicates=[]
    def escape(key):return key.replace('~','~0').replace('/','~1')
    def walk(node,pointer):
        if isinstance(node,_Pairs):
            counts=Counter(key for key,_ in node)
            for key,count in counts.items():
                if count>1:duplicates.append({'pointer':pointer+'/'+escape(key),'occurrences':count})
            result={}
            for key,value in node:result[key]=walk(value,pointer+'/'+escape(key))
            return result
        if isinstance(node,list):return [walk(value,pointer+'/'+str(index)) for index,value in enumerate(node)]
        return node
    try:document=walk(tree,'')
    except RecursionError:raise ValueError('BACKEND_SOURCE_JSON_INVALID') from None
    if duplicates and writable:raise ValueError('BACKEND_DUPLICATE_SOURCE_UNSUPPORTED')
    return document,duplicates
