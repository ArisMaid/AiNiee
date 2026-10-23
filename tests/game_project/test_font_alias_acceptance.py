"""Independent font alias process/load-order and output acceptance."""
import json,shutil,subprocess,unittest


class FontAliasAcceptance(unittest.TestCase):
    def runtime(self,aliases=None,file='AiNiee-Simplified.ttf'):
        from ModuleFolders.Service.GameProject.FontAliasRuntime import build_runtime
        return build_runtime(['HSJP-Regular','HSJP-Bold'] if aliases is None else aliases,file)

    def node(self,body):
        node=shutil.which('node')
        if not node:self.skipTest('Node unavailable')
        fixture=r'''
const vm=require('vm');const assert=require('assert');
const hooks={};const target={calls:[],_urls:{},load(family,file,...rest){this.calls.push([family,file,...rest]);return 'returned';}};
const sandbox={document:{addEventListener:(t,f,c)=>{assert.strictEqual(c,true);hooks.doc=f;},removeEventListener:()=>{hooks.doc=null;}},
 addEventListener:(t,f)=>{hooks.win=f;},removeEventListener:()=>{hooks.win=null;},console};sandbox.window=sandbox;
const context=vm.createContext(sandbox);
const run=source=>vm.runInContext(source,context);
'''
        source=fixture+'\nconst runtime='+json.dumps(self.runtime().decode())+';\n'+body
        result=subprocess.run([node,'-e',source],capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))

    def test_immediate_and_idempotent_mapping_preserves_other_calls(self):
        self.node(r'''
sandbox.FontManager=target;run(runtime);const wrapper=target.load;const state=sandbox.AiNieeFontAliasOverride;
assert.strictEqual(state.installed,true);assert.strictEqual(target.load('HSJP-Regular','old.woff',5),'returned');
target.load('rmmz-mainfont','other.ttf',6);assert.deepStrictEqual(target.calls,[['HSJP-Regular','AiNiee-Simplified.ttf',5],['rmmz-mainfont','other.ttf',6]]);
assert.strictEqual(state.loads['HSJP-Regular'],1);run(runtime);assert.strictEqual(target.load,wrapper);assert.strictEqual(sandbox.AiNieeFontAliasOverride,state);
assert.throws(()=>run(runtime.replaceAll('AiNiee-Simplified.ttf','other.ttf')));
''')

    def test_deferred_capture_hook_and_late_load_rejection(self):
        self.node(r'''
run(runtime);assert.strictEqual(sandbox.AiNieeFontAliasOverride.installed,false);assert.strictEqual(typeof hooks.doc,'function');
sandbox.FontManager=target;hooks.doc({target:{tagName:'SCRIPT'}});assert.strictEqual(sandbox.AiNieeFontAliasOverride.installed,true);
assert.strictEqual(hooks.doc,null);target.load('HSJP-Bold','old.woff');assert.strictEqual(target.calls[0][1],'AiNiee-Simplified.ttf');
''')
        self.node(r'''
target._urls['HSJP-Regular']='fonts/original.woff';sandbox.FontManager=target;
assert.throws(()=>run(runtime));
''')

    def test_bad_aliases_and_filenames_rejected(self):
        for aliases in [None,[],['HSJP-Regular','HSJP-Regular'],['a,b'],['a b'],['中文'],[1],['a']*17]:
            with self.subTest(aliases=aliases),self.assertRaises(ValueError):
                from ModuleFolders.Service.GameProject.FontAliasRuntime import build_runtime
                build_runtime(aliases,'font.ttf')
        for file in ['../font.ttf','font.ttf:stream','C:/font.ttf','a\\font.ttf','font.exe','font\n.ttf','../font.ttf','x..ttf']:
            with self.subTest(file=file),self.assertRaises(ValueError):self.runtime(file=file)
        self.assertEqual(self.runtime(),self.runtime())


if __name__=='__main__':unittest.main()
