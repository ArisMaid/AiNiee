"""Compare one document's approved native occurrences with extraction candidates."""
from copy import deepcopy

_NO_DOCUMENT = object()


def _field_types(document, native, resolved, groups):
    """Audit claimed string targets once per pointer/shared candidate array."""
    if document is _NO_DOCUMENT:
        return {'type_check':'unavailable','type_conflicts':[], 'source_field_types':{},
                'type_conflict_count':0,'type_conflict_pointer_count':0}
    from ModuleFolders.Infrastructure.GameAdapters.RpgMaker.JsonPatcher import resolve_pointer
    cache, bad_types, conflicts, shared, type_sets = {}, {}, [], {}, {}
    def kind(pointer):
        if pointer not in cache:
            try:
                value = resolve_pointer(document, pointer)
            except ValueError:
                result = 'unresolved'
            else:
                result = ('null' if value is None else 'boolean' if isinstance(value,bool) else
                          'string' if isinstance(value,str) else 'number' if isinstance(value,(int,float)) else
                          'array' if isinstance(value,list) else 'object' if isinstance(value,dict) else 'unsupported')
            cache[pointer] = result
            if result != 'string':
                bad_types[pointer] = result
        return cache[pointer]
    for row in native:
        actual = kind(row['pointer'])
        if actual != 'string':
            conflicts.append({'side':'native','unit_id':row['unit_id'],'pointer':row['pointer'],
                              'expected_type':'string','actual_type':actual,'reason':'source_field_type'})
    next_group = 0
    for index,pointers in enumerate(resolved):
        identity = id(pointers)
        if identity not in shared:
            bad = [pointer for pointer in dict.fromkeys(pointers) if kind(pointer) != 'string']
            group_id = None
            if bad:
                while 'type'+str(next_group) in groups:
                    next_group += 1
                group_id = 'type'+str(next_group);next_group += 1
                groups[group_id] = bad
                type_sets[group_id] = sorted({bad_types[p] for p in bad})
            shared[identity] = group_id
        group_id = shared[identity]
        if group_id is not None:
            conflicts.append({'side':'backend','record_index':index,'candidate_pointer_group':group_id,
                'candidate_pointer_count':len(groups[group_id]),'expected_type':'string',
                'actual_types':type_sets[group_id],'reason':'source_field_type'})
    return {'type_check':'complete','type_conflicts':conflicts,'source_field_types':bad_types,
            'type_conflict_count':len(conflicts),'type_conflict_pointer_count':len(bad_types)}


def _field(value,key,default=None):
    return value.get(key,default) if isinstance(value,dict) else getattr(value,key,default)


def compare_extractions(native_units,backend_result,relative_path,*,document=_NO_DOCUMENT):
    if not isinstance(relative_path,str) or not relative_path:raise ValueError('relative_path is required')
    if not isinstance(backend_result,dict) or backend_result.get('ok') is not True:
        raise ValueError('BACKEND_RESULT_INVALID')
    native=[];native_occurrences=[];ownership=[]
    for unit in native_units:
        unit_id=_field(unit,'unit_id')
        for occurrence in _field(unit,'occurrences',()):
            if _field(occurrence,'relative_path')!=relative_path:continue
            locator=_field(occurrence,'locator',{})
            pointer=_field(locator,'pointer')
            if isinstance(pointer,str):
                ownership.append((unit_id,occurrence))
                native.append((unit_id,pointer))
                native_occurrences.append({'unit_id':unit_id,'pointer':pointer,
                    'kind':_field(unit,'kind'),'role':_field(occurrence,'role'),
                    'value_codec':_field(locator,'value_codec'),
                    'source_text':_field(unit,'source_text',_field(unit,'text')),
                    'source_hash':_field(unit,'source_hash'),
                    'expected_value_hash':_field(occurrence,'expected_value_hash')})
    approved={}
    for uid,pointer in native:approved.setdefault(pointer,[]).append(uid)
    if len(approved)!=len(native):
        from types import SimpleNamespace
        from ModuleFolders.Domain.GameProject.WriteOwnership import ownership_issues
        claims=[SimpleNamespace(unit_id=uid,occurrences=(SimpleNamespace(
            occurrence_id=_field(o,'occurrence_id','comparison'),relative_path=relative_path,
            adapter_id=_field(o,'adapter_id','rpgmaker-native'),locator=_field(o,'locator',{})),)) for uid,o in ownership]
        if ownership_issues(claims):raise ValueError('NATIVE_OWNERSHIP_CONFLICT')
    overlaps=[];other=[];ambiguous=[];used=set()
    from ModuleFolders.Infrastructure.GameAdapters.ExtractionPointerPool import pointer_lists
    records=backend_result.get('records',[])
    resolved=pointer_lists(backend_result)
    backend_records=[{'record_index':index,'text':row.get('text'),
        'locator':deepcopy(row.get('locator',{}))} for index,row in enumerate(records)]
    deduplicated={}
    def unique(raw):
        key=id(raw)
        if key not in deduplicated:deduplicated[key]=list(dict.fromkeys(raw))
        return deduplicated[key]
    def location(row,pointers):
        group=row.get('candidate_pointer_group')
        if group is not None:return {'candidate_pointer_group':group,'candidate_pointer_count':len(pointers)}
        return {'candidate_pointers':pointers}
    for index,row in enumerate(records):
        pointers=unique(resolved[index])
        if len(pointers)>1:
            ambiguous.append({'record_index':index,**location(row,pointers),'reason':'multiple_candidate_pointers'})
        elif len(pointers)==1 and len(approved.get(pointers[0],[]))>1:
            # A whole-leaf backend record cannot identify one of its logical fragments.
            ambiguous.append({'record_index':index,**location(row,pointers),'reason':'shared_native_leaf'})
        elif len(pointers)==1 and pointers[0] in approved and pointers[0] not in used:
            pointer=pointers[0];used.add(pointer)
            overlaps.append({'unit_id':approved[pointer][0],'record_index':index,'pointer':pointer})
        else:other.append({'record_index':index,**location(row,pointers)})
    missing=[{'unit_id':uid,'pointer':pointer} for uid,pointer in native if pointer not in used]
    report={'counts':{'native_total':len(native),'backend_total':len(records),'overlap':len(overlaps),
        'native_only':len(missing),'backend_only':len(other),'ambiguous':len(ambiguous)},
        'native_only':missing,'backend_only':other,'overlap':overlaps,'ambiguous':ambiguous,
        'native_occurrences':native_occurrences,'backend_records':backend_records}
    groups = {key:unique(value) for key,value in backend_result.get('candidate_pointer_groups',{}).items()}
    report.update(_field_types(document,native_occurrences,resolved,groups))
    if 'pointer_pool_schema' in backend_result or groups:
        report.update(pointer_pool_schema=1,candidate_pointer_groups=groups)
    return report
