"""Pinned, on-demand tools. Installs live outside source and never change game data."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
import zipfile

from ModuleFolders.Config.FilePathConfig import resource_path, repo_root, user_data_root


class ToolError(ValueError):
    pass


class Cancelled(ToolError):
    pass


def _sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _run(args, timeout=120, cwd=None):
    result = subprocess.run([str(a) for a in args], cwd=cwd, capture_output=True,
        timeout=timeout, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise ToolError(f'工具命令失败（退出码 {result.returncode}）；请检查安装目录或重新配置。')
    return result.stdout.decode('utf-8', errors='replace')


def _member(name):
    name = name.replace('\\', '/')
    p = PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or ':' in name or '\x00' in name:
        raise ToolError('压缩包包含不安全路径，已停止解压。')
    return p


def _no_links(root):
    # Do not descend through a junction even when an existing installation is selected.
    for current, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            info = (Path(current) / name).lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ToolError('工具目录包含链接或联接点，请选择普通安装目录。')


class ExternalTools:
    def __init__(self):
        self.catalog = json.loads(resource_path('ExternalTools', 'catalog.json').read_text(encoding='utf-8'))
        source = not getattr(sys, 'frozen', False)
        default_home = repo_root().parent / '外部工具' if source else user_data_root() / 'tools'
        default_config = (repo_root().parent / '开发记录' / '工具配置' / 'external-tools.json'
            if source else user_data_root() / 'external-tools.json')
        self.home = Path(os.environ.get('AINIEE_EXTERNAL_TOOLS_HOME', default_home)).expanduser().absolute()
        self.config = Path(os.environ.get('AINIEE_EXTERNAL_TOOLS_CONFIG', default_config)).expanduser().absolute()

    def _settings(self):
        if not self.config.exists():
            return {}
        try:
            data = json.loads(self.config.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except (ValueError, OSError) as exc:
            raise ToolError(f'工具配置无法读取，请保留文件并检查：{self.config}') from exc

    def _candidates(self, tool):
        spec = self.catalog['tools'][tool]
        configured = self._settings().get(tool)
        if configured:
            # An explicitly selected broken installation must not silently switch to another.
            return [Path(configured)]
        base = self.home / spec['folder']
        candidates = [base / spec['version'], base]
        if tool == 'translatorpp':
            candidates.insert(0, base / spec['version'] / 'app' / 'Translator++')
        elif tool == 'ocr':
            candidates.insert(0, base / ('tesseract-' + spec['version']) / 'app')
        elif tool == 'stev' and not getattr(sys, 'frozen', False):
            candidates.append(repo_root() / 'StevExtraction')
        return candidates

    def validate(self, tool, selected):
        spec = self.catalog['tools'][tool]
        root = Path(selected).expanduser().absolute()
        if root.is_file():
            root = root.parent
        options = [root, root / 'Translator++', root / 'app' / 'Translator++', root / 'app']
        entry = {'translatorpp': 'Translator++.exe', 'ocr': 'tesseract.exe'}.get(tool)
        root = next((p for p in options if (p / (entry or spec['required'][0])).is_file()), root)
        if not root.is_dir():
            raise ToolError('未找到工具目录，请下载配置或选择已有安装。')
        if entry and not (root / entry).is_file():
            raise ToolError(f'目录中缺少 {entry}。')
        if tool == 'translatorpp':
            try:
                version = json.loads((root / 'package.json').read_text(encoding='utf-8'))['version']
            except (OSError, ValueError, KeyError) as exc:
                raise ToolError('无法识别 Translator++ 安装。') from exc
            if version != spec['version']:
                raise ToolError('此桥接仅支持 Translator++ ' + spec['version'] + '，请使用一键下载配置。')
        elif tool == 'ocr':
            if not all((root / 'tessdata' / (lang + '.traineddata')).is_file() for lang in ('jpn', 'eng')):
                raise ToolError('缺少 jpn/eng 识别数据，请使用一键下载配置。')
            if 'tesseract v5.4.0.20240606' not in _run([root / entry, '--version'], timeout=15):
                raise ToolError('当前 OCR 仅验收 Tesseract 5.4.0，请使用一键下载配置。')
        else:
            for name, expected in spec['entry_sha256'].items():
                path = root / name
                if not path.is_file() or hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest() != expected:
                    raise ToolError(f'{spec["label"]} 入口与支持的固定版本不符：{name}；请使用一键下载配置。')
        return root.resolve()

    def status(self, tool):
        spec = self.catalog['tools'][tool]
        error = '尚未配置'
        try:
            candidates = self._candidates(tool)
        except ToolError as exc:
            return dict(tool=tool, ready=False, path='', version=spec['version'], message=str(exc))
        for path in candidates:
            if not path.exists():
                continue
            try:
                root = self.validate(tool, path)
                return dict(tool=tool, ready=True, path=str(root), version=spec['version'], message='已就绪')
            except (ToolError, OSError, subprocess.SubprocessError) as exc:
                error = str(exc)
        return dict(tool=tool, ready=False, path='', version=spec['version'], message=error)

    def path(self, tool):
        status = self.status(tool)
        if not status['ready']:
            raise ToolError(status['message'] + '；请打开“外部工具管理”。')
        return Path(status['path'])

    def select(self, tool, path):
        # Trust is explicit when choosing an existing program; still reject linked trees.
        root = Path(path).expanduser().absolute()
        _no_links(root if root.is_dir() else root.parent)
        root = self.validate(tool, path)
        data = self._settings()
        data[tool] = str(root)
        self.config.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config.with_name(self.config.name + '.' + uuid.uuid4().hex + '.tmp')
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(self.config)
        return self.status(tool)

    @staticmethod
    def _check(cancel):
        if cancel.is_set():
            raise Cancelled('已取消；已下载文件和诊断现场保留，可稍后重试。')

    def _download(self, spec, name, progress, cancel):
        cache = self.home / '下载缓存' / '7.2.4.1'
        cache.mkdir(parents=True, exist_ok=True)
        target = cache / name
        self._check(cancel)
        if target.is_file() and _sha(target) == spec['sha256']:
            progress('复用已校验下载：' + name)
            return target
        partial = cache / (name + '.' + uuid.uuid4().hex + '.part')
        progress('开始下载：' + name)
        try:
            request = urllib.request.Request(spec['url'], headers={'User-Agent': 'AiNieeRPG/7.2.4.1'})
            with urllib.request.urlopen(request, timeout=30) as response, partial.open('xb') as output:
                total = int(response.headers.get('Content-Length', 0))
                count = 0
                last = 0.0
                while True:
                    self._check(cancel)
                    block = response.read(256 * 1024)
                    if not block:
                        break
                    output.write(block)
                    count += len(block)
                    if time.monotonic() - last > .5:
                        progress(f'下载 {name}：{count // 1048576} / {total // 1048576 if total else "?"} MiB')
                        last = time.monotonic()
        except Cancelled:
            raise
        except Exception as exc:
            raise ToolError('下载失败，请检查网络后重试，或选择已有安装；现场：' + str(partial)) from exc
        if _sha(partial) != spec['sha256']:
            raise ToolError('下载文件 SHA-256 不符，已停止配置；文件保留：' + str(partial))
        partial.replace(target)
        return target

    def _archiver(self, progress, cancel):
        spec = self.catalog['archiver']
        dest = self.home / '解压工具' / spec['version']
        matches = list(dest.rglob('7z.exe')) if dest.exists() else []
        if matches and (matches[0].parent / '7z.dll').is_file():
            return matches[0]
        package = self._download(spec, 'archiver.msi', progress, cancel)
        stage = self.home / '安装现场' / ('7zip-' + uuid.uuid4().hex)
        stage.mkdir(parents=True)
        progress('正在准备解压组件（仅展开文件，不安装系统服务）…')
        log = stage / 'extract.log'
        _run(['msiexec.exe', '/a', package, '/qn', 'TARGETDIR=' + str(stage),
            'REBOOT=ReallySuppress', '/L*v', log], timeout=180)
        self._check(cancel)
        _no_links(stage)
        matches = list(stage.rglob('7z.exe'))
        if len(matches) != 1 or not (matches[0].parent / '7z.dll').is_file():
            raise ToolError('无法展开解压组件；请保留安装现场并选择已有工具安装。')
        relative = matches[0].relative_to(stage)
        dest.parent.mkdir(parents=True, exist_ok=True)
        stage.rename(dest)
        return dest / relative

    def install(self, tool, progress=lambda message: None, cancel=None):
        if os.name != 'nt':
            raise ToolError('一键配置目前支持 Windows x64。')
        cancel = cancel or threading.Event()
        spec = self.catalog['tools'][tool]
        dest = self.home / spec['folder'] / spec['version']
        # Existing valid installs are selected, never overwritten or "repaired" in place.
        if dest.exists():
            return self.select(tool, dest)
        package = self._download(spec, tool + ('.zip' if spec['kind'] == 'zip' else '.7z' if tool == 'translatorpp' else '.exe'), progress, cancel)
        stage = self.home / '安装现场' / (tool + '-' + uuid.uuid4().hex)
        stage.mkdir(parents=True)
        progress('正在解压和检查 ' + spec['label'] + '…')
        if spec['kind'] == 'zip':
            prefix = spec['archive_prefix']
            expanded = 0
            with zipfile.ZipFile(package) as archive:
                for member in archive.infolist():
                    self._check(cancel)
                    _member(member.filename)
                    if stat.S_ISLNK(member.external_attr >> 16):
                        raise ToolError('压缩包不允许符号链接。')
                    if not member.filename.startswith(prefix) or member.is_dir():
                        continue
                    relative = _member(member.filename[len(prefix):])
                    expanded += member.file_size
                    if expanded > 2 * 1024**3:
                        raise ToolError('压缩包展开大小超过限制。')
                    output = stage.joinpath(*relative.parts)
                    output.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source, output.open('xb') as target:
                        while block := source.read(1024 * 1024):
                            self._check(cancel)
                            target.write(block)
        else:
            archiver = self._archiver(progress, cancel)
            password = ['-pDreamsavior'] if tool == 'translatorpp' else []  # Public upstream archive password.
            listing = _run([archiver, 'l', '-slt', '-sccUTF-8', *password, package], timeout=180)
            entries = listing.split('----------', 1)[-1]
            for line in entries.splitlines():
                if line.startswith('Path = '):
                    _member(line[7:])
                if line.startswith(('Symbolic Link = ', 'Hard Link = ')):
                    raise ToolError('压缩包不允许链接。')
            self._check(cancel)
            _run([archiver, 'x', '-y', '-sccUTF-8', *password, '-o' + str(stage), package], timeout=600)
        self._check(cancel)
        _no_links(stage)
        root = stage / 'Translator++' if tool == 'translatorpp' else stage
        if tool == 'ocr':
            language = self._download(spec['language'], 'jpn.traineddata', progress, cancel)
            (root / 'tessdata').mkdir(exist_ok=True)
            import shutil
            shutil.copyfile(language, root / 'tessdata' / 'jpn.traineddata')
        self.validate(tool, root)
        self._check(cancel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        stage.rename(dest)
        result = self.select(tool, dest)
        progress(spec['label'] + ' 已配置，可返回功能页面继续。')
        return result

    def start_translatorpp(self, progress=lambda message: None, cancel=None):
        from ModuleFolders.Infrastructure.GameAdapters.TranslatorPlusPlusClient import TranslatorPlusPlusClient, TranslatorPlusPlusError
        root = self.path('translatorpp')
        client = TranslatorPlusPlusClient(timeout=2)

        def probe():
            # A reachable but incompatible server must be reported, not trigger a second app.
            client.discover()
            info = client.probe()
            if not info.get('install_root') or Path(info['install_root']).resolve() != root:
                raise ToolError('22883 端口由其他 Translator++ 安装占用；请关闭该工具后重试。')
            return info

        try:
            connection = socket.create_connection(('127.0.0.1', 22883), timeout=2)
        except OSError:
            connection = None
        if connection is not None:
            connection.close()
            return probe()
        cancel = cancel or threading.Event()
        self._check(cancel)
        progress('正在启动 Translator++ 并等待本地 API（最多 60 秒）…')
        logs = self.home / '运行日志'
        logs.mkdir(parents=True, exist_ok=True)
        log = logs / ('translatorpp-' + uuid.uuid4().hex + '.log')
        with log.open('wb') as output:
            subprocess.Popen([str(root / 'Translator++.exe'), '--no-first-run', '--disable-background-networking',
                '--user-data-dir=' + str(logs / 'profile-8.8.9')], cwd=root, stdout=output, stderr=output,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            self._check(cancel)
            try:
                return probe()
            except TranslatorPlusPlusError:
                time.sleep(.5)
        raise ToolError('Translator++ API 尚未就绪；请查看工具窗口后重试。日志：' + str(log))
