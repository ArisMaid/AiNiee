"""Small value guards for display strings also observed by game conditions.

String conversion grammar: https://tc39.es/ecma262/#sec-stringtonumber
Only zero equality is needed; this module never evaluates JavaScript.
"""
import re
from .Models import Issue

_JS_SPACE='\t\v\f \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u202f\u205f\u3000\ufeff\n\r\u2028\u2029'
_DECIMAL=re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?')
_BASES=re.compile(r'0(?:[xX][0-9a-fA-F]+|[bB][01]+|[oO][0-7]+)')


def js_string_is_zero(text):
    if not isinstance(text,str):raise ValueError('Value must be a string')
    value=text.strip(_JS_SPACE)
    if not value:return True
    if _BASES.fullmatch(value):return all(char=='0' for char in value[2:])
    if not _DECIMAL.fullmatch(value):return False
    return float(value)==0.0


def validate_display_value(source,text,context,unit_id):
    rules=context.get('value_constraints',{})
    if not rules:return ()
    if (not isinstance(rules,dict) or set(rules)-{'exclude_values','exclude_contains','preserve_js_zero','preserve_newlines'} or
            any(key in rules and type(rules[key]) is not bool for key in ('preserve_js_zero','preserve_newlines'))):
        return (Issue('INVALID_VALUE_CONTRACT','error','Invalid display value contract',unit_id),)
    for key in ('exclude_values','exclude_contains'):
        values=rules.get(key,[])
        if (not isinstance(values,list) or len(values)>64 or any(
                not isinstance(value,str) or not value or len(value)>256 or '\x00' in value for value in values)
                or len(set(values))!=len(values)):
            return (Issue('INVALID_VALUE_CONTRACT','error','Invalid display value contract',unit_id),)
    errors=[]
    if rules.get('preserve_newlines') and source.count('\n')!=text.count('\n'):
        errors.append(Issue('DISPLAY_LINE_COUNT_CHANGED','error','Translation changes the number of game display-variable lines',unit_id))
    if text in rules.get('exclude_values',[]):
        errors.append(Issue('RESERVED_DISPLAY_VALUE','error','Translation equals a reserved program value',unit_id))
    if any(value in text for value in rules.get('exclude_contains',[])):
        errors.append(Issue('RESERVED_DISPLAY_MARKER','error','Translation introduces a reserved resource marker',unit_id))
    if rules.get('preserve_js_zero'):
        try:
            # RPG Maker returns storedValue || 0. Empty strings therefore also
            # change strict variable comparisons even when Number(text) is 0.
            if bool(source)!=bool(text) or js_string_is_zero(source)!=js_string_is_zero(text):
                errors.append(Issue('DISPLAY_VALUE_GUARD_CHANGED','error','Translation changes the game zero-value condition',unit_id))
        except (ValueError,OverflowError):
            errors.append(Issue('INVALID_DISPLAY_VALUE','error','Cannot verify the display value condition',unit_id))
    return tuple(errors)
