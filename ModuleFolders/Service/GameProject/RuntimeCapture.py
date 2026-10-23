"""Optional capture injection and bounded, read-only association to known units."""
import hashlib
import json
import re
import math
from pathlib import Path
from .PathGuard import safe_join,atomic_write


def capture_script(build_id=''):
    resource=Path(__file__).resolve().parents[3]/'Resource/RpgRuntime/AiNieeCapture.js'
    data=resource.read_bytes()
    if build_id:
        if not isinstance(build_id,str) or not re.fullmatch('[a-f0-9]{32}',build_id):raise ValueError('INVALID_CAPTURE_BUILD_ID')
        data+=b'\nwindow.AiNieeCapture.build_id = '+json.dumps(build_id).encode('ascii')+b';\n'
    return data


def install_capture(staging,manifest_files,*,writer=None,build_id=''):
    write=atomic_write if writer is None else writer
    data=capture_script(build_id);rel='js/AiNieeCapture.js'
    target=safe_join(staging,rel)
    if target.exists():
        if target.read_bytes()!=data:raise ValueError('CAPTURE_SNAPSHOT_CHANGED')
    else:write(target,data)
    html=safe_join(staging,'index.html',must_exist=True)
    before=html.read_bytes()
    if b'AiNieeCapture.js' in before:raise ValueError('CAPTURE_SCRIPT_ALREADY_PRESENT')
    tag=b'\n<script src="js/AiNieeCapture.js"></script>\n'
    # Append is safe for HTML parsing and leaves every existing byte in place.
    write(html,before+tag,overwrite=True)
    existing=next(r for r in manifest_files if r['path']=='index.html')
    existing.update(output_sha256=hashlib.sha256(before+tag).hexdigest(),changed=True,reason='test_runtime_capture')
    manifest_files.append({'path':rel,'original_sha256':None,
        'output_sha256':hashlib.sha256(data).hexdigest(),'changed':True,'reason':'test_runtime_capture'})
    return {'enabled':True,'build_id':build_id,'sink':'Window/Bitmap text','max_events':3000,'max_events_per_second':100,
        'sinks':['Window_Base.drawTextEx','Window_Message.startMessage','Bitmap.drawText'],
        'export':'AiNieeCapture.exportJSON()','disable':'AiNieeCapture.stop()',
        'limitations':['CJK observations are not a language or visibility verdict','Latest 3000 events; rate limited to 100/s',
            'Images and nonstandard canvas writers are not captured','Event context may refer to map interpreter rather than actual caller',
            'Horizontal widths are observations; vertical fit and font fallback are not checked'],
        'runtime_validation':'not_run'}


def associate_events(store,payload):
    if not isinstance(payload,dict) or payload.get('schema_version')!=1:raise ValueError('INVALID_CAPTURE_FORMAT')
    events=payload.get('events')
    if not isinstance(events,list) or len(events)>3000:raise ValueError('CAPTURE_LIMIT_EXCEEDED')
    known={};units={unit.unit_id:unit for unit in store.units()}
    for unit in units.values():
        known.setdefault(unit.source_text,{}).setdefault(unit.unit_id,set()).add('source')
        tr=store.translation(unit.unit_id) or {}
        if tr.get('text') and not tr.get('stale'):known.setdefault(tr['text'],{}).setdefault(unit.unit_id,set()).add('translation')
    rows=[];profiles=[];layout_issues=[]
    number=lambda value:type(value) in (int,float) and math.isfinite(value) and value>=0
    for event in events:
        if not isinstance(event,dict) or not isinstance(event.get('text'),str) or len(event['text'])>4096:
            raise ValueError('INVALID_CAPTURE_EVENT')
        matched={} if event.get('truncated') else known.get(event['text'],{})
        matches=sorted(matched);locations=[];total=0
        for uid in matches:
            for occurrence in units[uid].occurrences:
                total+=1
                if len(locations)>=20:continue
                loc=occurrence.locator
                locations.append(dict(unit_id=uid,path=occurrence.relative_path,
                    **{k:loc[k] for k in ('pointer','note_tag','object_path','property_path','json_steps') if k in loc},
                    **({'script_label':loc['script_span']['id']} if loc.get('script_span') else {})))
        text_hash=hashlib.sha256(event['text'].encode()).hexdigest()
        measured=event.get('measured_width');available=event.get('available_width')
        if (not event.get('truncated') and number(measured) and number(available) and
                event.get('measurement') in ('drawTextEx-return','canvas-natural-width')):
            profile={key:event[key] for key in ('scene','window_class','window_id','window_x','window_y','sink','x','y','max_width','available_width',
                'measured_width','measurement','font_family','entry_pixel_size','exit_pixel_size','logical_line_count') if key in event}
            profile.update(text_hash=text_hash,candidate_unit_ids=matches,locations=locations,
                observation='runtime-horizontal-width',exceeds_width=measured>available)
            profiles.append(profile)
            if measured>available:
                layout_issues.append(dict(code='TEXT_LAYOUT_OVERFLOW',severity='warning',
                    unit_id=matches[0] if len(matches)==1 else '',path=locations[0]['path'] if locations else '',
                    message='Observed natural text width exceeds the available horizontal area; inspect clipping or compression',
                    details=profile))
        rows.append({'text_hash':text_hash,
            'candidate_unit_ids':matches,'association':'truncated_rendered_text' if event.get('truncated') else 'exact_text' if matches else 'unmatched_rendered_text',
            'match_kinds':sorted({kind for kinds in matched.values() for kind in kinds}),
            'locations':locations,'location_count':total,'locations_truncated':total>len(locations),
            'context':{k:event[k] for k in ('scene','map_id','event_id','command_index','sink','window_class','max_width','time_ms','x','y') if k in event}})
    return {'events':rows,'reported_build_id':payload.get('build_id',''),
        'stats':{name:sum(row['association']==name for row in rows) for name in ('exact_text','unmatched_rendered_text','truncated_rendered_text')},
        'layout_profiles':profiles,'layout_issues':layout_issues,
        'layout_stats':{'measured':len(profiles),'unmeasured':len(rows)-len(profiles),'width_warnings':len(layout_issues)},
        'layout_scope':'Observed horizontal widths only; no vertical fit, dynamic-value boundary or whole-game pass',
        'automatic_rule_changes':0,'runtime_validation':'observations_only'}
