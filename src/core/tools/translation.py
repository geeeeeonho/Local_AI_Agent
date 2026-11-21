"""원본 구조·코드·변수를 보호하는 텍스트 번역 전처리."""
from __future__ import annotations
import json
import re
from dataclasses import dataclass
from pathlib import Path

SUPPORTED = {'.txt', '.json', '.md', '.markdown', '.srt', '.vtt'}
TYPES = {'auto', 'general', 'novel', 'script', 'subtitle', 'code', 'structured'}
TIMESTAMP = re.compile(r'^\s*(?:\d\d:)?\d\d:\d\d[,.]\d\d\d\s*-->')
SPEAKER = re.compile(r'^\s*(?:[-*]\s*)?[\w가-힣][\w가-힣 .-]{0,30}:[ \t]+')
FENCE = re.compile(r'^\s*(`{3,}|~{3,})')
COMMAND = re.compile(r'^\s*(?:#!|//|/\*|\*/|#include\b|(?:def|class|from|import|return|async|await|const|let|var|function|for|while|try|except|public|private)\s+|(?:pip|uv|npm|npx|git|docker|curl|wget|python|node|sudo)\s+|(?:>>>|\$)\s+|[A-Za-z_][\w.]*\s*\(.*\)\s*;?\s*$)', re.I)
MARKDOWN_PREFIX = re.compile(r'^\s*(?:#{1,6}\s+|>\s+|[-*+]\s+|\d+[.)]\s+)')
STAGE = re.compile(r'^\s*\[([^\]\r\n]+)\]\s*$')
PROTECT = re.compile(r'`[^`\r\n]+`|https?://[^\s<>\])]+|\{\{[^{}\r\n]+\}\}|\$\{[^{}\r\n]+\}|(?<!\{)\{[\w.:-]+\}(?!\})|%\([\w.:-]+\)[sdif]|(?<!%)%(?:\d+\$)?[sdif]|<\/?[A-Za-z][^<>\r\n]*>|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', re.UNICODE)
SAFE_JSON_KEYS = {'id','uuid','key','api_key','url','uri','href','path','filename','file','command','cmd','code','script','hash','checksum','version','type','mime','language','locale','model','token','slug','reference','regex','pattern','query','sql'}

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

def detect(source: str, suffix: str) -> str:
    if suffix == '.json': return 'structured'
    lines = [s for s in source.splitlines() if s.strip()][:180]
    if suffix in ('.srt', '.vtt') or sum(bool(TIMESTAMP.match(s)) for s in lines) >= 2: return 'subtitle'
    speakers = sum(bool(SPEAKER.match(s)) for s in lines)
    if speakers >= 2 and speakers / max(len(lines),1) >= .16: return 'script'
    code = sum(bool(COMMAND.match(s) or FENCE.match(s)) for s in lines)
    if code >= 3 and code / max(len(lines),1) >= .25: return 'code'
    return 'general'

def _plain(source: str, suffix: str, stage: bool) -> list[Segment]:
    segments = []
    fenced = None
    front = suffix in ('.md','.markdown') and source.startswith(('---\n','---\r\n'))
    for m in re.finditer(r'[^\r\n]+', source):
        line = m.group()
        stripped = line.strip()
        if front:
            if m.start() > 0 and stripped in ('---','...'): front = False
            continue
        fence = FENCE.match(line) if suffix in ('.txt','.md','.markdown') else None
        if fence:
            marker = fence.group(1)
            if fenced is None: fenced = marker
            elif marker[0] == fenced[0] and len(marker) >= len(fenced): fenced = None
            continue
        if fenced or not stripped or TIMESTAMP.match(line) or stripped in ('WEBVTT','NOTE'):
            continue
        if suffix in ('.srt','.vtt') and stripped.isdecimal(): continue
        if suffix == '.vtt' and stripped.startswith(('NOTE ','STYLE','REGION')): continue
        if suffix in ('.md','.markdown') and re.match(r'^\s*\|[-: |]+\|\s*$',line): continue
        direction = STAGE.fullmatch(line)
        if direction and not stage: continue
        if COMMAND.match(line) or re.match(r'^\s*[{}\[\]]\s*$',line):
            if not (direction and stage): continue
        start, end = m.start(), m.end()
        if direction:
            start += line.index('[')+1
            end = m.start()+line.rindex(']')
        else:
            prefix = MARKDOWN_PREFIX.match(line) if suffix in ('.md','.markdown') else None
            if prefix: start += prefix.end()
            speaker = SPEAKER.match(source[start:end])
            if speaker: start += speaker.end()
        value = source[start:end]
        left = len(value)-len(value.lstrip(' \t'))
        right = len(value.rstrip(' \t'))
        start += left
        end = start+max(0,right-left)
        value = source[start:end]
        if value and any(c.isalpha() for c in value) and not COMMAND.match(value):
            segments.append(Segment(start,end,value))
    return segments

