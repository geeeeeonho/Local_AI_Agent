"""이미 시각이 있는 자막을 다시 맞추고, 이상하게 끊긴 곳을 검수·교정한다.

다시 맞추기(alass·ffsubsync와 같은 생각)
  자막이 화면에 떠 있는 시간과 실제 말소리 시간(음성 인식·VAD)이 가장 많이 겹치도록,
  1) 속도 차이(프레임 수 차이 23.976↔25 등)와 전체 밀림을 찾고,
  2) 중간에 밀림이 바뀌는 곳(광고·편집본 차이)을 동적 계획법으로 찾는다(바꿀 때마다 벌점).
  글을 비교하지 않으므로 번역 자막에도 쓴다. 자막이 음성과 같은 언어면 글자까지 맞춰
  줄마다 시각을 더 정확히 고친다(맞춘 시각이 위에서 찾은 시각과 크게 다르면 쓰지 않는다).

검수·교정
  문장 중간에서 두세 낱말로 잘린 조각 큐는 이웃과 합치고, 기대는 말(조사·관사·접속사) 앞뒤에서
  어색하게 끊긴 경계는 가까운 자연스러운 경계로 옮기며, 줄 나눔·겹침·너무 짧은 표시는 자막 규칙대로
  고친다. 무엇을 왜 바꿨는지 목록으로 돌려준다.

외부 의존이 없고 화면·실행 파일을 모른다.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from core.tools import script_align, subtitles
from core.tools.subtitles import Cue

STEP_MS = 100                  # 겹침을 재는 시간 칸
SEARCH_MS = 120_000            # 전체 밀림을 찾는 범위(앞뒤)
COARSE_MS = 1000               # 넓게 찾을 때의 칸
SPLIT_SEARCH_MS = 60_000       # 중간 밀림은 전체 밀림에서 이만큼 안에서 찾는다
SPLIT_PENALTY = 0.6            # 중간에 밀림을 바꿀 때의 벌점(큐 하나가 완전히 겹칠 때 1)
DRIFT = 0.3                    # 전체 밀림에서 SPLIT_SEARCH_MS만큼 떨어질 때 큐마다 빼는 이득
ORDER_SLACK_MS = 300           # 순서를 지킬 때 허용하는 겹침(원래 자막의 작은 겹침)
SPEEDS = (1.0, 25 / 23.976, 23.976 / 25, 24 / 25, 25 / 24, 23.976 / 24, 24 / 23.976,
          30 / 25, 25 / 30, 29.97 / 25, 25 / 29.97, 30 / 23.976, 23.976 / 30)
SPEED_GAIN = 0.03              # 속도를 바꾸려면 겹침이 이만큼(비율) 더 좋아야 한다
REFINE_LIMIT_MS = 2000         # 글자로 맞춘 시각은 다시 맞춘 시각에서 이 안일 때만 쓴다


@dataclass(frozen=True)
class Sync:
    cues: tuple
    speed: float = 1.0
    offset_ms: int = 0                 # 첫 구간의 밀림(+면 늦춤)
    splits: tuple = ()                 # ((큐 번호, 새 밀림 ms), …) — 중간에 밀림이 바뀐 곳
    refined: int = 0                   # 글자까지 맞춰 시각을 고친 큐 수
    before: float = 0.0                # 고치기 전·후 말소리와 겹친 비율(자막 시간 기준)
    after: float = 0.0


@dataclass(frozen=True)
class Fix:
    number: int                        # 고치기 전 큐 번호(1부터)
    reason: str


# ── 말소리 칸 ──
def _speech_bins(spans, total_ms):
    size = total_ms // STEP_MS + 2
    marks = [0] * (size + 1)
    for start, end in spans:
        a, b = max(0, int(start) // STEP_MS), min(size, int(end) // STEP_MS + 1)
        if b > a:
            marks[a] += 1
            marks[b] -= 1
    prefix, level, value = [0] * (size + 1), 0, 0
    for index in range(size):
        level += marks[index]
        value += 1 if level > 0 else 0
        prefix[index + 1] = value
    return prefix


def _overlap(prefix, start, end):
    """[start, end) ms가 말소리와 겹친 칸 수."""
    last = len(prefix) - 1
    a = min(last, max(0, start // STEP_MS))
    b = min(last, max(0, end // STEP_MS))
    return prefix[b] - prefix[a]


def _score(cues, prefix, speed, offset):
    return sum(_overlap(prefix, int(c.start * speed) + offset, int(c.end * speed) + offset) for c in cues)


def _best_offset(cues, prefix, speed, center=0):
    """전체 밀림: 1초 칸으로 넓게 찾은 뒤 그 둘레를 0.1초 칸으로 다시 찾는다(빠르게)."""
    best, where = -1, center
    for offset in range(center - SEARCH_MS, center + SEARCH_MS + 1, COARSE_MS):
        score = _score(cues, prefix, speed, offset)
        if score > best:
            best, where = score, offset
    for offset in range(where - COARSE_MS, where + COARSE_MS + 1, STEP_MS):
        score = _score(cues, prefix, speed, offset)
        if score > best:
            best, where = score, offset
    return where, best


def _piecewise(cues, prefix, speed, base):
    """큐마다 밀림(동적 계획법). 바꿀 때마다 SPLIT_PENALTY. → 큐마다 밀림 ms.
    자막 순서는 뒤바뀌지 않는다: 밀림을 앞으로 당길 때는 앞 큐와의 틈(+약간)만큼만 당길 수 있다.
    그렇지 않으면 말소리가 없는 구간(음악·긴 무음)의 가장자리 큐들이 앞뒤 말소리(이미 다른 큐가 덮은)에
    끌려가 순서가 꼬였다."""
    offsets = list(range(base - SPLIT_SEARCH_MS, base + SPLIT_SEARCH_MS + 1, STEP_MS))
    size = len(offsets)
    score = [0.0] * size
    back = []
    previous_end = None
    for cue in cues:
        start, end = int(cue.start * speed), int(cue.end * speed)
        length = max(1, (end - start) // STEP_MS)
        # 겹침 이득에서 전체 밀림에서 멀어진 만큼 조금 뺀다(증거가 없는 곳은 전체 밀림으로 돌아오게).
        gain = [_overlap(prefix, start + o, end + o) / length - DRIFT * abs(o - base) / SPLIT_SEARCH_MS
                for o in offsets]
        # 앞 큐 밀림 j에서 이번 밀림 k로: offsets[k] >= offsets[j] - (틈 + 여유) → j <= k + reach
        reach = size if previous_end is None else max(0, (start - previous_end + ORDER_SLACK_MS) // STEP_MS)
        best_value, best_index = [0.0] * size, [0] * size
        top_value, top_index = float('-inf'), 0
        for j in range(size):
            if score[j] > top_value:
                top_value, top_index = score[j], j
            best_value[j], best_index[j] = top_value, top_index
        new, choice = [0.0] * size, [0] * size
        for k in range(size):
            limit = min(size - 1, k + reach)
            jump = best_value[limit] - SPLIT_PENALTY
            if jump > score[k]:
                new[k], choice[k] = jump + gain[k], best_index[limit]
            else:
                new[k], choice[k] = score[k] + gain[k], k
        score = new
        back.append(choice)
        previous_end = end
    index = max(range(size), key=score.__getitem__)
    path = []
    for choice in reversed(back):
        path.append(offsets[index])
        index = choice[index]
    return list(reversed(path))


def resync(cues, speech, *, words=(), same_language=False, total_ms=None):
    """시각이 어긋난 자막 → Sync. speech: 말소리 구간 [(시작, 끝)], words: 인식 단어(Word)."""
    cues = [cue for cue in cues if cue.lines]
    if not cues or not speech:
        return Sync(tuple(cues))
    end = max([e for _s, e in speech] + [c.end for c in cues])
    total = int(total_ms or end) + SEARCH_MS * 2
    prefix = _speech_bins(speech, total)
    shown = sum(max(1, (c.end - c.start) // STEP_MS) for c in cues)
    before = _score(cues, prefix, 1.0, 0) / shown
    # 1) 속도 × 전체 밀림
    plain_offset, plain = _best_offset(cues, prefix, 1.0)
    speed, offset, best = 1.0, plain_offset, plain
    for candidate in SPEEDS[1:]:
        where, score = _best_offset(cues, prefix, candidate)
        if score > best and score > plain * (1 + SPEED_GAIN):
            speed, offset, best = candidate, where, score
    # 2) 중간에 밀림이 바뀌는 곳
    path = _piecewise(cues, prefix, speed, offset)
    splits = tuple((number, path[number - 1]) for number in range(2, len(path) + 1)
                   if path[number - 1] != path[number - 2])
    moved = [replace(cue, start=max(0, int(cue.start * speed) + shift), end=max(1, int(cue.end * speed) + shift))
             for cue, shift in zip(cues, path)]
    refined = 0
    if same_language and words:
        moved, refined = _refine_by_text(moved, words)
    after = _score(moved, prefix, 1.0, 0) / max(1, sum(max(1, (c.end - c.start) // STEP_MS) for c in moved))
    return Sync(tuple(moved), speed, path[0], splits, refined, round(min(1.0, before), 3), round(min(1.0, after), 3))


def _refine_by_text(cues, words):
    """같은 언어 자막: 큐 글을 인식 글자와 맞춰, 충분히 맞은 큐는 맞은 글자의 시각으로."""
    heard = script_align._heard(words)
    lines = [[char for char in script_align._key(cue.text)] for cue in cues]
    found = script_align._match(lines, heard)
    out, refined = [], 0
    for index, cue in enumerate(cues):
        hits = sorted(found[(index, offset)] for offset in range(len(lines[index])) if (index, offset) in found)
        if lines[index] and len(hits) >= max(2, len(lines[index]) * 0.5):
            start, end = heard[hits[0]][1], heard[hits[-1]][2]
            if abs(start - cue.start) <= REFINE_LIMIT_MS and abs(end - cue.end) <= REFINE_LIMIT_MS * 2:
                out.append(replace(cue, start=start, end=max(end, start + 1)))
                refined += 1
                continue
        out.append(cue)
    return out, refined


# ── 검수·교정 ──
def _text(cue, rules):
    return (' ' if rules.spaced else '').join(line.strip() for line in cue.lines).strip()


def _wrapped(text, rules):
    return subtitles.wrap(text, rules) or subtitles.force_wrap(text, rules)


def review(cues, rules):
    """→ (고친 큐, (Fix, …)). 분명한 문제만 고친다: 조각 큐 합치기, 어색한 경계 옮기기, 줄 나눔·시간 규칙."""
    items = [[cue, [index + 1]] for index, cue in enumerate(sorted((c for c in cues if c.lines),
                                                                    key=lambda c: (c.start, c.end)))]
    fixes = []
    # 1) 문장 중간에서 잘린 조각 큐 합치기(새로 만들 때와 같은 기준)
    merged = []
    for cue, numbers in items:
        if merged:
            previous, previous_numbers = merged[-1]
            text = _text(previous, rules) + (' ' if rules.spaced else '') + _text(cue, rules)
            gap = cue.start - previous.end
            short = any(item.end - item.start < subtitles.SHORT_MS
                        or subtitles.display_length(_text(item, rules)) < rules.capacity * 0.5
                        for item in (previous, cue))
            if not subtitles.ends_sentence(_text(previous, rules)) and short and gap <= subtitles.MERGE_GAP_MS \
                    and subtitles.wrap(text, rules) is not None and cue.end - previous.start <= rules.max_ms:
                merged[-1] = [replace(previous, end=max(previous.end, cue.end), lines=_wrapped(text, rules)),
                              previous_numbers + numbers]
                fixes.append(Fix(numbers[0], 'merged a fragment cut mid-sentence'))
                continue
        merged.append([cue, numbers])
    # 2) 어색한 경계(기대는 말 앞뒤)를 가까운 자연스러운 경계로
    for index in range(len(merged) - 1):
        (left, left_numbers), (right, right_numbers) = merged[index], merged[index + 1]
        moved = _better_boundary(left, right, rules)
        if moved is not None:
            merged[index][0], merged[index + 1][0] = moved
            fixes.append(Fix(right_numbers[0], 'moved an awkward break to a natural boundary'))
    # 3) 줄 나눔(규칙보다 긴 줄·어색한 줄바꿈)
    out = []
    for cue, numbers in merged:
        text = _text(cue, rules)
        lines = subtitles.wrap(text, rules)
        if lines is not None and tuple(lines) != tuple(cue.lines) and (
                len(cue.lines) > rules.max_lines
                or any(subtitles.display_length(line) > rules.max_chars for line in cue.lines)
                or (_break_cost(cue.lines, rules) > 0 and _break_cost(cue.lines, rules) > _break_cost(lines, rules) + 1.0)):
            cue = replace(cue, lines=tuple(lines))
            fixes.append(Fix(numbers[0], 'rewrapped lines'))
        out.append(cue)
    # 4) 겹침·너무 짧은 표시·깜박임(자막 규칙). 무엇을 고쳤는지는 고치기 전 큐와 글로 짝지어 알린다.
    timed = subtitles.retime(out, rules)
    flat = lambda cue: _text(cue, rules).replace(' ', '')
    cursor, hosts = 0, {}
    for index, (cue, numbers) in enumerate(zip(out, (n for _c, n in merged))):
        while cursor < len(timed) and flat(cue) not in flat(timed[cursor]):
            cursor += 1
        if cursor >= len(timed):
            break
        hosts.setdefault(cursor, []).append(index)
        host = timed[cursor]
        following = out[index + 1] if index + 1 < len(out) else None
        if following is not None and cue.end > following.start:
            fixes.append(Fix(numbers[0], 'fixed an overlap'))
        elif cue.end - cue.start < rules.min_ms <= host.end - host.start and flat(host) == flat(cue):
            fixes.append(Fix(numbers[0], 'lengthened a cue shown too briefly'))
    for group in hosts.values():
        if len(group) > 1:            # 밀려 보이지 않던 큐를 이웃에 합쳤다: 가장 짧던 큐가 그 큐다
            squeezed = min(group, key=lambda i: out[i].end - out[i].start)
            fixes.append(Fix(merged[squeezed][1][0], 'merged a cue squeezed to nothing'))
    return tuple(timed), tuple(sorted(set(fixes), key=lambda fix: (fix.number, fix.reason)))


def _break_cost(lines, rules):
    """줄바꿈 자리의 어색함(작을수록 좋다). 한 줄이면 0."""
    if len(lines) < 2:
        return 0.0
    return -sum(subtitles.boundary_score(lines[i], lines[i + 1], rules.spaced) for i in range(len(lines) - 1))


def _better_boundary(left, right, rules, reach=3):
    """두 큐 사이 경계가 어색하면(점수 차가 분명할 때만) 앞뒤 reach 조각 안에서 더 자연스러운 곳으로 옮긴다.
    시간은 두 큐를 합친 구간을 글자 수 비율로 다시 나눈다. → (새 왼쪽, 새 오른쪽) 또는 None."""
    left_text, right_text = _text(left, rules), _text(right, rules)
    if subtitles.ends_sentence(left_text):
        return None
    pieces = subtitles._pieces(left_text + (' ' if rules.spaced else '') + right_text, rules.spaced)
    current = len(subtitles._pieces(left_text, rules.spaced))
    if not 0 < current < len(pieces):
        return None
    join = lambda part: ''.join(part).strip()
    def score(cut):
        return subtitles.boundary_score(join(pieces[:cut]), join(pieces[cut:]), rules.spaced)
    now = score(current)
    best, where = now, current
    for cut in range(max(1, current - reach), min(len(pieces) - 1, current + reach) + 1):
        head, tail = join(pieces[:cut]), join(pieces[cut:])
        if subtitles.wrap(head, rules) is None or subtitles.wrap(tail, rules) is None:
            continue
        value = score(cut)
        if value > best + 1.0:
            best, where = value, cut
    if where == current:
        return None
    head, tail = join(pieces[:where]), join(pieces[where:])
    span_start, span_end = left.start, right.end
    middle = span_start + int((span_end - span_start) * len(head) / max(1, len(head) + len(tail)))
    gap = max(0, right.start - left.end)
    return (replace(left, end=max(left.start + 1, middle - gap // 2), lines=_wrapped(head, rules)),
            replace(right, start=middle + gap - gap // 2, lines=_wrapped(tail, rules)))
