"""Confirmed image regions, private previews and explicit output approval."""
from __future__ import annotations
import hashlib
import io
import json
from pathlib import Path
import uuid

from .PathGuard import safe_join, atomic_write
from .ProjectLock import ProjectLock
from ModuleFolders.Domain.GameProject.Models import TranslationUnit, Occurrence, hash_text

SUFFIXES={'.png','.png_','.rpgmvp'}


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,
        separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _read(path,limit=64*1024*1024):
    if path.stat().st_size>limit:raise ValueError('IMAGE_INPUT_TOO_LARGE')
    with path.open('rb') as f:data=f.read(limit+1)
    if len(data)>limit:raise ValueError('IMAGE_INPUT_TOO_LARGE')
    return data


def _sha(data):return hashlib.sha256(data).hexdigest()


def inventory(store):
    return {'images':[{'relative_path':r['relative_path'],'source_sha256':r['sha256'],
        'size':r['size'],'supported':Path(r['relative_path']).suffix.lower() in SUFFIXES}
        for r in store.files() if r['relative_path'].lower().startswith('img/')],
        'settings':store.metadata().get('image_settings',{})}


def _asset(store,rel):
    from .ImageCodec import decode_image
    if not isinstance(rel,str) or not rel.startswith('img/') or Path(rel).suffix.lower() not in SUFFIXES:
        raise ValueError('IMAGE_FORMAT_UNSUPPORTED')
    record=next((r for r in store.files() if r['relative_path']==rel),None)
    if not record:raise ValueError('IMAGE_SOURCE_UNKNOWN')
    source=safe_join(store.metadata()['source_root'],rel,must_exist=True)
    data=_read(source)
    if _sha(data)!=record['sha256']:raise ValueError('IMAGE_SOURCE_CHANGED')
    system=safe_join(store.root,'source/data/System.json',must_exist=True)
    system_record=next(r for r in store.files() if r['relative_path']=='data/System.json')
    system_bytes=_read(system)
    if _sha(system_bytes)!=system_record['sha256']:raise ValueError('IMAGE_SYSTEM_CHANGED')
    key=json.loads(system_bytes.decode('utf-8-sig')).get('encryptionKey','')
    png,info=decode_image(data,Path(rel).suffix.lower(),key)
    return png,info,key,record


def preview(store,rel):
    png,info,_,record=_asset(store,rel)
    path=f'images/previews/{uuid.uuid4().hex}.png'
    atomic_write(safe_join(store.root,path),png)
    return dict(info,relative_path=rel,source_sha256=record['sha256'],preview=str(store.root/path))


def ocr(store,rel,executable,tessdata,language='jpn+eng',*,on_job=None):
    from .ImageCodec import ocr_png
    from .ExternalTask import run_external_task
    def compute(control):
        png,info,_,record=_asset(store,rel)
        control.check(force=True)
        result=ocr_png(png,executable,tessdata,language)
        result.update(relative_path=rel,source_sha256=record['sha256'],image=info,
            state='candidate_requires_confirmation')
        return result
    def publish(result):
        path=f'images/ocr/{uuid.uuid4().hex}.json'
        atomic_write(safe_join(store.root,path),json.dumps(result,ensure_ascii=False,indent=2).encode())
        return dict(result,candidate_file=str(store.root/path))
    return run_external_task(store,'IMAGE_OCR',{'relative_path':rel,'language':language},
        compute,publish,on_job)


def _regions(regions,width,height):
    if not isinstance(regions,list) or not 1<=len(regions)<=500:raise ValueError('IMAGE_REGIONS_INVALID')
    normalized=[];seen=set()
    for row in regions:
        if not isinstance(row,dict) or set(row)-{'region_id','box','text','font_size','color','align'}:
            raise ValueError('IMAGE_REGION_INVALID')
        rid=row.get('region_id') or uuid.uuid4().hex
        if not isinstance(rid,str) or len(rid)!=32 or any(c not in '0123456789abcdef' for c in rid) or rid in seen:
            raise ValueError('IMAGE_REGION_ID_INVALID')
        seen.add(rid);box=row.get('box')
        if not isinstance(box,list) or len(box)!=4 or any(type(v)!=int for v in box):raise ValueError('IMAGE_BOX_INVALID')
        x,y,w,h=box
        if min(x,y)<0 or min(w,h)<=0 or x+w>width or y+h>height:raise ValueError('IMAGE_BOX_OUT_OF_BOUNDS')
        for other in normalized:
            a,b,c,d=other['box']
            if x<a+c and a<x+w and y<b+d and b<y+h:raise ValueError('IMAGE_BOX_OVERLAP')
        text=row.get('text')
        if not isinstance(text,str) or not text.strip() or len(text)>2000:raise ValueError('IMAGE_TEXT_INVALID')
        size=row.get('font_size',24);color=row.get('color',[255,255,255,255]);align=row.get('align','center')
        if type(size)!=int or not 6<=size<=256:raise ValueError('IMAGE_FONT_SIZE_INVALID')
        if not isinstance(color,list) or len(color)!=4 or any(type(v)!=int or not 0<=v<=255 for v in color):raise ValueError('IMAGE_COLOR_INVALID')
        if align not in ('left','center','right'):raise ValueError('IMAGE_ALIGN_INVALID')
        normalized.append(dict(region_id=rid,box=box,text=text,font_size=size,color=color,align=align))
    return normalized


