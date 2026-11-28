"""대본 맞추기: 이미 있는 대본의 글을 그대로 쓰고, 시각만 음성 인식 결과에서 가져온다.

흐름
  1. 대본을 줄로 나눈다(빈 줄·통째로 괄호인 지문 줄은 말하지 않으므로 뺀다). SRT·WebVTT를 주면
     큐 글을 한 줄씩 쓴다.
  2. 대본과 인식 결과를 글자 단위로 맞춘다. 대소문자·문장부호·공백·전각/반각 차이는 무시한다.
     인식이 틀린 글자가 있어도 앞뒤가 맞으면 그 사이 대본 글자는 앞뒤 시각 사이에 고르게 놓는다.
  3. 대본 낱말마다 시각을 정해 자막 단어(Word)로 돌려준다. 대본 한 줄은 새 큐에서 시작하도록
     줄 첫 단어 위치(boundaries)를 함께 돌려준다. 줄 나눔·표시 시간은 자막 규칙이 그대로 맡는다.

대본 전체를 한 번에 맞추면 글이 길 때 느리다(흔한 글자가 수천 번 나온다). 대본을 몇 줄씩 묶어
아직 맞추지 않은 인식 구간의 앞부분과만 비교해, 순서를 지키면서 길이에 거의 비례해 끝낸다.
음성에서 찾지 못한 줄은 시각을 추정했다고 알린다(검토 목록).
외부 의존이 없고 화면·실행 파일을 모른다.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from core.tools import subtitles
from core.tools.subtitles import Word

CHUNK_CHARS = 240          # 한 번에 맞출 대본 글자 수(줄 단위로 끊는다)
WINDOW_FACTOR = 3          # 인식 쪽은 대본 묶음의 이만큼 + 여유를 본다(대본에 없는 말·애드리브)
WINDOW_EXTRA = 400
WIDE_FACTOR = 20           # 가까운 곳에서 못 찾았을 때 한 번 더 볼 넓이
WIDE_EXTRA = 4000
WIDE_BLOCK = 4
JUMP_BLOCK = 4             # 크게 건너뛴 자리에서 이보다 짧게 맞은 조각은 우연으로 본다
JUMP_SLACK = 12
MIN_BLOCK = 2              # 이보다 짧게 맞은 조각은 우연으로 보고 쓰지 않는다
ACCEPT = 0.3               # 묶음 글자가 이만큼 맞아야 그 묶음의 맞춤을 쓴다
FOUND = 0.5                # 줄의 글자가 이만큼 맞아야 '음성에서 찾음'
GUESSED_PROB = 0.3         # 시각을 추정한 단어의 확신도(자막 검토의 '확신도 낮음' 기준 아래)
DEFAULT_MS_PER_CHAR = 180

_STAGE = re.compile(r'^\s*(?:\[[^\]]*\]|\([^)]*\)|（[^）]*）|【[^】]*】|〔[^〕]*〕)\s*$')


@dataclass(frozen=True)
class Alignment:
    words: tuple            # 대본 낱말(Word), 시각은 음성에서
    boundaries: tuple       # 각 줄 첫 단어의 위치(첫 줄 제외) — 이 앞에서 큐를 끊는다
    lines: tuple            # 자막에 쓴 대본 줄
    coverage: tuple         # 줄마다 음성에서 찾은 글자 비율(0~1)
    line_starts: tuple      # 줄마다 첫 단어 위치

    @property
    def missed(self):
        """음성에서 거의 찾지 못해 시각을 추정한 줄 번호(1부터)."""
        return tuple(number for number, value in enumerate(self.coverage, 1) if value < FOUND)


def script_lines(text):
    """대본 글 → 자막에 쓸 줄. SRT·WebVTT면 큐마다 한 줄."""
    text = (text or '').lstrip('﻿')
    cues = subtitles.parse(text) if '-->' in text else []
    raw = [' '.join(line.strip() for line in cue.lines if line.strip()) for cue in cues] if cues \
        else text.splitlines()
    lines = []
    for line in raw:
        line = ' '.join(line.split())
        if line and not _STAGE.match(line):
            lines.append(line)
    return lines


def _key(text):
    """맞출 때 비교하는 글자: 글자·숫자만, 호환 문자는 같은 모양으로, 대소문자 무시."""
    return [char for char in unicodedata.normalize('NFKC', text).casefold()
            if unicodedata.category(char)[:1] in 'LN']


def _tokens(line, spaced):
    """대본 한 줄 → 자막 단어 글. 줄 나눔 규칙과 같은 조각(띄어 쓰는 언어는 낱말, 아니면 글자)."""
    pieces = subtitles._pieces(line, spaced)
    if spaced and pieces:
        pieces[0] = ' ' + pieces[0].lstrip()        # 줄끼리 이어 붙여도 띄어 쓰인다
    return [piece for piece in pieces if piece.strip()]


def _heard(words):
    """인식 결과 → (글자, 시작 ms, 끝 ms) 목록. 한 단어의 시간은 글자 수대로 나눈다."""
    chars = []
    for word in words:
        keys = _key(word.text)
        span = max(0, word.end - word.start)
        for index, char in enumerate(keys):
            start = word.start + span * index // len(keys)
            end = word.start + span * (index + 1) // len(keys)
            chars.append((char, start, max(end, start + 1)))
    return chars


def _chunk_from(line_keys, first):
    """first 줄부터 CHUNK_CHARS 안팎이 되도록 줄을 묶는다(줄을 가르지 않는다)."""
    lines, size = [], 0
    for index in range(first, len(line_keys)):
        lines.append(index)
        size += len(line_keys[index])
        if size >= CHUNK_CHARS:
            break
    return lines


def _committed(chunk, line_keys, last):
    """묶음 가운데 이번에 확정할 앞쪽 줄들(글자 절반 이상, 적어도 한 줄). 끝 묶음은 모두.
    묶음 끝의 줄은 다음 줄의 음성과 우연히 겹쳐 맞기 쉬우므로, 다음 묶음과 함께 다시 맞춘다."""
    if last:
        return chunk
    total = sum(len(line_keys[line]) for line in chunk)
    size = 0
    for count, line in enumerate(chunk, 1):
        size += len(line_keys[line])
        if size * 2 >= total:
            return chunk[:count]
    return chunk


def _plausible(blocks):
    """앞 조각에서 크게 건너뛴 자리의 짧은 조각은 우연한 겹침으로 보고 뺀다(긴 조각은 실제로 건너뛴 것)."""
    kept, previous = [], None
    for block in blocks:
        if not block.size:
            continue
        if previous is None:
            jump, skipped = block.b, block.a
        else:
            jump = block.b - (previous.b + previous.size)
            skipped = block.a - (previous.a + previous.size)
        if block.size < JUMP_BLOCK and jump > 2 * skipped + JUMP_SLACK:
            continue
        kept.append(block)
        previous = block
    return kept


def _blocks(text, keys, position):
    """대본 묶음과 인식 글자(position부터)의 맞은 조각. 충분히 맞지 않으면 빈 목록."""
    # 가까운 곳부터 본다. 없으면 한 번 더 넓게(대본 앞에 긴 인사말·대본에 없는 장면이 있을 때).
    # 넓게 볼수록 우연히 겹칠 곳이 많으므로 더 긴 조각만 증거로 쓴다.
    for factor, extra, least in ((WINDOW_FACTOR, WINDOW_EXTRA, MIN_BLOCK), (WIDE_FACTOR, WIDE_EXTRA, WIDE_BLOCK)):
        window = keys[position:position + len(text) * factor + extra]
        blocks = _plausible(block for block in
                            SequenceMatcher(None, text, window, autojunk=False).get_matching_blocks()
                            if block.size >= least)
        if sum(block.size for block in blocks) >= len(text) * ACCEPT:
            return blocks
        if len(window) < len(text) * factor + extra:
            break                        # 이미 끝까지 봤다
    return []                            # 이 묶음은 음성에 없다(우연히 겹친 두세 글자로 건너뛰지 않는다)


def _match(script, heard):
    """대본 글자 위치 → 인식 글자 위치. 순서를 지키며, 묶음마다 아직 쓰지 않은 인식 구간과 맞춘다."""
    found = {}
    keys = [char for char, _start, _end in heard]
    position, first = 0, 0
    while first < len(script) and position < len(keys):
        chunk = _chunk_from(script, first)
        commit = _committed(chunk, script, chunk[-1] == len(script) - 1)
        first = commit[-1] + 1
        piece = [(line, offset) for line in chunk for offset in range(len(script[line]))]
        if not piece:
            continue
        blocks = _blocks([script[line][offset] for line, offset in piece], keys, position)
        settled = set(commit)
        advance = None
        for block in blocks:
            for step in range(block.size):
                where = piece[block.a + step]
                if where[0] in settled:
                    found[where] = position + block.b + step
                    advance = block.b + step + 1
        if advance is not None:
            position += advance
    return found


def _rate(timed):
    """맞춘 단어들로 잰 글자당 말하는 시간(ms)."""
    spans = [(end - start, size) for start, end, size in timed if size]
    total = sum(size for _, size in spans)
    return max(40, min(600, sum(span for span, _ in spans) // total)) if total else DEFAULT_MS_PER_CHAR


def align(text, words, *, spaced=True):
    """대본 글과 인식 단어 → Alignment. 대본이 음성과 전혀 맞지 않으면 ValueError."""
    lines = script_lines(text)
    if not lines:
        raise ValueError('The script has no lines to place')
    heard = _heard(words)
    tokens = [_tokens(line, spaced) for line in lines]
    token_keys = [[_key(token) for token in line] for line in tokens]
    line_keys = [[char for keys in line for char in keys] for line in token_keys]
    found = _match(line_keys, heard)
    if not found:
        raise ValueError('The script does not match the speech in this file')

    # 낱말마다: 맞은 글자의 시각(없으면 None), 비교 글자 수
    items, coverage, offset_of = [], [], {}
    for line_index, line in enumerate(token_keys):
        offset, matched = 0, 0
        for token_index, keys in enumerate(line):
            hits = [found[(line_index, offset + i)] for i in range(len(keys)) if (line_index, offset + i) in found]
            matched += len(hits)
            span = (heard[hits[0]][1], heard[hits[-1]][2]) if hits else None
            items.append([line_index, tokens[line_index][token_index], span, max(1, len(keys)), bool(hits)])
            offset += len(keys)
        coverage.append(matched / len(line_keys[line_index]) if line_keys[line_index] else 1.0)
    rate = _rate([(span[0], span[1], size) for _line, _text, span, size, hit in items if hit])
    _fill(items, rate)

    out, starts, previous = [], [], None
    for line_index, text_, span, _size, hit in items:
        if line_index != previous:
            starts.append(len(out))
            previous = line_index
        start, end = span
        out.append(Word(start, max(end, start + 1), text_, 1.0 if hit else GUESSED_PROB))
    return Alignment(tuple(out), tuple(starts[1:]), tuple(lines), tuple(coverage), tuple(starts))


def _fill(items, rate):
    """시각을 모르는 낱말을 앞뒤 맞은 낱말 사이에 글자 수대로 놓는다. 시각은 앞에서 뒤로 늘어난다.
    사이가 말하는 속도보다 훨씬 길면(대본에 없는 말이 끼었다) 앞 낱말 바로 뒤에 말하는 속도로 놓는다."""
    index = 0
    previous_end = None
    while index < len(items):
        if items[index][4]:
            start, end = items[index][2]
            if previous_end is not None:
                start = max(start, previous_end)
            items[index][2] = (start, max(end, start + 1))
            previous_end = items[index][2][1]
            index += 1
            continue
        stop = index
        while stop < len(items) and not items[stop][4]:
            stop += 1
        sizes = [items[i][3] for i in range(index, stop)]
        need = sum(sizes) * rate
        following = items[stop][2][0] if stop < len(items) else None
        if previous_end is None:                       # 앞에 맞은 낱말이 없다: 다음 낱말 앞으로
            begin = max(0, (following if following is not None else need) - need)
            room = (following if following is not None else begin + need) - begin
        elif following is None or following - previous_end > need * 3:
            # 사이가 너무 멀다(대본에 없는 말·긴 쉼). 새 줄 첫머리부터 못 들었으면 그 줄의 다음 맞은
            # 낱말 바로 앞에(줄은 쉼 뒤에 시작한다), 아니면 앞 낱말 바로 뒤에 말하는 속도로 놓는다.
            opens_line = items[index][0] != items[index - 1][0]
            if following is not None and opens_line and items[stop][0] == items[index][0]:
                begin, room = following - need, need
            else:
                begin, room = previous_end, need
        else:
            begin, room = previous_end, max(0, following - previous_end)
        cursor = float(begin)
        for i, size in zip(range(index, stop), sizes):
            length = room * size / sum(sizes)
            start = int(cursor)
            items[i][2] = (start, max(int(cursor + length), start + 1))
            cursor += length
        previous_end = items[stop - 1][2][1]
        index = stop
