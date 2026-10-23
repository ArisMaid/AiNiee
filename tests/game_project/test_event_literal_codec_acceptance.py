"""Codex-owned grammar, no-op and engine-expression safety tests."""
import json,shutil,subprocess,unittest


class EventLiteralCodecAcceptance(unittest.TestCase):
    def codec(self):
        from ModuleFolders.Domain.GameProject import EventLiteralCodec
        return EventLiteralCodec

    def test_grammar_and_raw_noop_spelling(self):
        codec=self.codec()
        self.assertEqual(codec.CODEC_ID,'event-js-json-string-v1')
        for raw in ['""','"日本語"',' \t"\\u65e5\\u672c"\r\n','"quote\\\"\\\\\\n"']:
            with self.subTest(raw=raw):
                decoded=codec.decode_literal(raw)
                self.assertEqual(decoded,json.loads(raw))
                self.assertEqual(codec.encode_literal(decoded,original=raw),raw)
        for bad in [None,False,3,b'"text"',"'text'",'`text`','("text")','"text"+"more"',
                '"text";globalThis.pwned=1','/*comment*/"text"','["text"]','{}','null','true','0',
                'NaN','"\\x41"','"actual\nnewline"','"\\ud800"','"\udfff"']:
            with self.subTest(bad=repr(bad)),self.assertRaises(ValueError):codec.decode_literal(bad)
        with self.assertRaises(ValueError):codec.encode_literal('valid',original='invalid')
        class PretendsEqual:
            def __eq__(self,other):return True
        with self.assertRaises(ValueError):codec.encode_literal(PretendsEqual(),original='"text"')

    def test_generated_literals_roundtrip_and_never_execute_payload(self):
        codec=self.codec()
        examples=['','简体中文','😀前置','引号"和反斜杠\\','换行\n制表\tNUL\x00',
            '\u2028\u2029','";globalThis.pwned=1;//','${globalThis.pwned=1}','</script>']
        encoded=[codec.encode_literal(text) for text in examples]
        self.assertEqual([codec.decode_literal(value) for value in encoded],examples)
        self.assertNotIn('\u2028',encoded[5]);self.assertNotIn('\u2029',encoded[5])
        self.assertIn('\\u2028',encoded[5]);self.assertIn('\\u2029',encoded[5])
        node=shutil.which('node')
        if not node:self.skipTest('Node runtime unavailable')
        script=r'''const vm=require('vm');let input='';process.stdin.on('data',x=>input+=x);process.stdin.on('end',()=>{
const values=JSON.parse(input).map(code=>{const c={pwned:0};const text=vm.runInNewContext('('+code+')',c,{timeout:50});if(c.pwned!==0)throw Error('code executed');return text;});process.stdout.write(JSON.stringify(values));});'''
        result=subprocess.run([node,'-e',script],input=json.dumps(encoded).encode(),capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
        self.assertEqual(json.loads(result.stdout),examples)

    def test_bounds_unicode_and_wrong_types_fail_without_truncation(self):
        codec=self.codec();limit=codec.MAX_LITERAL_BYTES
        exact='a'*(limit-2)
        self.assertEqual(len(codec.encode_literal(exact).encode()),limit)
        self.assertEqual(codec.decode_literal(codec.encode_literal(exact)),exact)
        for text in ['a'*(limit-1),'中'*limit,'\x00'*(limit//2),'\ud800',False,None,b'text']:
            with self.subTest(type=type(text).__name__),self.assertRaises(ValueError):codec.encode_literal(text)
        with self.assertRaises(ValueError):codec.decode_literal(' '*(limit+1)+'""')


if __name__=='__main__':unittest.main()
