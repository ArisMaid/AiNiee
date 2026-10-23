import json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import threading
import unittest

from ModuleFolders.Infrastructure.GameAdapters.TranslatorPlusPlusClient import (
    TranslatorPlusPlusClient,TranslatorPlusPlusError)


class TranslatorPlusPlusTransport(unittest.TestCase):
    def test_endpoint_boundary(self):
        for endpoint in ['http://localhost:22883','http://192.168.0.1:22883',
                         'https://127.0.0.1:22883','http://user@127.0.0.1:22883',
                         'http://127.0.0.1:22883/','http://127.0.0.1:22883?x',
                         'http://127.0.0.1','http://127.0.0.1:0','http://[::1]:22883']:
            with self.subTest(endpoint=endpoint),self.assertRaises(TranslatorPlusPlusError):
                TranslatorPlusPlusClient(endpoint)
        for timeout in [True,0,301,float('nan')]:
            with self.assertRaises(TranslatorPlusPlusError):TranslatorPlusPlusClient(timeout=timeout)

    def test_redirect_and_upstream_errors_do_not_escape(self):
        requests=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                requests.append(self.path)
                if len(requests)==1:
                    self.send_response(302);self.send_header('Location','http://192.0.2.1:7/private');self.end_headers()
                else:
                    body=json.dumps({'error':{'message':'PRIVATE GAME TEXT'}}).encode()
                    self.send_response(200);self.end_headers();self.wfile.write(body)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            client=TranslatorPlusPlusClient(f'http://127.0.0.1:{server.server_port}')
            with self.assertRaisesRegex(TranslatorPlusPlusError,'redirect'):client.discover()
            self.assertEqual(requests,['/api/tools'])
            with self.assertRaises(TranslatorPlusPlusError) as rejected:client.discover()
            self.assertNotIn('PRIVATE',str(rejected.exception))
            self.assertEqual(len(requests),2)  # Neither operation was retried.
        finally:server.shutdown();server.server_close();thread.join(2)

    def test_wrong_version_and_missing_identity_are_rejected(self):
        client=TranslatorPlusPlusClient()
        client._exec_script=lambda script:{'version':'9.0.0'}
        with self.assertRaisesRegex(TranslatorPlusPlusError,'unsupported'):client.probe()
        client._exec_script=lambda script:{'project_id':'unexpected'}
        with self.assertRaises(TranslatorPlusPlusError):client.open_data({'project':{'projectId':'expected'}})
        with self.assertRaises(TranslatorPlusPlusError):client.write_translation(0,0,'字','expected')
        with self.assertRaises(TranslatorPlusPlusError):client.write_translation('file',True,'字','expected')