def _unit(rel,region,source_sha,policy_id='rpgmaker-v1'):
    uid='image:'+hashlib.sha256((rel+'\0'+region['region_id']).encode()).hexdigest()[:32]
    occurrence=Occurrence(uid+':occ',rel,{'pointer':'region/'+region['region_id'],
        'region_id':region['region_id'],'box':region['box'],'source_sha256':source_sha},
        hash_text(region['text']),adapter_id='image-region')
    return TranslationUnit(uid,'image-text',region['text'],scene_id=rel,
        context={'image':rel,'region_id':region['region_id'],'box':region['box']},occurrences=(occurrence,),token_policy_id=policy_id)


def confirm_regions(store,rel,source_sha256,regions):
    """The explicit call is the human confirmation boundary; OCR never calls it."""
    with ProjectLock(store.root):
        _,info,_,record=_asset(store,rel)
        if source_sha256!=record['sha256']:raise ValueError('IMAGE_CONFIRM_SOURCE_MISMATCH')
        rows=_regions(regions,info['width'],info['height'])
        settings=store.metadata().get('image_settings',{})
        old=settings.get(rel,{})
        # Preserve a cleaned base only when the same region geometry is retained.
        same=[r['box'] for r in rows]==[r['box'] for r in old.get('regions',[])]
        entry={k:v for k,v in old.items() if same and k in {'clean_base_path','clean_base_sha256','font_path','font_sha256'}}
        entry.update(source_sha256=source_sha256,width=info['width'],height=info['height'],regions=rows)
        settings[rel]=entry
        units=[u for u in store.units() if not(u.kind=='image-text' and u.scene_id==rel)]
        policy_id=store.metadata().get('token_policy_id','rpgmaker-v1')
        units.extend(_unit(rel,r,source_sha256,policy_id) for r in rows)
        stats=dict(store.metadata().get('extraction_stats',{}),unit_count=len(units),
            occurrence_count=sum(len(unit.occurrences) for unit in units))
        result=store.replace_units(units,image_settings=settings,extraction_metadata={'extraction_stats':stats})
        return dict(result,regions=rows,unit_ids=[_unit(rel,r,source_sha256).unit_id for r in rows])


def _unchanged_outside(original,clean,regions):
    from PIL import Image,ImageChops,ImageDraw
    a=Image.open(io.BytesIO(original)).convert('RGBA');b=Image.open(io.BytesIO(clean)).convert('RGBA')
    if a.size!=b.size:raise ValueError('IMAGE_BASE_DIMENSIONS_CHANGED')
    mask=Image.new('L',a.size,255);draw=ImageDraw.Draw(mask)
    for row in regions:
        x,y,w,h=row['box'];draw.rectangle((x,y,x+w-1,y+h-1),fill=0)
    diff=ImageChops.difference(a,b)
    if any(ImageChops.multiply(channel,mask).getbbox() for channel in diff.split()):
        raise ValueError('IMAGE_BASE_CHANGED_OUTSIDE_REGIONS')


def prepare_base(store,rel,clean_base,font):
    from .ImageCodec import decode_image
    with ProjectLock(store.root):
        original,_,_,_=_asset(store,rel)
        settings=store.metadata().get('image_settings',{})
        if rel not in settings:raise ValueError('IMAGE_REGIONS_NOT_CONFIRMED')
        entry=settings[rel]
        # External files are read, then captured; they are never trusted by builds.
        clean,_=decode_image(_read(Path(clean_base).absolute()),'.png')
        _unchanged_outside(original,clean,entry['regions'])
        font_bytes=_read(Path(font).absolute(),32*1024*1024)
        from fontTools.ttLib import TTFont
        with TTFont(io.BytesIO(font_bytes)) as face:face.getBestCmap()
        root=f'images/bases/{uuid.uuid4().hex}'
        clean_path=root+'/clean.png';font_path=root+'/font.ttf'
        atomic_write(safe_join(store.root,clean_path),clean)
        atomic_write(safe_join(store.root,font_path),font_bytes)
        entry.update(clean_base_path=clean_path,clean_base_sha256=_sha(clean),font_path=font_path,font_sha256=_sha(font_bytes))
        entry.pop('candidate',None);entry.pop('approved',None)
        store.update_metadata({'image_settings':settings})
        return {'relative_path':rel,'state':'base_captured','clean_base_sha256':_sha(clean)}


