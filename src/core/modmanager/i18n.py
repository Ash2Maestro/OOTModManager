"""Shared frontend catalogs; translate UI fields without touching mod metadata."""
import json
from pathlib import Path
import re

_messages = {}
_templates = []
_prefixes = []
_suffixes = []


def configure(language='fr', directory=None):
    global _messages, _templates, _prefixes, _suffixes
    _messages, _templates, _prefixes, _suffixes = {}, [], [], []
    if language == 'fr' or directory is None or not re.fullmatch(r'[a-z]{2}(?:-[A-Z]{2})?', language):
        return
    path = Path(directory) / (language + '.json')
    if not path.is_file():
        return
    _messages = json.loads(path.read_text(encoding='utf-8'))['messages']
    for source, translated in _messages.items():
        placeholders = list(re.finditer(r'%(?:\.\d+)?[sdf]|%[1-9]', source))
        if placeholders:
            parts, offset = [], 0
            for match in placeholders:
                parts += [re.escape(source[offset:match.start()]),
                          r'(-?\d+(?:\.\d+)?)' if match.group().endswith('f') else
                          r'(-?\d+)' if match.group() == '%d' else r'(.+?)']
                offset = match.end()
            parts.append(re.escape(source[offset:]))
            _templates.append((re.compile(''.join(parts), re.DOTALL), translated,
                               [m.group() for m in placeholders], source.startswith(('%s non renseigné', '%s introuvable'))))
        elif source.endswith((': ', ' pour ')):
            _prefixes.append((source, translated))
        elif source.startswith(' — '):
            _suffixes.append((source, translated))
    _prefixes.sort(key=lambda pair: len(pair[0]), reverse=True)


def text(source, depth=0):
    if not isinstance(source, str) or not _messages:
        return source
    if source in _messages:
        return _messages[source]
    for pattern, translated, placeholders, label_first in _templates:
        match = pattern.fullmatch(source)
        if match:
            values = list(match.groups())
            if label_first and depth < 2:
                values[0] = text(values[0], depth + 1)
            if any(value[1:].isdigit() for value in placeholders):
                for placeholder, value in zip(placeholders, values):
                    translated = translated.replace(placeholder, value)
                return translated
            return translated % tuple(int(value) if placeholder == '%d' else
                                      float(value) if placeholder.endswith('f') else value
                                      for placeholder, value in zip(placeholders, values))
    for prefix, translated in _prefixes:
        if source.startswith(prefix):
            return translated + source[len(prefix):]
    for suffix, translated in _suffixes:
        if source.endswith(suffix):
            return source[:-len(suffix)] + translated
    return source


def event(payload):
    """Copy and translate only presentation fields; identifiers stay intact."""
    result = dict(payload)
    kind = result.get('type')
    fields = {'log': ('text',), 'progress': ('label', 'detail'), 'plan': ('title', 'reason'),
              'complete': ('message',), 'error': ('message',), 'snapshot': ('warning',)}.get(kind, ())
    for key in fields:
        if key in result:
            result[key] = text(result[key])
    if kind == 'snapshot':
        if result.get('active') == 'vanilla':
            result['activeName'] = text(result.get('activeName', ''))
        for collection in ('catalog', 'installed'):
            result[collection] = [dict(row) for row in result.get(collection, [])]
            for row in result[collection]:
                for key in ('subtitle', 'displayVersion', 'contentSummary', 'presentationSource'):
                    if key in row:
                        row[key] = text(row[key])
                if 'detail' in row:
                    parts = row['detail'].split(' · ', 1)
                    row['detail'] = ' · '.join([text(parts[0]), *parts[1:]])
    elif kind == 'import_result':
        result['errors'] = [name + ' : ' + text(detail) if separator else text(error)
                            for error in result.get('errors', [])
                            for name, separator, detail in [error.partition(' : ')]]
    elif kind == 'updates_result' and isinstance(result.get('result'), dict):
        result['result'] = dict(result['result'])
        if 'message' in result['result']:
            result['result']['message'] = text(result['result']['message'])
    return result
