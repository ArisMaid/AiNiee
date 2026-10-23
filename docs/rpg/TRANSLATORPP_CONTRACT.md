# Translator++ 8.8.9 transport contract

Implement ONLY `ModuleFolders/Infrastructure/GameAdapters/TranslatorPlusPlusClient.py`.
Use read/write/edit only. No grep/glob/todo, execution, web, agents, deletes, dependencies.
All architecture, integration, tests and delivery belong to Codex. Read this contract
only; all observed installed API facts are provided below. Stdlib Python only.

Class `TranslatorPlusPlusClient(endpoint='http://127.0.0.1:22883', timeout=60)`.
Only http with literal IPv4 loopback 127.0.0.1, valid explicit port (1..65535), no
userinfo/query/fragment/path accepted. Do not use DNS, environment proxies or redirects.
Use urllib with ProxyHandler({}) and a rejecting HTTPRedirectHandler. JSON UTF-8,
16 MiB request/32 MiB response bounds, timeout 1..300. Custom `TranslatorPlusPlusError`
extends ValueError. Reject non-dict response, HTTP/network error, malformed JSON,
and response.error with a bounded non-sensitive message (never echo script/text/body).
No requests to translation services. Version API support exact 8.8.9, fail closed
for other versions in probe; raw version in error is OK. No retries on mutations.

Installed official API facts:
- GET /api/tools returns {tools:[{name,...}],...}.
- POST /api/call body {tool,params}, response {tool,result,console,error}.
- POST /api/exec body {script}, response {returned,console,error}. `script` runs
  AsyncFunction with globals trans, nw, require, addonLoader, common, ui. It is
  NOT called `code`. Fixed trusted templates only; no user-supplied JavaScript method.
- `nw.App.manifest.version` is "8.8.9"; process.cwd() is install root.
- trans.openFromTransObj(data,{isNew:true}) loads {project:{files,...}}; sync method.
  trans.getSaveData() returns current full saved object. trans.project.projectId ID.
- cells.write tool args {fileId,row,col,value}, accepts col 1 (target) and 0 (source).
  Our wrapper MUST only allow row nonnegative integer (not bool) and target column 1.
- `addonLoader.addons.rmmv.RMMVGames(entryPoint,{})`, await game.toTrans(), returns
  project object containing gameEngine, files, projectId, cache. Native extraction
  side effects create staging under installation data/staging only; caller passes
  an isolated copy's entrypoint. No original game path permitted by high-level caller.
- `await addonLoader.addons.rmmv.exportToFolder(destination, undefined, {})` writes
  current RPG project from its retained staging. Caller owns separate output validation.
  Upstream can swallow parser errors, so operation success is NOT acceptance.

Required methods:
`discover()` GET returns raw dict after tools type validation.
`probe()` fixed exec returns {version,install_root,rpg_parser,open_data,snapshot};
  fields parser and open_data and snapshot are booleans from typeof checks. Version
  exact gate then require booleans true and project.info/cells.read/cells.write tools.
`open_data(data)` accepts dict with project dict and projectId nonempty str, fixed
  exec sets trans.openFromTransObj(PAYLOAD,{isNew:true}); returns {project_id:...}.
  Must JSON serialize payload into code as a JSON literal; never string interpolation
  of code or unquoted paths. It is OK for T++ to add metadata or empty trailing row.
`snapshot(expected_project_id=None)` fixed exec verifies optional current ID then
  returns trans.getSaveData(); ensure result dict with project dict.
`write_translation(file_id,row,text,expected_project_id)` fixed exec verifies exact
  project ID, existence and valid existing row, rejects source column mutation,
  sets row[1] to text, trans.gridIsModified(true), returns {written:true}.
  Explicitly validate Python types before request. Do not evaluate translations.
`extract_rpg(entry_point)` requires absolute .html str/path, no NUL; fixed exec:
  const game=new addonLoader.addons.rmmv.RMMVGames(PATH,{});
  const project=await game.toTrans(); trans.openFromTransObj({project},{isNew:true});
  return trans.getSaveData(); Return full snapshot dict. Do not validate original
  path boundary here; high-level service will only pass a generated private copy.
`export_rpg(destination,expected_project_id)` requires absolute path/no NUL,
  fixed exec checks trans.project.projectId; const fs=require('fs'); if path exists
  throw Error('DESTINATION_EXISTS'); await addonLoader.addons.rmmv.exportToFolder(PATH,
  undefined,{}); return {output_path:PATH,project_id:...}; No directory removal.

Each exec wraps console.log/warn/info/debug suppression in try/finally because the
upstream API captures full source data in console arrays. Never suppress errors
out of returned.error; enforce response error gate. Transport method `_execute`
private only, no generic CLI script endpoint or model-accessible arbitrary exec.
Use clear types, not a generic framework. No tests by worker; Codex supplies tests.
