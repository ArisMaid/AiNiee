"""Game adapter registry with the native RPG Maker adapter pre-registered."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy

from .RpgMaker.Detector import GameDetectionError, detect_game
from .RpgMaker.JsonExtractor import extract_game
from .Capabilities import capability_matrix

__all__ = ['AdapterRegistry', 'RpgMakerAdapter']


class RpgMakerAdapter:
    """JSON-only native adapter for RPG Maker MV/MZ game folders."""

    adapter_id = 'rpgmaker-native'
    version = '1.1.0'

    def probe(self, source):
        try:
            return detect_game(source)
        except GameDetectionError:
            return None

    def capabilities(self) -> dict:
        return dict(capability_matrix()[self.adapter_id], **{
            'adapter_id': self.adapter_id,
            'version': self.version,
            'engines': ['rpgmaker-mv', 'rpgmaker-mz'],
            'formats': ['json'],
            'extract_json': True,
            'extract_js': False,
            'extract_resources': False,
            'profile_json_selectors': True,
            'patch_json': True,
        })

    def extract(self, source, profile=None, progress=None, document_cache=None):
        return extract_game(source, profile, progress=progress,document_cache=document_cache)

    def __eq__(self, other):
        if isinstance(other, str):
            return other == self.adapter_id
        if isinstance(other, RpgMakerAdapter):
            return self.adapter_id == other.adapter_id and self.version == other.version
        return NotImplemented

    def __hash__(self):
        return hash((self.adapter_id, self.version))


class AdapterRegistry:
    """Registry keyed by adapter id; the native adapter is always present."""

    def __init__(self) -> None:
        self._adapters: dict[str, object] = {}
        self.register(RpgMakerAdapter())

    def register(self, adapter):
        adapter_id = getattr(adapter, 'adapter_id', None)
        if not isinstance(adapter_id, str) or adapter_id.strip() == '':
            raise ValueError('adapter must expose a non-empty adapter_id')
        version = getattr(adapter, 'version', None)
        if not isinstance(version, str) or version.strip() == '':
            raise ValueError(f'adapter {adapter_id} must expose a non-empty version')
        for method in ('probe', 'capabilities', 'extract'):
            if not callable(getattr(adapter, method, None)):
                raise ValueError(f'adapter {adapter_id} must implement {method}()')
        capabilities = adapter.capabilities()
        if (not isinstance(capabilities,Mapping) or capabilities.get('adapter_id')!=adapter_id
                or capabilities.get('version')!=version):
            raise ValueError('ADAPTER_CAPABILITY_IDENTITY_MISMATCH')
        for field in ('engines','formats'):
            values=capabilities.get(field)
            if not isinstance(values,list) or not values or any(not isinstance(v,str) or not v for v in values):
                raise ValueError('ADAPTER_CAPABILITY_INVALID: '+field)
        if adapter_id in self._adapters:
            raise ValueError(f'duplicate adapter id: {adapter_id}')
        self._adapters[adapter_id] = adapter
        return adapter

    def get(self, adapter_id):
        try:
            return self._adapters[adapter_id]
        except KeyError:
            raise KeyError(f'unknown adapter id: {adapter_id}') from None

    def list(self) -> list:
        return [self._adapters[key] for key in sorted(self._adapters)]

    def capability_matrix(self) -> dict:
        """Engine adapters and separate document/resource components, without probing tools."""
        result=capability_matrix()
        for adapter in self.list():
            result[adapter.adapter_id]=deepcopy(dict(adapter.capabilities()))
        return result

    def detect(self, source):
        for adapter_id in sorted(self._adapters):
            adapter = self._adapters[adapter_id]
            info = adapter.probe(source)
            if not isinstance(info, Mapping) or not info:
                continue
            result = dict(info)
            result['adapter_id'] = adapter_id
            result['version'] = adapter.version
            result['adapter_version'] = adapter.version
            return result
        return None
