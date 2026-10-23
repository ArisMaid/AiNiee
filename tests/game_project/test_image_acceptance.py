"""Codex-owned image pipeline tests; fixtures are retained for audit."""
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import subprocess

from PIL import Image,ImageDraw
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
import test_adapter_acceptance as fixtures
from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
from ModuleFolders.Service.GameProject.BuildService import BuildService,file_hash
from ModuleFolders.Service.GameProject import ImageService as images


def png(image):
    out=io.BytesIO();image.save(out,format='PNG');return out.getvalue()


def font_bytes():
    chars='日本中文AB测试开始继续选项'
    names={ord(c):'u'+str(ord(c)) for c in chars}
    order=['.notdef',*names.values()]
    fb=FontBuilder(1024,isTTF=True);fb.setupGlyphOrder(order);fb.setupCharacterMap(names)
    glyphs={}
    for name in order:
        pen=TTGlyphPen(None);pen.moveTo((80,0));pen.lineTo((500,0));pen.lineTo((500,650));pen.lineTo((80,650));pen.closePath()
        glyphs[name]=pen.glyph()
    fb.setupGlyf(glyphs);fb.setupHorizontalMetrics({n:(600,0) for n in order});fb.setupHorizontalHeader(ascent=800,descent=-200)
    fb.setupNameTable({'familyName':'ImageFixture','styleName':'Regular'});fb.setupOS2();fb.setupPost();fb.setupMaxp()
    out=io.BytesIO();fb.save(out);return out.getvalue()


