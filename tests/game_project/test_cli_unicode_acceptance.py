"""Chinese CLI errors remain UTF-8 under a legacy parent encoding."""
import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path


class CliUnicodeAcceptance(unittest.TestCase):
    def test_error_json_is_utf8_with_cp936_parent_configuration(self):
        repo=Path(__file__).resolve().parents[2];base=repo/'work/acceptance'
        base.mkdir(parents=True,exist_ok=True)
        root=Path(tempfile.mkdtemp(prefix='unicode-cli-',dir=base))
        missing=root/'未创建工程'
        env=dict(os.environ,PYTHONIOENCODING='cp936')
        for entry in [['RpgApp.py','--cli'],['-m','Tools.rpg_pipeline']]:
            with self.subTest(entry=entry):
                result=subprocess.run([sys.executable,*entry,'summary','--project',str(missing)],
                    cwd=repo,env=env,capture_output=True,timeout=10)
                self.assertEqual(result.returncode,1)
                payload=json.loads(result.stderr.decode('utf-8'))
                self.assertIn('未创建工程',payload['message'])


if __name__=='__main__':unittest.main()
