"""문서 크기를 제한하면서 구조를 보존하는 번역 전처리·복원 규칙."""
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
MAX_SEGMENTS = 80000
TIMESTAMP = re.compile(r'^\s*(?:\d{2}:)?\d{2}:\d{2}[,.]\d{3}\s*-->')
# 대본·회의록의 줄머리 시간표시: [00:01:23.456] / [01:23] / 00:01:23,456 (뒤에 공백)
TIMECODE_PREFIX = re.compile(r'^\s*(?:\[\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?\]|\d{1,2}:\d{2}:\d{2}(?:[.,]\d{1,3})?(?=\s))\s*')
NONBLANK_LINE = re.compile(r'[^\r\n]+')
LINE = re.compile(r'[^\r\n]*(?:\r\n|\n|\r|$)')
# 화자 이름: 숫자로 시작하지 않고, 반각 ': ' 또는 전각 '：' 뒤에 대사가 온다.
SPEAKER = re.compile(r'^\s*(?:[-*]\s*)?([^\W\d_][\w .\'-]{0,30}?)\s*(?::[ \t]+|：\s*)', re.UNICODE)
# 'Note:' 'Step 1:' 같은 문서 라벨은 화자가 아니다.
NOT_SPEAKER = re.compile(
    r'(?:note|notes|warning|caution|tip|tips|important|example|examples|todo|fixme|info|'
    r'error|see|source|step(?:\s*\d+)?|chapter(?:\s*\d+)?|part(?:\s*\d+)?|q|a|re|fw|'
    r'https?|ftp|mailto|참고|주의|경고|예시|예|단계|注意|参考|例)',
    re.IGNORECASE)
FENCE = re.compile(r'^\s*(`{3,}|~{3,})')
MARKDOWN_PREFIX = re.compile(r'^\s*(?:>\s*)*(?:#{1,6}\s+|[-*+]\s+(?:\[[ xX]\]\s+)?|\d+[.)]\s+)?')
MARKDOWN_HEADING = re.compile(r'^\s{0,3}#{1,6}\s')
LIST_ITEM = re.compile(r'^\s*(?:>\s*)*(?:[-*+]|\d+[.)])\s+\S')
STAGE = re.compile(r'^\s*\[([^\]\r\n]+)\]\s*$')
PROTECT = re.compile(
    # 게임·메시지 제어 코드: RPG Maker \N[2] \V[23] \C[4] \I[64] \FS[24] \.  \|  \!  \>  \<  \^  \{  \$ …
    r'\\[A-Za-z]{1,8}(?:\[[^\]\r\n]*\]|<[^>\r\n]*>)?|\\[^\sA-Za-z0-9]|'
    # 시스템 태그와 내부 식별자: [SYSTEM] [SCENE] [BGM:battle1] PENDING_REVIEW MAX_HP
    r'\[[A-Z][A-Z0-9_]*(?:[:=][^\]\r\n]*)?\]|(?<![\w])[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+(?![\w])|'
    r'`[^`\r\n]+`|'
    # HTML 주석, Markdown 각주·참조 정의 라벨, 수식
    r'<!--.*?-->|\[\^[^\]\r\n]+\]|^\[[^\]\r\n]+\]:|'
    r'(?<![\w$])\$(?=[^\s$\d])[^$\r\n]*?[^\s$]\$(?![\w$])|'
    # i18n 변수: Ruby %{x}, vue-i18n @:key, i18next $t(key), [[x]], Laravel :name, react-i18next <0>
    r'%\{[\w.]+\}|@:[\w.]+|\$t\([^)\r\n]*\)|\[\[[^\[\]\r\n]+\]\]|'
    r'(?<![\w:/@.]):[A-Za-z_]\w*(?!:)|</?\d+\s*/?>|'
    # Markdown 링크/이미지 대상: [글자](대상 "제목") 과 참조형 [글자][id]
    r'(?<=\])\((?:[^()\s]|\([^()\s]*\))+(?:\s+"[^"\r\n]*")?\)|(?<=\])\[[^\[\]\r\n]{1,60}\]|'
    r'https?://[^\s<>\])]+|'
    # 자막 서식 태그 {\an8} {\i1}
    r'\{\\[^{}\r\n]*\}|'
    r'\{\{[^{}\r\n]+\}\}|\$\{[^{}\r\n]+\}|(?<!\{)\{[\w.:-]+\}(?!\})|'
    r'%\([\w.:-]+\)[sdif]|(?<!%)%(?:\d+\$)?[sdif]|'
    r'<\/?[A-Za-z][^<>\r\n]*>|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|'
    r'&(?:[A-Za-z][\w]+|#(?:\d+|x[\da-fA-F]+));|'
    r'(?:[A-Za-z]:\\|\.\.?/)[\w.\\/\-]+', re.UNICODE)
