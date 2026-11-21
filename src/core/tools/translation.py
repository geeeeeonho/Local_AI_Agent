"""Bounded structure-preserving translation preparation and reconstruction."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

SUPPORTED = frozenset({'.txt', '.json', '.md', '.markdown', '.srt', '.vtt'})
TYPES = frozenset({'auto', 'general', 'novel', 'script', 'subtitle', 'code', 'structured'})
MAX_SOURCE_BYTES = 32 * 1024 * 1024
MAX_UNIT_CHARS = 1400
TIMESTAMP = re.compile(r'^\s*(?:\d{2}:)?\d{2}:\d{2}[,.]\d{3}\s*-->')
SPEAKER = re.compile(r'^\s*(?:[-*]\s*)?[\w][\w .-]{0,30}:[ \t]+', re.UNICODE)
FENCE = re.compile(r'^\s*(`{3,}|~{3,})')
COMMAND = re.compile(
    r'^\s*(?:#!|//|/\*|\*/|#include\b|'
    r'(?:def|class|from|import|return|async|await|const|let|var|function|for|while|try|except|public|private|if|elif|else|with|raise)\b'
    r'|(?:pip|uv|npm|npx|git|docker|curl|wget|python|node|sudo|powershell)\s+'
    r'|(?:>>>|\$)\s+|[A-Za-z_][\w.]*\s*\([^\r\n]*\)\s*;?\s*$'
    r'|[A-Za-z_][\w.]*\s*(?:\+=|-=|=(?!=))\s*[^=])')
MARKDOWN_PREFIX = re.compile(r'^\s*(?:#{1,6}\s+|>\s+|[-*+]\s+|\d+[.)]\s+)')
STAGE = re.compile(r'^\s*\[([^\]\r\n]+)\]\s*$')
PROTECT = re.compile(
    r'`[^`\r\n]+`|https?://[^\s<>\])]+|'
    r'\{\{[^{}\r\n]+\}\}|\$\{[^{}\r\n]+\}|(?<!\{)\{[\w.:-]+\}(?!\})|'
    r'%\([\w.:-]+\)[sdif]|(?<!%)%(?:\d+\$)?[sdif]|'
    r'<\/?[A-Za-z][^<>\r\n]*>|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|'
    r'&(?:[A-Za-z][\w]+|#(?:\d+|x[\da-fA-F]+));|'
    r'(?:[A-Za-z]:\\|\.\.?/)[\w.\\/\-]+', re.UNICODE)
PROTECTED_TOKEN = re.compile(r'__LOCALAI_KEEP_[0-9a-f]{8}_\d{4}__')
SAFE_JSON_KEYS = frozenset({
    'id', 'uuid', 'key', 'api_key', 'url', 'uri', 'href', 'path', 'filename', 'file',
    'command', 'cmd', 'code', 'source', 'script', 'hash', 'checksum', 'version',
    'type', 'mime', 'language', 'locale', 'model', 'token', 'slug', 'reference',
    'regex', 'pattern', 'expression', 'query', 'sql', 'function',
})


@dataclass(frozen=True)
class Segment:
    start: int
    end: int
    text: str
    json_string: bool = False


@dataclass(frozen=True)
class Document:
    source: str
    suffix: str
    detected: str
    selected: str
    segments: tuple[Segment, ...]


@dataclass(frozen=True)
class Piece:
    segment_index: int
    text: str
    after: str


def detect(source: str, suffix: str) -> str:
    suffix = suffix.lower()
    if suffix == '.json':
        return 'structured'
    lines = []
    for match in re.finditer(r'[^\r\n]+',source):
        if match.group().strip():
            lines.append(match.group())
            if len(lines)>=180:
                break
    if suffix in ('.srt', '.vtt') or sum(bool(TIMESTAMP.match(x)) for x in lines) >= 2:
        return 'subtitle'
    speakers = sum(bool(SPEAKER.match(line)) for line in lines)
    if speakers >= 2 and speakers / max(1, len(lines)) >= .16:
        return 'script'
    if speakers == 1 and any(STAGE.fullmatch(x) for x in lines):
        return 'script'
    codes = sum(bool(COMMAND.match(x) or FENCE.match(x)) for x in lines)
    if codes >= 3 and codes / max(1, len(lines)) >= .25:
        return 'code'
    return 'general'


def _trim_span(source: str, start: int, end: int) -> Segment | None:
    value = source[start:end]
    left = len(value) - len(value.lstrip(' \t'))
    start += left
    end = start + len(value[left:].rstrip(' \t'))
    value = source[start:end]
    if value and any(x.isalpha() for x in value) and not COMMAND.match(value):
        return Segment(start, end, value)
    return None


def _table_cells(source: str, start: int, end: int):
    line = source[start:end]
    if re.fullmatch(r'\s*\|?\s*[:\- ]+\|[:\-| ]+\s*\|?\s*', line):
        return []
    positions = [-1] + [i for i, char in enumerate(line) if char == '|' and (i == 0 or line[i - 1] != '\\')] + [len(line)]
    items = []
    for i in range(len(positions) - 1):
        begin = positions[i] + 1
        finish = positions[i + 1]
        candidate = _trim_span(source, start + begin, start + finish)
        if candidate:
            items.append(candidate)
    return items


def _plain(source: str, suffix: str, stage: bool, kind: str) -> list[Segment]:
    segments = []
    fenced = None
    in_frontmatter = suffix in ('.md', '.markdown') and source.startswith(('---\n', '---\r\n'))
    block = None
    for line_match in re.finditer(r'[^\r\n]*(?:\r\n|\n|\r|$)', source):
        raw = line_match.group()
        if not raw:
            continue
        line = raw.rstrip('\r\n')
        stripped = line.strip()
        if in_frontmatter:
            if line_match.start() > 0 and stripped in ('---', '...'):
                in_frontmatter = False
            continue
        if suffix in ('.srt', '.vtt') and not stripped:
            block = None
            continue
        if suffix == '.vtt':
            if stripped in ('STYLE', 'REGION') or stripped == 'NOTE' or stripped.startswith('NOTE '):
                block = stripped.split(' ', 1)[0]
                continue
            if block:
                continue
            if stripped in ('WEBVTT',) or stripped.startswith('WEBVTT '):
                continue
            # A VTT cue identifier precedes the timing line; it is not a subtitle.
            if not TIMESTAMP.match(line):
                remainder = source[line_match.end():]
                next_line = re.search(r'[^\r\n]+', remainder)
                if next_line and TIMESTAMP.match(next_line.group()):
                    continue
        if suffix in ('.txt', '.md', '.markdown'):
            fence = FENCE.match(line)
            if fence:
                marker = fence.group(1)
                if fenced is None:
                    fenced = marker
                elif marker[0] == fenced[0] and len(marker) >= len(fenced):
                    fenced = None
                continue
            if fenced:
                continue
        if not stripped or TIMESTAMP.match(line) or (suffix == '.srt' and stripped.isdecimal()):
            continue
        if suffix in ('.md', '.markdown'):
            if line.startswith(('    ', '\t')):
                continue
            if '|' in line and line.count('|') >= 2:
                segments.extend(_table_cells(source, line_match.start(), line_match.start() + len(line)))
                continue
        direction = STAGE.fullmatch(line)
        if direction and not stage:
            continue
        if kind == 'code' and re.match(r'^\s*(?:#|//|/\*|\*|--|;)', line):
            continue
        if COMMAND.match(line) or re.fullmatch(r'\s*[{}\[\]]\s*', line):
            if not (direction and stage):
                continue
        start, end = line_match.start(), line_match.start() + len(line)
        if direction:
            start += line.index('[') + 1
            end = line_match.start() + line.rindex(']')
        else:
            prefix = MARKDOWN_PREFIX.match(line) if suffix in ('.md', '.markdown') else None
            if prefix:
                start += prefix.end()
            speaker = SPEAKER.match(source[start:end]) if kind in ('script', 'subtitle') else None
            if speaker:
                start += speaker.end()
        candidate = _trim_span(source, start, end)
        if candidate:
            segments.append(candidate)
    if fenced:
        raise ValueError('Unclosed Markdown/code fence; refusing ambiguous translation')
    return segments


class _JSON:
    def __init__(self, source):
        self.source, self.decoder, self.result = source, json.JSONDecoder(), []

    def space(self, pos):
        while pos < len(self.source) and self.source[pos].isspace():
            pos += 1
        return pos

    def value(self, pos, key=''):
        pos = self.space(pos)
        source = self.source
        if source[pos] == '{':
            pos = self.space(pos + 1)
            while source[pos] != '}':
                name, pos = self.decoder.raw_decode(source, pos)
                pos = self.space(pos)
                if source[pos] != ':':
                    raise ValueError('Invalid JSON field separator')
                pos = self.value(pos + 1, str(name))
                pos = self.space(pos)
                if source[pos] != ',':
                    break
                pos = self.space(pos + 1)
            return pos + 1
        if source[pos] == '[':
            pos = self.space(pos + 1)
            while source[pos] != ']':
                pos = self.value(pos, key)
                pos = self.space(pos)
                if source[pos] != ',':
                    break
                pos = self.space(pos + 1)
            return pos + 1
        literal, end = self.decoder.raw_decode(source, pos)
        if isinstance(literal, str) and key.lower() not in SAFE_JSON_KEYS and any(x.isalpha() for x in literal):
            self.result.append(Segment(pos, end, literal, True))
        return end


def prepare(source: str, suffix: str, *, kind='auto', stage=False) -> Document:
    suffix = suffix.lower()
    if suffix not in SUPPORTED:
        raise ValueError('Unsupported file extension: ' + suffix)
    if kind not in TYPES:
        raise ValueError('Unsupported content type: ' + kind)
    detected = detect(source, suffix)
    selected = detected if kind == 'auto' else kind
    if suffix == '.json':
        try:
            json.loads(source)
            parser = _JSON(source)
            parser.value(0)
        except (RecursionError, IndexError) as exc:
            raise ValueError('Invalid or excessively nested JSON') from exc
        segments = parser.result
    else:
        segments = _plain(source, suffix, stage, selected)
    return Document(source, suffix, detected, selected, tuple(segments))


def protect(text: str):
    mapping = {}
    nonce = hashlib.sha256(text.encode('utf-8')).hexdigest()[:8]
    suffix = 0
    while f'__LOCALAI_KEEP_{nonce}_' in text:
        suffix += 1
        nonce = hashlib.sha256((text + str(suffix)).encode('utf-8')).hexdigest()[:8]
    def replace(match):
        token = f'__LOCALAI_KEEP_{nonce}_{len(mapping):04d}__'
        mapping[token] = match.group()
        return token
    return PROTECT.sub(replace, text), mapping


def restore(text: str, mapping: dict):
    for token, value in mapping.items():
        if text.count(token) != 1:
            raise ValueError('Protected code/variable token was changed: ' + token)
        text = text.replace(token, value)
    return text


def _safe_boundary(text: str, start: int, limit: int) -> int:
    if len(text) - start <= limit:
        return len(text)
    end = start + limit
    begin = start + limit // 3
    whitespace = max(text.rfind(' ', begin, end), text.rfind('\t', begin, end), text.rfind('\n', begin, end))
    if whitespace > start:
        end = whitespace
    else:
        punct = max((text.rfind(char, begin, end) for char in '.!?;,:.\u3002\uff01\uff1f'), default=-1)
        if punct > start:
            end = punct + 1
    for token in PROTECTED_TOKEN.finditer(text, start):
        if token.start() >= end:
            break
        if token.start() < end < token.end():
            if token.start() > start:
                end = token.start()
            elif token.end() - start <= limit:
                end = token.end()
            else:
                raise ValueError('A single protected token exceeds the chunk limit')
            break
    if end <= start:
        raise ValueError('Unable to safely divide translation text')
    if end < len(text) and unicodedata.combining(text[end]):
        while end > start and unicodedata.combining(text[end]):
            end -= 1
    return end


def split_masked(masked: str, *, limit=MAX_UNIT_CHARS):
    if limit < 50:
        raise ValueError('Unreasonably small translation chunk limit')
    left = len(masked) - len(masked.lstrip())
    prefix = masked[:left]
    cursor = left
    pieces = []
    while cursor < len(masked):
        cutoff = _safe_boundary(masked, cursor, limit)
        body = masked[cursor:cutoff].rstrip()
        if not body:
            raise ValueError('Untranslatable chunk boundary')
        separator_start = cursor + len(body)
        next_cursor = cutoff
        while next_cursor < len(masked) and masked[next_cursor].isspace():
            next_cursor += 1
        pieces.append((body, masked[separator_start:next_cursor]))
        cursor = next_cursor
    return prefix, pieces


def render(doc: Document, outputs: list[str]) -> str:
    if len(outputs) != len(doc.segments):
        raise ValueError('Number of translated segments differs from input')
    pieces = []
    cursor = 0
    for segment, translated in zip(doc.segments, outputs):
        if not isinstance(translated, str) or not translated.strip():
            raise ValueError('Empty translated segment')
        if not segment.json_string and ('\r' in translated or '\n' in translated):
            raise ValueError('Translation changed the original line boundaries')
        pieces.append(doc.source[cursor:segment.start])
        pieces.append(json.dumps(translated, ensure_ascii=False) if segment.json_string else translated)
        cursor = segment.end
    pieces.append(doc.source[cursor:])
    result = ''.join(pieces)
    if doc.suffix == '.json':
        old, new = json.loads(doc.source), json.loads(result)
        def same(a, b):
            if type(a) is not type(b):
                return False
            if isinstance(a, dict):
                return a.keys() == b.keys() and all(same(a[key], b[key]) for key in a)
            if isinstance(a, list):
                return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
            return isinstance(a, str) or a == b
        if not same(old, new):
            raise ValueError('Translation modified the JSON structure')
    return result


def read_source(path: Path, limit=MAX_SOURCE_BYTES):
    path = Path(path)
    if path.suffix.lower() not in SUPPORTED:
        raise ValueError('Unsupported file extension')
    with path.open('rb') as input_file:
        raw = input_file.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Source file is too large (32 MiB maximum)')
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        try:
            return raw.decode('utf-16'), 'utf-16'
        except UnicodeDecodeError as exc:
            raise ValueError('Invalid UTF-16 text') from exc
    if b'\x00' in raw:
        raise ValueError('Binary file or unsupported UTF-16 without BOM')
    for encoding in ('utf-8-sig', 'cp949'):
        try:
            value = raw.decode(encoding)
            if encoding == 'utf-8-sig' and not raw.startswith(b'\xef\xbb\xbf'):
                return value, 'utf-8'
            return value, encoding
        except UnicodeDecodeError:
            continue
    raise ValueError('Cannot decode file as UTF-8 or CP949')