def _input(store,rel):
    settings=store.metadata().get('image_settings',{})
    entry=settings.get(rel)
    if not entry or not entry.get('clean_base_path'):raise ValueError('IMAGE_BASE_NOT_PREPARED')
    rows=[];translations=[]
    for region in entry['regions']:
        unit=_unit(rel,region,entry['source_sha256'],store.metadata().get('token_policy_id','rpgmaker-v1'));current=store.unit(unit.unit_id)
        tr=store.translation(unit.unit_id)
        if not current or current.source_hash!=unit.source_hash or not tr or not tr.get('text') or tr.get('stale') or tr['source_hash']!=unit.source_hash:
            raise ValueError('IMAGE_TRANSLATION_MISSING_OR_STALE')
        from .TranslationCommitter import TranslationCommitter
        from ModuleFolders.Domain.GameProject.Models import TranslationProposal
        if any(i.severity=='error' for i in TranslationCommitter(store).validate_proposal(TranslationProposal(
            unit.unit_id,tr['text'],unit.source_hash,expected_revision=tr['revision'],origin='image-render'))):
            raise ValueError('IMAGE_TRANSLATION_INVALID')
        rows.append(dict(box=region['box'],text=tr['text'],font_size=region['font_size'],color=region['color'],align=region['align']))
        translations.append((unit.unit_id,tr['revision'],tr['text']))
    payload={k:v for k,v in entry.items() if k not in {'approved','candidate'}}
    return entry,rows,digest({'settings':payload,'translations':translations})


def render_candidate(store,rel):
    from .ImageCodec import render_png,encode_image
    with ProjectLock(store.root):
        _,_,key,_=_asset(store,rel)
        entry,rows,input_digest=_input(store,rel)
        clean=_read(safe_join(store.root,entry['clean_base_path'],must_exist=True))
        font=_read(safe_join(store.root,entry['font_path'],must_exist=True),32*1024*1024)
        if _sha(clean)!=entry['clean_base_sha256'] or _sha(font)!=entry['font_sha256']:raise ValueError('IMAGE_CAPTURE_CHANGED')
        png=render_png(clean,rows,font)
        data=encode_image(png,Path(rel).suffix.lower(),key)
        candidate_path=f'images/candidates/{uuid.uuid4().hex}'
        atomic_write(safe_join(store.root,candidate_path+'/preview.png'),png)
        atomic_write(safe_join(store.root,candidate_path+'/asset.bin'),data)
        candidate={'path':candidate_path+'/asset.bin','preview':candidate_path+'/preview.png',
            'sha256':_sha(data),'input_digest':input_digest,'state':'requires_visual_approval'}
        settings=store.metadata()['image_settings'];settings[rel]['candidate']=candidate
        settings[rel].pop('approved',None)
        store.update_metadata({'image_settings':settings})
        return dict(candidate,preview=str(store.root/candidate['preview']),relative_path=rel)


def approve_candidate(store,rel,sha256):
    with ProjectLock(store.root):
        _asset(store,rel)
        entry,_,input_digest=_input(store,rel)
        candidate=entry.get('candidate',{})
        if candidate.get('sha256')!=sha256 or candidate.get('input_digest')!=input_digest:
            raise ValueError('IMAGE_CANDIDATE_STALE')
        if _sha(_read(safe_join(store.root,candidate['path'],must_exist=True)))!=sha256:raise ValueError('IMAGE_CANDIDATE_CHANGED')
        settings=store.metadata()['image_settings'];settings[rel]['approved']=dict(candidate,state='approved')
        store.update_metadata({'image_settings':settings})
        return {'relative_path':rel,'state':'approved','sha256':sha256}


def build_image(store,rel,original,project_root=None):
    from .ImageCodec import decode_image
    entry,_,input_digest=_input(store,rel)
    approved=entry.get('approved',{})
    if approved.get('input_digest')!=input_digest or approved.get('state')!='approved':raise ValueError('IMAGE_VISUAL_APPROVAL_REQUIRED')
    if _sha(original)!=entry['source_sha256']:raise ValueError('IMAGE_SOURCE_CHANGED')
    root=project_root or store.root
    data=_read(safe_join(root,approved['path'],must_exist=True))
    if _sha(data)!=approved['sha256']:raise ValueError('IMAGE_CANDIDATE_CHANGED')
    # Decode with the captured key and check actual dimensions before adopting.
    system=json.loads(_read(safe_join(root,'source/data/System.json',must_exist=True)).decode('utf-8-sig'))
    _,info=decode_image(data,Path(rel).suffix.lower(),system.get('encryptionKey',''))
    if (info['width'],info['height'])!=(entry['width'],entry['height']):raise ValueError('IMAGE_DIMENSIONS_CHANGED')
    return data,{'id':'image-region','input_digest':input_digest,'approved_sha256':approved['sha256']}