# ICU MessageFormat({n, plural, one {...} other {...}}): 뼈대(머리·선택자·닫는 괄호·#)만 보호하고
# 안쪽 문장은 번역한다. 선택자(one/other/male…)를 번역하면 메시지가 깨진다.
ICU_HEADER = re.compile(r'\{\s*\w+\s*,\s*(?:plural|select|selectordinal)\s*,')
ICU_PROTECT = re.compile(
    r'\{\s*\w+\s*,\s*(?:plural|select|selectordinal)\s*,(?:\s*offset:\d+)?|'
    r'(?:=\d+|[A-Za-z_]\w*)\s*\{(?=[^{}]*\})|\}|#|' + PROTECT.pattern, re.UNICODE)
PROTECTED_TOKEN = re.compile(r'__LOCALAI_KEEP_[0-9a-f]{8}_\d{4}__')
# 번역 전후 개수가 같아야 하는 구조 기호(괄호·꺾쇠·강조·코드·수식 표시)
STRUCTURE_MARKS = ('{', '}', '[', ']', '<', '>', '**', '~~', '`', '\\')  # $는 '$5→5달러'처럼 정상 변환이 있어 제외
SAFE_JSON_KEYS = frozenset({
    'id', 'uuid', 'guid', 'key', 'api_key', 'url', 'uri', 'href', 'link', 'path', 'filename', 'file',
    'command', 'cmd', 'code', 'source', 'src', 'script', 'hash', 'checksum', 'version',
    'type', 'kind', 'mime', 'language', 'lang', 'locale', 'model', 'token', 'slug', 'reference',
    'regex', 'pattern', 'expression', 'query', 'sql', 'function', 'method', 'status', 'state',
    'mode', 'color', 'colour', 'icon', 'image', 'img', 'class', 'classname', 'style', 'format',
    'unit', 'encoding', 'charset', 'timezone', 'date', 'time', 'timestamp', 'email', 'phone',
    'action', 'event', 'role', 'permission', 'scope', 'target', 'route', 'template', 'variant',
    'note', 'meta', 'plugin', 'plugins', 'filename', 'battleback1name', 'battleback2name',
    'charactername', 'facename', 'battlername', 'parallaxname', 'tilesetnames', 'animationname',
})
# RPG Maker MV/MZ 이벤트 명령: 화면에 보이는 문장만 번역한다. 그 밖의 명령(스크립트 355/655,
# 플러그인 356/357, 주석 108/408, 그림·소리 파일 이름 등)의 parameters는 절대 건드리지 않는다.
# 값: 번역할 parameters 위치(None = 모든 문자열)
RPG_TEXT_COMMANDS = {401: None, 405: None, 102: (0,), 402: (1,), 101: (4,), 320: (1,), 324: (1,), 325: (1,)}
# 'user_id' 'imageUrl' 'file-path' 처럼 식별자 성격의 접미사가 붙은 키
SAFE_JSON_KEY_SUFFIX = re.compile(
    r'(?:^|[_\-.])(?:id|ids|url|urls|uri|path|paths|key|hash|code|type|slug|token|ref|src|file|dir|'
    r'ext|mime|class|color|icon|at|date|time|format|status|mode)$'
    r'|[a-z0-9](?:Id|Ids|URL|Url|Uri|Path|Key|Hash|Code|Type|Slug|Token|Ref|Src|File|Dir|Class|'
    r'Color|Icon|At|Date|Time|Format|Status|Mode)$')
