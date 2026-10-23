from pathlib import Path
import os
import json
import sys
from PyInstaller.utils.hooks import collect_data_files,collect_submodules
from PyInstaller.utils.hooks.qt import pyqt5_library_info
import PyQt5
import importlib.metadata

# Qt 5.15 wheels return lossy paths through QLibraryInfo in Unicode Windows venvs.
# Patch only this build's hook metadata; installed Qt/PyInstaller files stay intact.
qt_location=pyqt5_library_info.location
qt_prefix=Path(PyQt5.__file__).parent/'Qt5'
old_prefix=qt_location['PrefixPath']
for key,value in list(qt_location.items()):
    if isinstance(value,str) and value.startswith(old_prefix):
        qt_location[key]=str(qt_prefix)+value[len(old_prefix):]
pyqt5_library_info.qt_inside_package=True
pyqt5_library_info.qt_lib_dir=qt_prefix/'bin'

root=Path(SPECPATH).parent
layout=json.loads((root/'Tools/rpg_paths.json').read_text(encoding='utf-8'))
workspace=Path(os.environ.get('RPG_WORKSPACE_ROOT',root.parent))
acorn=workspace/layout['js']/'node_modules/acorn'
if not acorn.is_dir():acorn=root/'.tools/js/node_modules/acorn'
datas=[]
for name in ['ExternalTools','GameProfiles','Localization','Logo','platforms','Prompt','Regex','Version','RpgRuntime','Models/tiktoken']:
    folder=root/'Resource'/name
    if folder.exists():datas.append((str(folder),'Resource/'+name))
datas += [(str(root/'ModuleFolders/Infrastructure/GameAdapters/JsWorker/worker.cjs'),
           'ModuleFolders/Infrastructure/GameAdapters/JsWorker'),
          (str(acorn),'runtime/js/node_modules/acorn'),
          (str(root/'LICENSE'),'licenses/AiNiee')]
datas += collect_data_files('fontTools')
datas += collect_data_files('opencc')
datas += collect_data_files('mediapipe')
for dist in importlib.metadata.distributions():
    dist_name=dist.metadata.get('Name','unknown').replace('/','_')
    for entry in dist.files or []:
        low=str(entry).lower()
        if '.dist-info/' in low and any(part.startswith(('license','copying','notice')) for part in Path(low).parts):
            origin=dist.locate_file(entry)
            if origin.is_file():datas.append((str(origin),'licenses/python/'+dist_name+'/'+str(Path(entry).parent)))
datas.append((str(root/'docs/rpg/THIRD_PARTY_NOTICES.md'),'licenses'))
datas.append((str(root/'docs/rpg/node-license.txt'),'licenses'))
python_license=Path(sys.base_prefix)/'LICENSE.txt'
if not python_license.is_file():raise RuntimeError('CPython redistribution license not found')
datas.append((str(python_license),'licenses/CPython'))
node=os.environ.get('RPG_BUILD_NODE',r'C:\Program Files\nodejs\node.exe')
a=Analysis([str(root/'RpgApp.py')],pathex=[str(root)],
    binaries=[(node,'runtime')],datas=datas,
    hiddenimports=collect_submodules('tiktoken_ext')+['Tools.rpg_pipeline','Tools.rpg_selfcheck',
        'ModuleFolders.Infrastructure.GameAdapters.BackendWorker'],
    excludes=['torch','tensorflow','spacy','babeldoc','magika','onnxruntime','pytest','scipy'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='AiNieeRPG',console=True,disable_windowed_traceback=False)
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='AiNieeRPG')
