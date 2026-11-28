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
from difflib import Match, SequenceMatcher

from core.tools import subtitles
from core.tools.subtitles import Word

CHUNK_CHARS = 240          # 한 번에 맞출 대본 글자 수(줄 단위로 끊는다)
WINDOW_FACTOR = 3          # 인식 쪽은 대본 묶음의 이만큼 + 여유를 본다(대본에 없는 말·애드리브)
WINDOW_EXTRA = 400
WIDE_FACTOR = 20           # 가까운 곳에서 못 찾았을 때 한 번 더 볼 넓이
WIDE_EXTRA = 4000
WIDE_BLOCK = 4
FAR_BLOCK = 6              # 남은 음성 전체를 훑을 때 증거로 쓰는 조각 길이
FAR_ACCEPT = 0.4
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
    unscripted: tuple = ()  # 대본에 없는 말(애드리브 등)로 보이는 인식 단어 묶음 ((Word, …), …)

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
            return []                    # 이미 끝까지 봤다: 이 묶음은 음성에 없다
    # 넓게 봐도 없으면 남은 음성 전체를 구간별로 훑는다(대본에 없는 말이 30분 넘게 이어진 뒤에도 다시
    # 찾도록). 멀리서 찾는 만큼 긴 조각(FAR_BLOCK 글자 이상)이 FAR_ACCEPT 넘게 맞아야 쓴다 — 우연히 겹친
    # 몇 글자로 앞을 건너뛰면 그 뒤 대본 전체가 밀린다.
    span = len(text) * WIDE_FACTOR + WIDE_EXTRA
    step = span // 2
    for offset in range(step, max(step, len(keys) - position), step):
        window = keys[position + offset:position + offset + span]
        if len(window) < len(text):
            break
        blocks = _plausible(block for block in
                            SequenceMatcher(None, text, window, autojunk=False).get_matching_blocks()
                            if block.size >= FAR_BLOCK)
        if sum(block.size for block in blocks) >= len(text) * FAR_ACCEPT:
            return [Match(block.a, block.b + offset, block.size) for block in blocks]
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


def align(text, words, *, spaced=True, speech=()):
    """대본 글과 인식 단어 → Alignment. 대본이 음성과 전혀 맞지 않으면 ValueError.
    speech: 말소리 구간 [(시작 ms, 끝 ms)](VAD). 인식이 놓친 대본 줄을 무음이 아니라 말소리에 놓는 데 쓴다."""
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
    # 말소리가 있던 시간: VAD 구간 + 대본과 맞지 않은 인식 단어(인식은 했지만 글이 틀린 곳)
    used = set(found.values())
    voiced = list(speech or ()) + [(start, end) for index, (_char, start, end) in enumerate(heard)
                                   if index not in used]
    _fill(items, rate, _merge_spans(voiced))

    out, starts, previous = [], [], None
    for line_index, text_, span, _size, hit in items:
        if line_index != previous:
            starts.append(len(out))
            previous = line_index
        start, end = span
        out.append(Word(start, max(end, start + 1), text_, 1.0 if hit else GUESSED_PROB))
    return Alignment(tuple(out), tuple(starts[1:]), tuple(lines), tuple(coverage), tuple(starts),
                     _unscripted(words, used, out))


UNSCRIPTED_MIN_MS = 700    # 이보다 짧은 대본 밖 말(맞장구 한 마디·잡음)은 자막으로 만들지 않는다
UNSCRIPTED_MIN_PROB = 0.5


def _unscripted(words, used, placed, join=600):
    """대본과 한 글자도 맞지 않은 인식 단어 가운데, 대본 글을 놓은 시간과 겹치지 않는 것(대본에 없는 말).
    가까운 단어끼리 묶고, 너무 짧거나 확신도가 낮은 묶음(잡음·환각)은 뺀다."""
    taken = _merge_spans([(word.start, word.end) for word in placed], join=0)
    runs, index, cursor = [], 0, 0
    for word in words:
        size = len(_key(word.text))
        hit = any(position in used for position in range(index, index + size))
        index += size
        if not size or hit or not word.text.strip() or word.prob < UNSCRIPTED_MIN_PROB:
            continue
        while cursor < len(taken) and taken[cursor][1] <= word.start:
            cursor += 1
        if cursor < len(taken) and taken[cursor][0] < word.end:
            continue                                   # 대본 글이 이미 이 시간을 덮는다
        if runs and word.start - runs[-1][-1].end <= join:
            runs[-1].append(word)
        else:
            runs.append([word])
    keep = []
    for run in runs:
        prob = sum(word.prob for word in run) / len(run)
        if run[-1].end - run[0].start >= UNSCRIPTED_MIN_MS and prob >= UNSCRIPTED_MIN_PROB:
            keep.append(tuple(run))
    return tuple(keep)


