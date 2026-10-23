"""Audited font-family identifiers; no source paths or runtime execution."""
import re


def normalize_aliases(value):
    if (not isinstance(value,(list,tuple)) or len(value)>16 or any(
            not isinstance(name,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}',name)
            for name in value) or len(set(value))!=len(value)):
        raise ValueError('FONT_ALIASES_INVALID: expected at most 16 unique ASCII font-family names')
    return list(value)