# 열거형·식별자처럼 보이는 값: active, dark-mode, en_US, fontSize, MAX_SIZE, #fff, 2026-01-01, v1.2.3, text/plain
IDENTIFIER_VALUE = re.compile(
    r'[a-z0-9]+(?:[_\-.][a-z0-9]+)*|[a-z]+(?:[A-Z][a-z0-9]*)+|[A-Za-z]{2}[_-][A-Z]{2}|'
    r'[A-Z0-9]+(?:_[A-Z0-9]+)+|#[0-9a-fA-F]{3,8}|v?\d+(?:\.\d+)+[\w.-]*|'
    r'\d{4}-\d{2}-\d{2}(?:[T ][\d:.]+(?:Z|[+-]\d{2}:?\d{2})?)?|[\w.+-]+/[\w.+-]+')
_STOPWORDS = frozenset({'the', 'a', 'an', 'is', 'are', 'was', 'of', 'to', 'and', 'or', 'what',
                        'he', 'she', 'it', 'you', 'i', 'we', 'they', 'that', 'this', 'in', 'on'})
_CODE_LINE = re.compile(
    r'\s*(?:#!|#include\b|//|/\*|\*/'
    r'|(?:async\s+)?def\s+[A-Za-z_]\w*\s*\(|class\s+[A-Za-z_]\w*\s*[(:{]'
    r'|from\s+[\w.]+\s+import\s+\S|import\s+[\w.]+(?:\s+as\s+\w+)?(?:\s*,\s*[\w.]+)*\s*;?\s*$'
    r'|import\s+.+\s+from\s+[\'"]|(?:const|let|var)\s+[\w$]+\s*=|function\s*[\w$]*\s*\('
    r'|return\b[^\r\n]*;\s*$|return\s*$|(?:public|private|protected|static)\b[^\r\n]*[;{]\s*$'
    r'|(?:>>>|\$|PS [A-Za-z]:\\[^>\r\n]*>)\s|(?:\./|~/)\S'
    r'|[A-Za-z_][\w.]*\([^\r\n]*\)\s*;?\s*$|[{}\[\]()<>;,]+\s*$)')
_CONTROL = re.compile(r'\s*(if|elif|while|for|with|try|except|else|catch|switch|finally|do)\b([^\r\n]*?)([:{])\s*$')
_SHELL = re.compile(r'\s*(?:pip3?|uv|npm|npx|yarn|pnpm|git|docker|curl|wget|python3?|node|sudo|'
                    r'powershell|winget|choco|ollama|cd|mkdir)\s+(\S.*)$')
_ASSIGN = re.compile(r'\s*[A-Za-z_][\w.\[\]\'"]*\s*(?:[+\-*/%]?=)(?!=)\s*(\S.*)$')


def looks_like_code(line: str) -> bool:
    """한 줄이 코드/명령처럼 보이는지 보수적으로 판단한다. 문장(산문)은 False가 되도록 한다."""
    if _CODE_LINE.match(line):
        return True
    control = _CONTROL.match(line)
    if control:
        keyword, rest, end = control.groups()
        rest = rest.strip()
        # 'for example:' 'if you want:' 같은 문장은 연산자/괄호가 없다.
        if not rest or end == '{' or re.search(r'[()=<>!\[\].]|\bin\b|\bas\b', rest) or \
                rest in ('True', 'False', '1'):
            return True
    # JSON/설정 조각의 "키": 값 줄
    if re.match(r'\s*"[^"\r\n]+"\s*:\s*(?:"|-?\d|true\b|false\b|null\b|\{|\[)', line):
        return True
    shell = _SHELL.match(line)
    if shell and re.search(r'&&|\|\||(?:^|\s)\|(?:\s|$)|(?:^|\s)(?:\.{1,2}|~)/|(?:^|\s)--?[A-Za-z]|\$\w',
                           shell.group(1)):
        return True                      # 셸 연산자·경로·옵션이 있으면 문장 길이와 무관하게 명령
    if shell:
        rest = shell.group(1).rstrip()
        if not rest.endswith(('.', '!', '?')) and (rest.startswith('-') or len(rest.split()) <= 4) \
                and not any(word.lower() in _STOPWORDS for word in rest.split()):
            return True
    assign = _ASSIGN.match(line)
    if assign:
        rest = assign.group(1).rstrip()
        words = rest.split()
        if rest.endswith((';', ',', '{', '[', '(')) or (
                len(words) <= 3 and not rest.endswith(('.', '!', '?'))
                and not any(word.lower().strip('.,') in _STOPWORDS for word in words)):
            return True
    return False