def with_unscripted(placed):
    """대본 낱말과 대본에 없는 말(인식 글)을 시간 순으로 합친다 →
    (단어, 끊을 위치, 언제나 지킬 경계(대본 글 ↔ 인식 글), 대본 밖 묶음의 시간 구간).
    대본 밖 묶음과 대본 줄은 서로 다른 큐에서 시작하고 한 큐로 합치지 않는다."""
    items = [(word.start, 0, index, word) for index, word in enumerate(placed.words)]
    line_start = set(placed.line_starts)
    for number, run in enumerate(placed.unscripted):
        items += [(word.start, 1, (number, position), word) for position, word in enumerate(run)]
    items.sort(key=lambda item: (item[0], item[1]))
    words, boundaries, strict, previous_kind = [], [], [], None
    for _start, kind, key, word in items:
        switched = previous_kind is not None and kind != previous_kind
        opens = (kind == 0 and key in line_start) or (kind == 1 and key[1] == 0) or switched
        if words and opens:
            boundaries.append(len(words))
            if switched or kind == 1:
                strict.append(len(words))
        words.append(word)
        previous_kind = kind
    spans = tuple((run[0].start, run[-1].end) for run in placed.unscripted)
    return words, tuple(sorted(set(boundaries))), tuple(sorted(set(strict))), spans


def _merge_spans(spans, join=250):
    """겹치거나 join ms보다 가까운 구간을 합쳐 시간 순으로."""
    out = []
    for start, end in sorted((int(s), int(e)) for s, e in spans if e > s):
        if out and start <= out[-1][1] + join:
            out[-1][1] = max(out[-1][1], end)
        else:
            out.append([start, end])
    return [tuple(span) for span in out]


def _voiced_between(voiced, low, high, least=150):
    """[low, high] 안의 말소리 구간(너무 짧은 조각은 뺀다)."""
    spans = [(max(start, low), min(end, high)) for start, end in voiced if end > low and start < high]
    return [(start, end) for start, end in spans if end - start >= least]


def _along(spans, sizes, offset=0.0, length=None):
    """구간들을 이어 붙인 시간선의 [offset, offset+length]에 낱말을 글자 수대로 놓는다 → [(시작, 끝)]."""
    total = sum(end - start for start, end in spans)
    length = total - offset if length is None else length

    def at(position):
        position = min(max(position, 0.0), total)
        for start, end in spans:
            if position <= end - start:
                return int(start + position)
            position -= end - start
        return int(spans[-1][1])

    out, cursor, weight = [], offset, sum(sizes)
    for size in sizes:
        step = length * size / weight
        start = at(cursor)
        out.append((start, max(at(cursor + step), start + 1)))
        cursor += step
    return out


def _fill(items, rate, voiced=()):
    """시각을 모르는 낱말(인식이 놓쳤거나 틀린 곳)을 앞뒤 맞은 낱말 사이에 놓는다.

    사이에 말소리(VAD·맞지 않은 인식 단어)가 있으면 그 말소리 시간에만 글자 수대로 놓는다. 예전에는
    사이가 길면 앞 낱말 바로 뒤에 몰아 놓아, 긴 무음·음악 뒤에 시작한 줄이 무음 동안 보이고 실제로
    말할 때는 자막이 비었다. 말소리가 놓을 글보다 훨씬 길면(대본에 없는 말이 섞였다) 줄 첫머리는
    다음 맞은 낱말 바로 앞, 그 밖에는 앞 낱말 바로 뒤의 말소리를 쓴다.
    말소리를 모르면 사이에 고르게, 사이가 너무 길면 같은 규칙으로 말하는 속도만큼만 놓는다."""
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
        opens_line = index == 0 or items[index][0] != items[index - 1][0]
        before_next = following is not None and opens_line and items[stop][0] == items[index][0]
        low = previous_end if previous_end is not None else max(0, (following or need) - need * 4)
        high = following if following is not None else low + need * 4
        spans = _voiced_between(voiced, low, high)
        heard = sum(end - start for start, end in spans)
        if spans and heard >= need * 0.25:
            if heard <= need * 3:
                placed = _along(spans, sizes)
            elif before_next or previous_end is None:
                placed = _along(spans, sizes, offset=heard - need, length=need)
            else:
                placed = _along(spans, sizes, offset=0.0, length=need)
        else:
            if previous_end is None:                   # 앞에 맞은 낱말이 없다: 다음 낱말 앞으로
                begin = max(0, (following if following is not None else need) - need)
                room = (following if following is not None else begin + need) - begin
            elif following is None or following - previous_end > need * 3:
                begin, room = (following - need, need) if before_next else (previous_end, need)
            else:
                begin, room = previous_end, max(0, following - previous_end)
            placed = _along([(begin, begin + max(1, room))], sizes)
        for i, span in zip(range(index, stop), placed):
            items[i][2] = span
        previous_end = items[stop - 1][2][1]
        index = stop