class _JSON:
    def __init__(self, source: str):
        self.s, self.decoder, self.result = source, json.JSONDecoder(), []
    def space(self,p):
        while p < len(self.s) and self.s[p].isspace(): p += 1
        return p
    def value(self,p,key=''):
        p=self.space(p); s=self.s
        if s[p]=='{':
            p=self.space(p+1)
            while s[p]!='}':
                name,p=self.decoder.raw_decode(s,p)
                p=self.space(p)
                if s[p]!=':': raise ValueError('JSON 콜론이 없습니다')
                p=self.value(p+1,str(name))
                p=self.space(p)
                if s[p]!=',': break
                p=self.space(p+1)
            return p+1
        if s[p]=='[':
            p=self.space(p+1)
            while s[p]!=']':
                p=self.value(p,key)
                p=self.space(p)
                if s[p]!=',': break
                p=self.space(p+1)
            return p+1
        literal,end=self.decoder.raw_decode(s,p)
        if isinstance(literal,str) and key.lower() not in SAFE_JSON_KEYS and any(c.isalpha() for c in literal):
            self.result.append(Segment(p,end,literal,True))
        return end

def prepare(source: str, suffix: str, *, kind='auto', stage=False) -> Document:
    suffix=suffix.lower()
    if suffix not in SUPPORTED: raise ValueError('지원하지 않는 확장자: '+suffix)
    if kind not in TYPES: raise ValueError('지원하지 않는 콘텐츠 유형: '+kind)
    detected=detect(source,suffix)
    if suffix=='.json':
        json.loads(source)
        walker=_JSON(source); walker.value(0)
        segments=walker.result
    else:
        segments=_plain(source,suffix,stage)
    return Document(source,suffix,detected,detected if kind=='auto' else kind,tuple(segments))

def protect(text: str):
    mapping={}
    def replace(match):
        token='__LOCALAI_KEEP_%04d__'%len(mapping)
        if token in text: raise ValueError('보호 토큰 충돌')
        mapping[token]=match.group()
        return token
    return PROTECT.sub(replace,text),mapping

def restore(text: str,mapping: dict):
    for key,value in mapping.items():
        if text.count(key)!=1: raise ValueError('코드/변수 보호 토큰 손상: '+key)
        text=text.replace(key,value)
    if '__LOCALAI_KEEP_' in text: raise ValueError('알 수 없는 보호 토큰')
    return text

def render(doc: Document, outputs: list[str]) -> str:
    if len(outputs)!=len(doc.segments): raise ValueError('번역 구간 수가 다릅니다')
    result=doc.source
    for segment,value in reversed(list(zip(doc.segments,outputs))):
        if not isinstance(value,str) or not value.strip(): raise ValueError('빈 번역 결과')
        if not segment.json_string and ('\n' in value or '\r' in value): raise ValueError('번역 결과가 줄바꿈을 변경했습니다')
        item=json.dumps(value,ensure_ascii=False) if segment.json_string else value
        result=result[:segment.start]+item+result[segment.end:]
    if doc.suffix=='.json':
        old,new=json.loads(doc.source),json.loads(result)
        def same(a,b):
            if type(a)!=type(b): return False
            if isinstance(a,dict): return a.keys()==b.keys() and all(same(a[k],b[k]) for k in a)
            if isinstance(a,list): return len(a)==len(b) and all(same(x,y) for x,y in zip(a,b))
            return isinstance(a,str) or a==b
        if not same(old,new): raise ValueError('JSON 구조 변형')
    return result

def read_source(path: Path, limit=4*1024*1024):
    path=Path(path)
    if path.suffix.lower() not in SUPPORTED: raise ValueError('지원하지 않는 확장자')
    with path.open('rb') as f: raw=f.read(limit+1)
    if len(raw)>limit: raise ValueError('4MiB보다 큰 파일은 지원하지 않습니다')
    if b'\x00' in raw: raise ValueError('바이너리 파일입니다')
    for encoding in ('utf-8-sig','cp949'):
        try: return raw.decode(encoding), ('utf-8-sig' if raw.startswith(b'\xef\xbb\xbf') else 'utf-8') if encoding=='utf-8-sig' else encoding
        except UnicodeDecodeError: pass
    raise ValueError('파일 인코딩을 해석할 수 없습니다')