def speaker_prefix(text: str):
    """대본 화자 접두어(예: 'Alice: ')의 match를 반환한다. 문서 라벨이면 None."""
    match = SPEAKER.match(text)
    if not match or NOT_SPEAKER.fullmatch(match.group(1).strip()):
        return None
    return match


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
    for match in NONBLANK_LINE.finditer(source):
        if match.group().strip():
            lines.append(match.group())
            if len(lines) >= 180:
                break
    if suffix in ('.srt', '.vtt') or sum(bool(TIMESTAMP.match(x)) for x in lines) >= 2 or \
            sum(bool(TIMECODE_PREFIX.match(x)) for x in lines) >= max(2, len(lines) // 2):
        return 'subtitle'
    speakers = sum(bool(speaker_prefix(line)) for line in lines)
    if speakers >= 2 and speakers / max(1, len(lines)) >= .16:
        return 'script'
    if speakers == 1 and any(STAGE.fullmatch(x) for x in lines):
        return 'script'
    codes = sum(bool(looks_like_code(x) or FENCE.match(x)) for x in lines)
    if codes >= 3 and codes / max(1, len(lines)) >= .25:
        return 'code'
    return 'general'


def _trim_span(source: str, start: int, end: int, code_filter: bool = True) -> Segment | None:
    value = source[start:end]
    left = len(value) - len(value.lstrip(' \t'))
    start += left
    end = start + len(value[left:].rstrip(' \t'))
    value = source[start:end]
    if value and any(x.isalpha() for x in value) and not (code_filter and looks_like_code(value)):
        return Segment(start, end, value)
    return None


def _table_cells(source: str, start: int, end: int, code_filter: bool):
    line = source[start:end]
    if re.fullmatch(r'\s*\|?\s*[:\- ]+\|[:\-| ]+\s*\|?\s*', line):
        return []
    # 인라인 코드 안의 '|'는 칸 구분자가 아니다.
    ticks = [False] * len(line)
    for code in re.finditer(r'`[^`]*`', line):
        for i in range(code.start(), code.end()):
            ticks[i] = True
    positions = ([-1] + [i for i, char in enumerate(line)
                         if char == '|' and not ticks[i] and (i == 0 or line[i - 1] != '\\')]
                 + [len(line)])
    items = []
    for i in range(len(positions) - 1):
        candidate = _trim_span(source, start + positions[i] + 1, start + positions[i + 1], code_filter)
        if candidate:
            items.append(candidate)
    return items


def _plain(source: str, suffix: str, stage: bool, kind: str) -> list[Segment]:
    segments = []
    fenced = None
    markdown = suffix in ('.md', '.markdown')
    subtitle_file = suffix in ('.srt', '.vtt')
    in_frontmatter = markdown and source.startswith(('---\n', '---\r\n'))
    block = None
    # 코드 판별은 코드가 섞일 수 있는 문서에만 쓴다. 자막·대본·소설의 대사를 코드로 오인하지 않는다.
    code_filter = kind in ('general', 'code', 'structured') and not subtitle_file
    dialogue = kind in ('script', 'subtitle') or subtitle_file
    last_blank, in_list, in_comment = True, False, False

    def add(segment):
        if segment:
            segments.append(segment)
            if len(segments) > MAX_SEGMENTS:
                raise ValueError('Document contains too many translation segments')

    for line_match in LINE.finditer(source):
        raw = line_match.group()
        if not raw:
            continue
        line = raw.rstrip('\r\n')
        stripped = line.strip()
        previous_blank, last_blank = last_blank, not stripped
        if in_frontmatter:
            if line_match.start() > 0 and stripped in ('---', '...'):
                in_frontmatter = False
            continue
        if subtitle_file and not stripped:
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
            # VTT에서 시간정보 바로 앞의 식별자는 자막 텍스트가 아니다. (원문 복사 없이 위치로 탐색)
            if not TIMESTAMP.match(line):
                next_line = NONBLANK_LINE.search(source, line_match.end())
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
        # 줄머리 시간표시는 구조로 보고 번역 대상에서 뺀다(모델이 숫자를 바꾸지 못하게).
        base = line_match.start()
        timecode = TIMECODE_PREFIX.match(line)
        if timecode:
            base += timecode.end()
            line = line[timecode.end():]
            stripped = line.strip()
            if not stripped:
                continue
        if markdown:
            # 여러 줄에 걸친 HTML 주석은 통째로 건너뛴다(한 줄 주석은 보호 토큰으로 처리).
            if in_comment:
                if '-->' in line:
                    in_comment = False
                continue
            if '<!--' in line and '-->' not in line[line.index('<!--'):]:
                in_comment = True
                if not line[:line.index('<!--')].strip():
                    continue
                line = line[:line.index('<!--')].rstrip()
                stripped = line.strip()
            indented = line.startswith(('    ', '\t'))
            if LIST_ITEM.match(line):
                in_list = True
            elif indented:
                # 목록 밖에서 빈 줄 뒤에 오는 들여쓰기만 코드 블록이다. 하위 목록·이어지는 문단은 번역한다.
                if not in_list and previous_blank:
                    continue
            elif previous_blank or MARKDOWN_HEADING.match(line):
                in_list = False
            if '|' in line and line.count('|') >= 2:
                for cell in _table_cells(source, base, base + len(line),
                                         code_filter):
                    add(cell)
                continue
        direction = STAGE.fullmatch(line)
        if direction and dialogue and not stage:
            continue
        if kind == 'code' and not (markdown and MARKDOWN_HEADING.match(line)) and \
                re.match(r'^\s*(?:#|//|/\*|\*(?!\*)|--|;)', line):
            continue
        if not direction and code_filter and looks_like_code(line):
            continue
        start, end = base, base + len(line)
        if direction:
            start += line.index('[') + 1
            end = base + line.rindex(']')
        else:
            prefix = MARKDOWN_PREFIX.match(line) if markdown else None
            if prefix:
                start += prefix.end()
            speaker = speaker_prefix(source[start:end]) if dialogue else None
            if speaker:
                start += speaker.end()
        add(_trim_span(source, start, end, code_filter and not direction))
    if fenced:
        raise ValueError('Unclosed Markdown/code fence; refusing ambiguous translation')
    return segments


def _json_skip(key: str, value: str) -> bool:
    """번역하면 프로그램 동작이 바뀔 수 있는 JSON 문자열 값인지 판단한다."""
    if key.lower() in SAFE_JSON_KEYS or SAFE_JSON_KEY_SUFFIX.search(key):
        return True
    value = value.strip()
    if not any(x.isalpha() for x in value):
        return True
    return bool(PROTECT.fullmatch(value) or IDENTIFIER_VALUE.fullmatch(value))


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
            code, parameters = None, None
            while source[pos] != '}':
                name, pos = self.decoder.raw_decode(source, pos)
                pos = self.space(pos)
                if source[pos] != ':':
                    raise ValueError('Invalid JSON field separator')
                if name == 'parameters' and self.source[self.space(pos + 1)] == '[':
                    pos, parameters = self.parameters(pos + 1)
                else:
                    if name == 'code':
                        literal, _end = self.decoder.raw_decode(source, self.space(pos + 1))
                        code = literal if isinstance(literal, int) and not isinstance(literal, bool) else None
                    pos = self.value(pos + 1, str(name))
                pos = self.space(pos)
                if source[pos] != ',':
                    break
                pos = self.space(pos + 1)
            if parameters is not None and code is not None:
                self.filter_command(code, parameters)
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
        if isinstance(literal, str) and not _json_skip(key, literal):
            self.result.append(Segment(pos, end, literal, True))
            if len(self.result) > MAX_SEGMENTS:
                raise ValueError('Document contains too many JSON string values')
        return end


    def parameters(self, pos):
        """'parameters' 배열을 읽으며 각 위치에서 나온 번역 구간 범위를 기억한다."""
        pos = self.space(pos)
        spans, index = [], 0
        pos = self.space(pos + 1)
        while self.source[pos] != ']':
            begin = len(self.result)
            pos = self.value(pos, 'parameters')
            spans.append((index, begin, len(self.result)))
            index += 1
            pos = self.space(pos)
            if self.source[pos] != ',':
                break
            pos = self.space(pos + 1)
        return pos + 1, spans

    def filter_command(self, code, spans):
        """RPG Maker 이벤트 명령이면 화면 문장 위치만 남기고 나머지 구간은 번역 대상에서 뺀다."""
        allowed = RPG_TEXT_COMMANDS.get(code, ())
        if allowed is None:
            return
        drop = set()
        for index, begin, end in spans:
            if index not in allowed:
                drop.update(range(begin, end))
        if drop:
            self.result[:] = [item for number, item in enumerate(self.result) if number not in drop]


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


def protect(text: str, allow=()):
    """보호할 부분을 토큰으로 바꾼다. allow(사용자 고정 용어집의 원문)에 있는 말은 식별자 모양이어도
    번역하라는 뜻이므로 보호하지 않는다."""
    mapping = {}
    nonce = hashlib.sha256(text.encode('utf-8')).hexdigest()[:8]
    suffix = 0
    while f'__LOCALAI_KEEP_{nonce}_' in text:
        suffix += 1
        nonce = hashlib.sha256((text + str(suffix)).encode('utf-8')).hexdigest()[:8]
    def replace(match):
        if match.group() in allow:
            return match.group()
        token = f'__LOCALAI_KEEP_{nonce}_{len(mapping):04d}__'
        mapping[token] = match.group()
        return token
    pattern = ICU_PROTECT if ICU_HEADER.search(text) else PROTECT
    return pattern.sub(replace, text), mapping


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
    for token in PROTECTED_TOKEN.finditer(text, start, min(len(text), end + 80)):
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
        newline = masked.find('\n', cursor, cutoff)
        carriage = masked.find('\r', cursor, cutoff)
        boundaries = [value for value in (newline, carriage) if value >= cursor]
        if boundaries:
            cutoff = min(boundaries)
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
    try:
        value = raw.decode('utf-8-sig')
        return value, ('utf-8-sig' if raw.startswith(b'\xef\xbb\xbf') else 'utf-8')
    except UnicodeDecodeError:
        pass
    try:
        value = raw.decode('cp949')
    except UnicodeDecodeError as exc:
        raise ValueError('Cannot decode file as UTF-8 or CP949') from exc
    # Shift-JIS 등도 CP949로 "해독"되지만 대부분 잘 쓰지 않는 확장 음절이 된다.
    # 실제 한국어 문서는 한글 비율이 높고, 음절 대부분이 KS X 1001(EUC-KR) 상용 음절이다.
    wide = [x for x in value if ord(x) > 127]
    hangul = [x for x in wide if '\uac00' <= x <= '\ud7a3' or '\u3131' <= x <= '\u318e']
    def common(char):
        # CPython euc_kr은 비상용 음절을 8바이트 조합형으로 인코딩하므로 2바이트만 상용 음절이다.
        try:
            return len(char.encode('euc_kr')) == 2
        except UnicodeEncodeError:
            return False
    if wide and (len(hangul) / len(wide) < .6 or sum(map(common, hangul)) / max(1, len(hangul)) < .9):
        raise ValueError('Cannot determine the text encoding; save the file as UTF-8 and retry')
    return value, 'cp949'


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def verify_codes(doc: Document, output: str, allow=()):
    """저장 직전 문서 전체 검사: 원문과 번역문의 제어 코드·태그·변수·식별자 목록이 같아야 한다.
    (구간 검증을 통과했더라도 조립·인코딩 과정의 실수까지 막는 마지막 안전장치)"""
    from collections import Counter
    if doc.suffix == '.json':
        before = '\n'.join(_strings(json.loads(doc.source)))
        after = '\n'.join(_strings(json.loads(output)))
    else:
        before, after = doc.source, output
    def codes(text):
        found = Counter(match.group() for match in PROTECT.finditer(text) if match.group() not in allow)
        found.update(match.group() for match in re.finditer(r'\\[A-Za-z]{1,8}(?:\[[^\]\r\n]*\])?', text))
        return found
    old, new = codes(before), codes(after)
    if old != new:
        missing = list((old - new).elements())[:5]
        extra = list((new - old).elements())[:5]
        raise ValueError('Control codes/tags changed during translation; not saved (missing %s, extra %s)'
                         % (missing, extra))
