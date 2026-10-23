'use strict';
const fs = require('node:fs');
const acorn = require(process.env.RPG_ACORN_PATH || 'acorn');
const IDENT=/^[A-Za-z_$][A-Za-z0-9_$]*$/;
const MAX_IDENTIFIER=128, MAX_OBJECT_PATH=512, MAX_FIELDS=32;
const FUNCTION_TYPES=new Set(['FunctionDeclaration','FunctionExpression','ArrowFunctionExpression']);
const DICTIONARY_TYPES=new Set(['ObjectExpression','ArrayExpression']);
function walk(node, fn, path=[]) {
  if (!node || typeof node !== 'object') return;
  if (typeof node.type === 'string') fn(node, path);
  for (const [k,v] of Object.entries(node)) {
    if (Array.isArray(v)) v.forEach((n,i)=>walk(n,fn,[...path,k,i]));
    else if (v && typeof v==='object') walk(v,fn,[...path,k]);
  }
}
// Lexical (non-function) traversal: never enters a function body, so global
// scope selection cannot pick definitions that belong to nested code.
function walkLexical(node, fn) {
  if (!node || typeof node !== 'object') return;
  if (FUNCTION_TYPES.has(node.type)) return;
  if (typeof node.type === 'string') fn(node);
  for (const [k,v] of Object.entries(node)) {
    if (Array.isArray(v)) v.forEach((n)=>walkLexical(n,fn));
    else if (v && typeof v==='object') walkLexical(v,fn);
  }
}
function member(node) {
  if (!node) return '';
  if (node.type==='Identifier') return node.name;
  if (node.type==='MemberExpression' && !node.computed)
    return member(node.object)+'.'+node.property.name;
  return '';
}
function propertyKey(node) {
  if (!node) return null;
  if (node.type==='Identifier') return node.name;
  if (node.type==='Literal') return String(node.value);
  return null;
}
function parse(source) { return acorn.parse(source,{ecmaVersion:2022,sourceType:'script',allowHashBang:true}); }
function byte(source, offset) { return Buffer.byteLength(source.slice(0,offset),'utf8'); }
function identifier(value, label, limit) {
  if (typeof value!=='string' || value.length===0 || value.length>limit || !IDENT.test(value))
    throw new Error('INVALID_'+label);
  return value;
}
function objectPathParts(value) {
  if (typeof value!=='string' || value.length===0 || value.length>MAX_OBJECT_PATH)
    throw new Error('INVALID_OBJECT_PATH');
  return value.split('.').map(part=>identifier(part,'OBJECT_PATH',MAX_IDENTIFIER));
}
function optionalIdentifier(value, label) {
  if (value===undefined) return null;
  return identifier(value,label,MAX_IDENTIFIER);
}
function propertyFieldSet(value) {
  if (value===undefined) return null;
  if (!Array.isArray(value) || value.length===0 || value.length>MAX_FIELDS)
    throw new Error('INVALID_PROPERTY_FIELDS');
  const fields=new Set();
  for (const field of value) {
    identifier(field,'PROPERTY_FIELDS',MAX_IDENTIFIER);
    if (fields.has(field)) throw new Error('INVALID_PROPERTY_FIELDS');
    fields.add(field);
  }
  return fields;
}
// Static resolution of the remaining dotted segments through literal object
// properties and array indexes; anything dynamic yields no definition.
function resolvePath(node, parts) {
  let current=node;
  for (const part of parts) {
    if (!current) return null;
    if (current.type==='ObjectExpression') {
      let next=null;
      for (const p of current.properties) {
        if (p.type!=='Property' || p.computed || p.kind!=='init') continue;
        if (propertyKey(p.key)===part) { next=p.value; break; }
      }
      current=next;
    } else if (current.type==='ArrayExpression') {
      current=/^\d+$/.test(part) ? current.elements[Number(part)]||null : null;
    } else return null;
  }
  return current||null;
}
function binds(pattern, name) {
  if (!pattern) return false;
  if (pattern.type==='Identifier') return pattern.name===name;
  if (pattern.type==='RestElement') return binds(pattern.argument,name);
  if (pattern.type==='AssignmentPattern') return binds(pattern.left,name);
  if (pattern.type==='ArrayPattern') return pattern.elements.some(p=>binds(p,name));
  if (pattern.type==='ObjectPattern') return pattern.properties.some(p=>binds(p.type==='RestElement'?p.argument:p.value,name));
  return false;
}
function shadows(fn, name) {
  if ((fn.id && fn.id.name===name) || fn.params.some(p=>binds(p,name))) return true;
  function visit(node) {
    if (!node || typeof node!=='object') return false;
    if (FUNCTION_TYPES.has(node.type)) return node.type==='FunctionDeclaration' && node.id && node.id.name===name;
    if (node.type==='ClassDeclaration' && node.id && node.id.name===name) return true;
    if (node.type==='VariableDeclarator' && binds(node.id,name)) return true;
    if (node.type==='CatchClause' && binds(node.param,name)) return true;
    return Object.values(node).some(value=>Array.isArray(value)?value.some(visit):visit(value));
  }
  return visit(fn.body);
}
function immediateAssignments(root, objectPath, parts, found, depth=0) {
  if (parts.length<2 || depth>16) return;
  walkLexical(root,n=>{
    if (n.type!=='CallExpression' || !n.callee ||
        !['FunctionExpression','ArrowFunctionExpression'].includes(n.callee.type)) return;
    const fn=n.callee;
    if (fn.generator || fn.body.type!=='BlockStatement' || shadows(fn,parts[0])) return;
    walkLexical(fn.body,assignment=>{
      if (assignment.type==='AssignmentExpression' && assignment.operator==='=' &&
          member(assignment.left)===objectPath && DICTIONARY_TYPES.has(assignment.right.type)) found.push(assignment.right);
    });
    immediateAssignments(fn.body,objectPath,parts,found,depth+1);
  });
}
// Global lexical scope: exactly one '<object_path> = {...}' assignment or
// declarator definition, with every function body skipped.
function globalDictionary(ast, objectPath, parts) {
  const found=[];
  walkLexical(ast,(n)=>{
    if (n.type==='AssignmentExpression' && n.operator==='=' && member(n.left)===objectPath) {
      if (n.right && DICTIONARY_TYPES.has(n.right.type)) found.push(n.right);
    } else if (n.type==='VariableDeclarator' && n.id && n.id.type==='Identifier' && n.id.name===parts[0]
        && n.init && DICTIONARY_TYPES.has(n.init.type)) {
      const target=parts.length===1?n.init:resolvePath(n.init,parts.slice(1));
      if (target && DICTIONARY_TYPES.has(target.type)) found.push(target);
    }
  });
  // RPG Maker plugins commonly assign a global dictionary inside a static
  // IIFE. Follow only immediately invoked wrappers with no binding that can
  // shadow the global root; ordinary functions and callbacks stay excluded.
  immediateAssignments(ast,objectPath,parts,found);
  if (found.length!==1) throw new Error(found.length?'JS_OBJECT_AMBIGUOUS':'JS_OBJECT_NOT_FOUND');
  return found[0];
}
// Scoped lexical scope: exactly one top-level function declaration of that
// name, and exactly one direct-body declarator binding object_path to a
// literal dictionary. Nested functions, blocks and callbacks are never entered.
function scopedDictionary(ast, scopeFunction, objectPath, staticText=false) {
  const declarations=ast.body.filter(s=>s.type==='FunctionDeclaration' && s.id && s.id.name===scopeFunction);
  if (declarations.length!==1)
    throw new Error(declarations.length?'JS_SCOPE_FUNCTION_AMBIGUOUS':'JS_SCOPE_FUNCTION_NOT_FOUND');
  const body=declarations[0].body;
  const statements=body && body.type==='BlockStatement' ? body.body : null;
  if (!statements) throw new Error('JS_SCOPE_BINDING_NOT_FOUND');
  const found=[];
  for (const statement of statements) {
    if (statement.type!=='VariableDeclaration') continue;
    for (const d of statement.declarations) {
      if (d.id && d.id.type==='Identifier' && d.id.name===objectPath && d.init &&
          (DICTIONARY_TYPES.has(d.init.type) || (staticText &&
            (d.init.type==='TemplateLiteral' || (d.init.type==='Literal' && typeof d.init.value==='string')))))
        found.push(d.init);
    }
  }
  if (found.length!==1) throw new Error(found.length?'JS_SCOPE_BINDING_AMBIGUOUS':'JS_SCOPE_BINDING_NOT_FOUND');
  return found[0];
}
// Static template parts are opt-in within a named scope; expressions stay opaque.
// Keys, computed properties, methods, spreads and tagged templates stay excluded.
function collect(source, node, fields, staticText=false) {
  const rows=[];
  const descend=(current, path)=>{
    if (!current) return;
    if (current.type==='Literal' && typeof current.value==='string') {
      if (fields && !fields.has(path[path.length-1])) return;
      rows.push({value:current.value,start:byte(source,current.start),end:byte(source,current.end),property_path:path});
      return;
    }
    if (staticText && current.type==='TemplateLiteral') {
      if (fields && !fields.has(path[path.length-1])) return;
      current.quasis.forEach((part,index)=>{
        if(typeof part.value.cooked==='string' && part.value.cooked.trim())
          rows.push({value:part.value.cooked,start:byte(source,part.start),end:byte(source,part.end),
            property_path:[...path,'#template',index],node_kind:'template-part'});
      });
      return;
    }
    if (current.type==='ObjectExpression') {
      for (const p of current.properties) {
        if (p.type!=='Property' || p.computed || p.kind!=='init') continue;
        const key=propertyKey(p.key);
        if (key===null) continue;
        descend(p.value,[...path,key]);
      }
    } else if (current.type==='ArrayExpression') current.elements.forEach((n,i)=>descend(n,[...path,i]));
  };
  descend(node,[]);
  return rows;
}
function extract(source, objectPath, scopeFunction, propertyFields, staticText, literalPath) {
  const parts=objectPathParts(objectPath);
  const scope=optionalIdentifier(scopeFunction,'SCOPE_FUNCTION');
  const fields=propertyFieldSet(propertyFields);
  if (scope && parts.length!==1) throw new Error('INVALID_OBJECT_PATH');
  if(staticText!==undefined && (staticText!==true || !scope))throw new Error('INVALID_STATIC_TEXT_SCOPE');
  const ast=parse(source);
  const dictionary=scope?scopedDictionary(ast,scope,objectPath,staticText):globalDictionary(ast,objectPath,parts);
  if(literalPath!==undefined) {
    if(scope || fields || staticText || !Array.isArray(literalPath) || !literalPath.length || literalPath.length>32 ||
        literalPath.some(p=>!((typeof p==='string'&&p.length>0&&p.length<=512)||(Number.isSafeInteger(p)&&p>=0))))
      throw new Error('JS_LITERAL_PATH_INVALID');
    const node=resolvePath(dictionary,literalPath);
    if(!node || node.type!=='Literal' || typeof node.value!=='string')throw new Error('JS_LITERAL_PATH_NOT_STRING');
    return [{value:node.value,start:byte(source,node.start),end:byte(source,node.end),property_path:literalPath}];
  }
  return collect(source,dictionary,fields,staticText);
}
function textNodeValue(node, kind) {
  if(kind==='template-part')return node.type==='TemplateElement' && typeof node.value.cooked==='string'?node.value.cooked:null;
  if(kind!=='literal')return null;
  return node.type==='Literal' && typeof node.value==='string'?node.value:null;
}
function encodedText(text, kind) {
  const encoded=JSON.stringify(text);
  return kind==='template-part'?encoded.slice(1,-1).replace(/`/g,'\\`').replace(/\$\{/g,'\\${'):encoded;
}
function extractSpans(source, spans) {
  if(!Array.isArray(spans)||!spans.length||spans.length>256)throw new Error('JS_SPANS_INVALID');
  const indexed=new Map();walk(parse(source),node=>{
    if(node.type==='Literal'||node.type==='TemplateElement')indexed.set(byte(source,node.start)+':'+byte(source,node.end),node);
  });
  return spans.map(span=>{
    if(!Number.isSafeInteger(span.start)||!Number.isSafeInteger(span.end))throw new Error('JS_SPANS_INVALID');
    const node=indexed.get(span.start+':'+span.end),value=node?textNodeValue(node,span.node_kind):null;
    if(value===null)throw new Error('JS_LOCATOR_MISMATCH');return {...span,value};
  });
}
function skeleton(ast, approved) {
  const cp=JSON.parse(JSON.stringify(ast));
  walk(cp,(n,path)=>{
    if(approved.has(JSON.stringify(path))) n.value='__APPROVED_TEXT__';
    delete n.start;delete n.end;delete n.raw;
  });
  return JSON.stringify(cp);
}
function patch(source, replacements) {
  const ast=parse(source), indexed=new Map(), approved=new Set();
  walk(ast,(n,path)=>{
    if((n.type==='Literal' && typeof n.value==='string') || n.type==='TemplateElement')
      indexed.set(byte(source,n.start)+':'+byte(source,n.end),{node:n,path});
  });
  const seen=new Set();
  for(const r of replacements) {
    const key=r.start+':'+r.end, item=indexed.get(key);
    if(!item || seen.has(key) || textNodeValue(item.node,r.node_kind||'literal')!==r.expected)
      throw new Error('JS_LOCATOR_MISMATCH');
    seen.add(key);approved.add(JSON.stringify(item.path));
    if(typeof r.text!=='string')throw new Error('INVALID_JS_TRANSLATION');
  }
  const sorted=[...replacements].sort((a,b)=>b.start-a.start);
  let data=Buffer.from(source,'utf8'), previous=data.length;
  for(const r of sorted) {
    if(r.start<0 || r.end>previous || r.start>=r.end)throw new Error('OVERLAPPING_JS_WRITES');
    data=Buffer.concat([data.subarray(0,r.start),Buffer.from(encodedText(r.text,r.node_kind||'literal'),'utf8'),data.subarray(r.end)]);
    previous=r.start;
  }
  const output=data.toString('utf8');
  if(skeleton(ast,approved)!==skeleton(parse(output),approved))throw new Error('JS_SEMANTIC_DIFFERENCE');
  return output;
}
function audit(source, output, replacements) {
  if(typeof output!=='string')throw new Error('JS_AUDIT_OUTPUT_REQUIRED');
  if(!Array.isArray(replacements))throw new Error('JS_AUDIT_INVALID_REPLACEMENTS');
  let originalAst,outputAst;
  try{originalAst=parse(source);}catch{throw new Error('JS_AUDIT_ORIGINAL_PARSE');}
  try{outputAst=parse(output);}catch{throw new Error('JS_AUDIT_OUTPUT_PARSE');}
  if(replacements.length===0) {
    if(source!==output)throw new Error('JS_AUDIT_SOURCE_OUTPUT_MISMATCH');
    return {approved_count:0,output_spans:[]};
  }
  const sourceBytes=Buffer.from(source,'utf8'),outputBytes=Buffer.from(output,'utf8');
  const literals=new Map();
  walk(originalAst,(node,path)=>{
    if(node.type!=='Literal' && node.type!=='TemplateElement')return;
    literals.set(byte(source,node.start)+':'+byte(source,node.end),{node,path});
  });
  const ranges=[];
  for(let index=0;index<replacements.length;index++) {
    const replacement=replacements[index];
    if(!replacement || typeof replacement!=='object' || Array.isArray(replacement))
      throw new Error('JS_AUDIT_INVALID_REPLACEMENT');
    if(typeof replacement.expected!=='string' || typeof replacement.text!=='string')
      throw new Error('JS_AUDIT_INVALID_REPLACEMENT');
    if(typeof replacement.start!=='number' || !Number.isSafeInteger(replacement.start) || replacement.start<0 ||
        typeof replacement.end!=='number' || !Number.isSafeInteger(replacement.end) || replacement.end<0)
      throw new Error('JS_AUDIT_INVALID_RANGE');
    if(replacement.start>=replacement.end || replacement.end>sourceBytes.length)
      throw new Error('JS_AUDIT_INVALID_RANGE');
    ranges.push({index,start:replacement.start,end:replacement.end,node_kind:replacement.node_kind||'literal',
      expected:replacement.expected,text:replacement.text});
  }
  ranges.sort((a,b)=>a.start-b.start||a.end-b.end);
  for(let index=1;index<ranges.length;index++) {
    if(ranges[index].start===ranges[index-1].start && ranges[index].end===ranges[index-1].end)
      throw new Error('JS_AUDIT_DUPLICATE_RANGE');
    if(ranges[index].start<ranges[index-1].end)
      throw new Error('JS_AUDIT_OVERLAPPING_RANGES');
  }
  const approved=new Set(),pairs=[];
  for(const range of ranges) {
    const found=literals.get(range.start+':'+range.end);
    if(!found)throw new Error('JS_LOCATOR_MISMATCH');
    const value=textNodeValue(found.node,range.node_kind);
    if(value===null)throw new Error('JS_AUDIT_NON_LITERAL');
    if(value!==range.expected)throw new Error('JS_LOCATOR_MISMATCH');
    const path=JSON.stringify(found.path);
    approved.add(path);
    pairs.push({...range,path});
  }
  const outputLiterals=new Map();
  walk(outputAst,(node,path)=>{
    if((node.type==='Literal' && typeof node.value==='string') || node.type==='TemplateElement')
      outputLiterals.set(JSON.stringify(path),node);
  });
  for(const pair of pairs) {
    const node=outputLiterals.get(pair.path);
    if(!node || textNodeValue(node,pair.node_kind)===null)
      throw new Error('JS_AUDIT_PATH_MISMATCH');
    if(textNodeValue(node,pair.node_kind)!==pair.text)throw new Error('JS_AUDIT_VALUE_MISMATCH');
    const outputStart=byte(output,node.start),outputEnd=byte(output,node.end);
    if(!Number.isSafeInteger(outputStart) || !Number.isSafeInteger(outputEnd) ||
        outputStart<0 || outputStart>=outputEnd || outputEnd>outputBytes.length)
      throw new Error('JS_AUDIT_OUTPUT_RANGE');
    pair.output_start=outputStart;pair.output_end=outputEnd;
  }
  const outputOrder=[...pairs].sort((a,b)=>a.output_start-b.output_start);
  for(let index=1;index<outputOrder.length;index++) {
    if(outputOrder[index].output_start<outputOrder[index-1].output_end)
      throw new Error('JS_AUDIT_OUTPUT_OVERLAP');
  }
  const ordered=[...pairs].sort((a,b)=>a.start-b.start);
  for(let index=1;index<ordered.length;index++) {
    if(ordered[index].output_start<=ordered[index-1].output_start)
      throw new Error('JS_AUDIT_PATH_MISMATCH');
  }
  try {
    if(skeleton(originalAst,approved)!==skeleton(outputAst,approved))
      throw new Error('JS_AUDIT_STRUCTURE_MISMATCH');
  } catch(error) {
    if(error && error.message && error.message.startsWith('JS_AUDIT_'))throw error;
    throw new Error('JS_AUDIT_STRUCTURE_MISMATCH');
  }
  let originalCursor=0,outputCursor=0;
  for(const pair of ordered) {
    if(!sourceBytes.subarray(originalCursor,pair.start).equals(outputBytes.subarray(outputCursor,pair.output_start)))
      throw new Error('JS_AUDIT_BYTES_MISMATCH');
    originalCursor=pair.end;outputCursor=pair.output_end;
  }
  if(!sourceBytes.subarray(originalCursor).equals(outputBytes.subarray(outputCursor)))
    throw new Error('JS_AUDIT_BYTES_MISMATCH');
  const byIndex=new Map(pairs.map(pair=>[pair.index,pair]));
  const outputSpans=replacements.map((replacement,index)=>{
    const pair=byIndex.get(index);
    return {start:replacement.start,end:replacement.end,
      output_start:pair.output_start,output_end:pair.output_end};
  });
  return {approved_count:replacements.length,output_spans:outputSpans};
}
function execute(req) {
  if(typeof req.source!=='string')
    throw new Error(req.operation==='audit'?'JS_AUDIT_INVALID_SOURCE':'SOURCE_REQUIRED');
  const value=req.operation==='extract'?extract(req.source,req.object_path,req.scope_function,req.property_fields,req.static_text,req.literal_path):
    req.operation==='extract_spans'?extractSpans(req.source,req.spans):
    req.operation==='patch'?patch(req.source,req.replacements):
    req.operation==='audit'?audit(req.source,req.output,req.replacements):
    (()=>{throw new Error('UNKNOWN_OPERATION');})();
  return {ok:true,value};
}
const {isMainThread,parentPort,workerData,Worker}=require('node:worker_threads');
if(!isMainThread) {
  try{parentPort.postMessage(execute(workerData));}
  catch(e){parentPort.postMessage({ok:false,error:String(e.message)});}
} else {
  const LIMIT=16*1024*1024+65536;
  let buffered=Buffer.alloc(0),initial=null,thread=null,finished=false,framed=false,cancelling=false;
  function frameFromBytes(bytes) {
    const text=new TextDecoder('utf-8',{fatal:true}).decode(bytes),frame=JSON.parse(text);
    const ast=acorn.parseExpressionAt(text,0,{ecmaVersion:2022});
    walk(ast,node=>{
      if(node.type!=='ObjectExpression')return;
      const keys=new Set();
      for(const property of node.properties) {
        const key=property.key.value;
        if(keys.has(key))throw new Error('WORKER_PROTOCOL_INVALID');
        keys.add(key);
        if(node===ast && key==='protocol_version' && property.value.raw!=='1')throw new Error('WORKER_PROTOCOL_INVALID');
      }
    });
    return frame;
  }
  function valid(frame,type,expected) {
    const keys=type==='cancel'?['job_id','protocol_version','request_id','type']:['job_id','payload','protocol_version','request_id','type'];
    if(!frame || Array.isArray(frame) || typeof frame!=='object' || JSON.stringify(Object.keys(frame).sort())!==JSON.stringify(keys)
        || frame.protocol_version!==1 || frame.type!==type || typeof frame.request_id!=='string'
        || !/^[a-f0-9]{32}$/.test(frame.request_id) || typeof frame.job_id!=='string'
        || !frame.job_id.length || frame.job_id.length>128 || /[\x00\r\n]/.test(frame.job_id)
        || (type!=='cancel' && (!frame.payload || Array.isArray(frame.payload) || typeof frame.payload!=='object'))
        || (expected && ['protocol_version','request_id','job_id'].some(k=>frame[k]!==expected[k])))
      throw new Error('WORKER_PROTOCOL_INVALID');
    return frame;
  }
  function finish(body,code=0) {
    if(finished)return;finished=true;
    const value=framed?{protocol_version:1,request_id:initial.request_id,job_id:initial.job_id,type:'result',payload:body}:body;
    process.stdin.destroy();
    process.stdout.write(JSON.stringify(value)+'\n',()=>process.exit(code));
  }
  function fail(error) {finish({ok:false,error:String(error.message)},1);}
  function receive(frame) {
    if(!initial) {
      initial=valid(frame,'request');framed=true;
      thread=new Worker(__filename,{workerData:initial.payload});
      thread.once('message',body=>{if(!cancelling)finish(body,body.ok?0:1);});
      thread.once('error',error=>{if(!cancelling)fail(error);});
      thread.once('exit',code=>{if(!finished && !cancelling)fail(new Error('JS_WORKER_EXITED_'+code));});
    } else {
      valid(frame,'cancel',initial);
      if(cancelling)return;cancelling=true;
      thread.terminate().then(()=>finish({ok:false,cancelled:true,error:'WORKER_CANCELLED'},2),fail);
    }
  }
  process.stdin.on('data',chunk=>{
    if(finished)return;
    buffered=Buffer.concat([buffered,chunk]);
    if(buffered.length>LIMIT)return fail(new Error('INPUT_TOO_LARGE'));
    while(true) {
      const end=buffered.indexOf(10);if(end<0)break;
      const first=buffered.subarray(0,end);
      if(!initial) {
        let frame;
        try{frame=JSON.parse(first.toString('utf8'));}catch{break;}
        // Legacy one-shot input may contain whitespace/newlines; leave its
        // complete buffer for EOF. Framed callers always send compact lines.
        if(!frame || !Object.hasOwn(frame,'protocol_version'))break;
      }
      buffered=buffered.subarray(end+1);
      try{receive(frameFromBytes(first));}catch(e){fail(e);break;}
    }
  });
  process.stdin.on('end',()=>{
    if(finished)return;
    if(framed)return fail(new Error('WORKER_CONTROL_EOF'));
    try{
      if(buffered.length>16*1024*1024)throw new Error('INPUT_TOO_LARGE');
      finish(execute(JSON.parse(buffered.toString('utf8'))));
    }catch(e){fail(e);}
  });
  process.stdin.on('error',fail);
}