class ImageAcceptance(unittest.TestCase):
    setUp=fixtures.AdapterAcceptance.setUp
    write=fixtures.AdapterAcceptance.write

    def test_codec_roundtrip_and_render_boundaries(self):
        from ModuleFolders.Service.GameProject.ImageCodec import decode_image,encode_image,render_png
        source=png(Image.new('RGBA',(180,70),(10,20,30,120)))
        key='00112233445566778899aabbccddeeff'
        for suffix in ('.png','.png_','.rpgmvp'):
            with self.subTest(suffix=suffix):
                encoded=encode_image(source,suffix,key)
                decoded,info=decode_image(encoded,suffix,key)
                self.assertEqual(decoded,source);self.assertEqual((info['width'],info['height']),(180,70))
        with self.assertRaises(ValueError):decode_image(b'bad','.png_ ',key)
        with self.assertRaises(ValueError):decode_image(encode_image(source,'.png_',key),'.png_','f'*32)
        overlay={'box':[20,15,140,40],'text':'中文','font_size':24,'color':[255,255,255,255],'align':'center'}
        result=render_png(source,[overlay],font_bytes())
        a=Image.open(io.BytesIO(source));b=Image.open(io.BytesIO(result))
        self.assertEqual(b.size,a.size);self.assertEqual(b.mode,'RGBA');self.assertNotEqual(a.tobytes(),b.tobytes())
        for y in range(70):
            for x in range(180):
                if not(20<=x<160 and 15<=y<55):self.assertEqual(a.getpixel((x,y)),b.getpixel((x,y)))
        for invalid in [dict(overlay,text='缺字'),dict(overlay,text='中'*100),dict(overlay,box=[170,0,40,20]),dict(overlay,font_size=True)]:
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):render_png(source,[invalid],font_bytes())
        with self.assertRaises(ValueError):render_png(source,[overlay,overlay],font_bytes())

    def test_confirmation_approval_build_and_stale_translation(self):
        from ModuleFolders.Service.GameProject.ImageCodec import encode_image,decode_image
        key='00112233445566778899aabbccddeeff'
        self.write('System',{'gameTitle':'テスト','advanced':{'gameId':1},'encryptionKey':key})
        image=Image.new('RGBA',(180,70),(10,20,30,120));ImageDraw.Draw(image).rectangle((20,15,159,54),fill='red')
        original=png(image);(self.root/'img').mkdir();asset=self.root/'img/Button.png_'
        asset.write_bytes(encode_image(original,'.png_',key));original_hash=file_hash(asset)
        project=self.root.parent/(self.root.name+'-image-project')
        with GameProjectService.create(self.root,project) as service:
            service.extract();store=service.store
            before=store.metadata()['dataset_revision']
            result=images.confirm_regions(store,'img/Button.png_',original_hash,[{'box':[20,15,140,40],'text':'日本','font_size':24}])
            uid=result['unit_ids'][0]
            self.assertEqual(store.metadata()['dataset_revision'],before+1)
            self.assertEqual(store.metadata()['extraction_stats']['unit_count'],len(store.units()))
            self.assertEqual(store.metadata()['extraction_stats']['occurrence_count'],
                sum(len(unit.occurrences) for unit in store.units()))
            service.extract();self.assertIsNotNone(store.unit(uid))
            service.import_translations({uid:'中文'})
            clean=Image.open(io.BytesIO(original));ImageDraw.Draw(clean).rectangle((20,15,159,54),fill=(10,20,30,120))
            clean_path=project/'clean.png';clean_path.write_bytes(png(clean));font_path=project/'font.ttf';font_path.write_bytes(font_bytes())
            images.prepare_base(store,'img/Button.png_',clean_path,font_path)
            candidate=images.render_candidate(store,'img/Button.png_')
            with self.assertRaisesRegex(ValueError,'IMAGE_VISUAL_APPROVAL_REQUIRED'):
                service.build(self.root.parent/(self.root.name+'-images-output'),test=True)
            images.approve_candidate(store,'img/Button.png_',candidate['sha256'])
            build=service.build(self.root.parent/(self.root.name+'-images-output'),test=True)
            self.assertTrue(BuildService.verify(build['output_path'])['passed'])
            out=Path(build['output_path'])/'img/Button.png_'
            decoded,info=decode_image(out.read_bytes(),'.png_',key)
            self.assertEqual((info['width'],info['height']),(180,70));self.assertNotEqual(decoded,original)
            self.assertEqual(file_hash(asset),original_hash)
            service.import_translations({uid:'测试'})
            with self.assertRaisesRegex(ValueError,'IMAGE_VISUAL_APPROVAL_REQUIRED'):
                service.build(self.root.parent/(self.root.name+'-images-output'),test=True)

    def test_invalid_regions_and_outside_clean_edit_are_rejected(self):
        (self.root/'img').mkdir();asset=self.root/'img/test.png';asset.write_bytes(png(Image.new('RGBA',(100,60),'white')))
        project=self.root.parent/(self.root.name+'-image-guards')
        with GameProjectService.create(self.root,project) as service:
            service.extract();store=service.store;sha=file_hash(asset)
            before=store.metadata()['dataset_revision']
            with self.assertRaisesRegex(ValueError,'IMAGE_BOX_OVERLAP'):
                images.confirm_regions(store,'img/test.png',sha,[{'text':'A','box':[0,0,50,30]},{'text':'B','box':[40,0,40,30]}])
            self.assertEqual(store.metadata()['dataset_revision'],before)
            with self.assertRaisesRegex(ValueError,'IMAGE_CONFIRM_SOURCE_MISMATCH'):
                images.confirm_regions(store,'img/test.png','0'*64,[{'text':'A','box':[0,0,50,30]}])
            images.confirm_regions(store,'img/test.png',sha,[{'text':'A','box':[0,0,50,30]}])
            bad=project/'bad.png';bad.write_bytes(png(Image.new('RGBA',(100,60),'black')))
            font=project/'font.ttf';font.write_bytes(font_bytes())
            with self.assertRaisesRegex(ValueError,'IMAGE_BASE_CHANGED_OUTSIDE_REGIONS'):
                images.prepare_base(store,'img/test.png',bad,font)

    def test_ocr_protocol_and_environment_are_bounded(self):
        from ModuleFolders.Service.GameProject.ImageCodec import ocr_png,decode_image
        source=png(Image.new('RGBA',(100,60),'white'))
        tool=self.root.parent/(self.root.name+'-OCR 工具');tool.mkdir()
        exe=tool/'tesseract.exe';exe.write_bytes(b'fixture-not-executed')
        data=tool/'tessdata';data.mkdir()
        for lang in ['jpn','eng']:(data/(lang+'.traineddata')).write_bytes(b'fixture')
        header=b'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
        row=b'5\t1\t1\t1\t1\t1\t5\t5\t50\t20\t96.5\tSTART\n'
        with patch.dict('os.environ',{'OPENAI_API_KEY':'DO-NOT-FORWARD','HTTP_PROXY':'DO-NOT-FORWARD'}):
            with patch('ModuleFolders.Service.GameProject.ImageCodec.run_owned_process',return_value=subprocess.CompletedProcess([],0,header+row,b'')) as run:
                result=ocr_png(source,exe,data)
                self.assertEqual(result['regions'][0]['text'],'START')
                self.assertNotIn('OPENAI_API_KEY',run.call_args.kwargs['env'])
                self.assertNotIn('HTTP_PROXY',run.call_args.kwargs['env'])
                self.assertEqual(run.call_args.args[0][1:3],['stdin','stdout'])
        with patch('ModuleFolders.Service.GameProject.ImageCodec.run_owned_process',side_effect=subprocess.TimeoutExpired('fixture',1)),self.assertRaisesRegex(ValueError,'IMAGE_OCR_TIMEOUT'):
            ocr_png(source,exe,data,timeout=1)
        with patch('ModuleFolders.Service.GameProject.ImageCodec.run_owned_process',return_value=subprocess.CompletedProcess([],0,header+row.replace(b'\t50\t20\t',b'\t500\t20\t'),b'')),self.assertRaisesRegex(ValueError,'OUT_OF_BOUNDS'):
            ocr_png(source,exe,data)
        # Corrupt only an IDAT CRC; the compressed pixels still decode.
        corrupted=bytearray(source);at=source.index(b'IDAT');size=int.from_bytes(source[at-4:at],'big');corrupted[at+4+size]^=1
        with self.assertRaisesRegex(ValueError,'IMAGE_CORRUPT'):decode_image(bytes(corrupted),'.png')


if __name__=='__main__':unittest.main()
