"""음성 인식 검증: 오류 의심 구간 찾기, 다시 인식한 후보 고르기, 발언 누락 찾기.

원칙(원문 보존)
  * 반복·감탄사·말 더듬기·비문은 그 자체로 오류가 아니다. 지우거나 바꾸려면 둘 이상의 근거
    (낮은 확신도, 높은 압축률, 사람이 낼 수 없는 발화 속도, 무음 구간 등)가 겹쳐야 한다.
  * 최초 인식 결과는 바꾸지 않고 보관한다. 다시 인식한 후보는 명확히 나을 때만 채택하고,
    근거가 부족하면 원래 결과를 유지한 채 '확인 필요'로 기록한다.
  * 비슷한 이름은 알려 주기만 하고 하나로 통일하지 않는다(다른 호칭일 수 있다).

외부 의존이 없다(zlib·array·difflib). 오디오는 16비트 PCM 샘플 바이트를 받는다.
"""
from __future__ import annotations

import array
import math
import re
import sys
from dataclasses import dataclass
from difflib import SequenceMatcher

from core.tools import speech

from core.tools.speech import COMPRESSION_LIMIT, LOW_PROB, MAX_RATE, compression_ratio, speech_rate


@dataclass(frozen=True)
class Evidence:
    prob: float
    compression: float
    rate: float
    loop: bool
    filler: bool
    plausible_rate: bool

    @property
    def signals(self):
        """오류를 뒷받침하는 근거 이름들."""
        found = []
        if self.prob < LOW_PROB:
            found.append('low confidence')
        if self.compression > COMPRESSION_LIMIT:
            found.append('high compression ratio')
        if not self.plausible_rate:
            found.append('implausible speech rate')
        if self.loop:
            found.append('repetition loop')
        if self.filler:
            found.append('typical hallucination')
        return tuple(found)


def evidence(segment, *, spaced=True):
    norm = speech.normalize(segment.text)
    rate = speech_rate(segment)
    return Evidence(segment.prob, compression_ratio(segment.text), rate,
                    bool(speech.LOOP.search(norm)) and len(norm) >= 6,
                    speech.is_filler(segment.text), rate <= MAX_RATE[bool(spaced)])


# ── 오디오 에너지 ──
def rms(frames, *, stride=4):
    """16비트 PCM 바이트 한 덩어리의 RMS. 속도를 위해 stride 샘플마다 하나씩 본다(에너지 추정엔 충분)."""
    samples = array.array('h')
    samples.frombytes(frames[:len(frames) - len(frames) % 2])
    if sys.byteorder == 'big':
        samples.byteswap()
    picked = samples[::stride]
    return math.sqrt(sum(value * value for value in picked) / len(picked)) if picked else 0.0


def rms_profile(frames, *, channels=1, rate=16000, window_ms=100):
    """16비트 PCM 바이트 → window_ms마다 RMS(0~32767) 목록."""
    step = max(1, int(rate * window_ms / 1000)) * channels * 2
    return [rms(frames[index:index + step]) for index in range(0, len(frames), step)
            if frames[index:index + step]]


def speech_threshold(profile):
    """잡음 바닥(하위 20%)의 3배 이상이면서 아주 작은 소리(300)는 넘어야 말소리 후보로 본다."""
    if not profile:
        return float('inf')
    ordered = sorted(profile)
    floor = ordered[int(len(ordered) * 0.2)]
    return max(300.0, floor * 3.0)


def uncovered_speech(segments, profile, *, window_ms=100, min_ms=1500, dip_ms=300):
    """인식된 글이 없는데 소리가 이어지는 구간: 발언 누락 후보 [(시작 ms, 끝 ms)].
    잠깐(dip_ms 이하) 조용해지는 것은 이어진 것으로 본다. 음악·효과음도 걸릴 수 있으므로
    바로 바꾸지 않고, 다시 인식해서 확인하는 데만 쓴다."""
    threshold = speech_threshold(profile)
    covered = [False] * len(profile)
    for segment in segments:
        for index in range(max(0, segment.start // window_ms), min(len(profile), segment.end // window_ms + 1)):
            covered[index] = True
    allowed_dip = max(0, dip_ms // window_ms)
    ranges, start, quiet = [], None, 0
    for index in range(len(profile) + 1):
        loud = index < len(profile) and not covered[index] and profile[index] >= threshold
        if loud:
            if start is None:
                start = index
            quiet = 0
            continue
        if start is not None:
            quiet += 1
            if quiet > allowed_dip or index >= len(profile) or covered[index]:
                end = index - quiet + 1
                if (end - start) * window_ms >= min_ms:
                    ranges.append((start * window_ms, end * window_ms))
                start, quiet = None, 0
    return ranges


# ── 다시 인식할 구간 ──
@dataclass(frozen=True)
class Range:
    start: int
    end: int
    reason: str


def merge_ranges(ranges, *, pad=300, join=1000, minimum=1500, limit=24, total=None):
    """가까운 구간을 합치고 앞뒤를 조금 넓힌다. 이유는 앞의 것을 쓴다. 최대 limit개."""
    merged = []
    for item in sorted(ranges, key=lambda value: value.start):
        start = max(0, item.start - pad)
        end = item.end + pad if total is None else min(total, item.end + pad)
        if end - start < minimum:
            middle = (start + end) // 2
            start, end = max(0, middle - minimum // 2), max(minimum, middle + minimum // 2)
        if total is not None and end > total:          # 끝을 넘으면 앞으로 당긴다
            start, end = max(0, start - (end - total)), total
        if merged and start - merged[-1].end <= join:
            last = merged[-1]
            merged[-1] = Range(last.start, max(last.end, end), last.reason)
        else:
            merged.append(Range(start, end, item.reason))
    return merged[:limit]


def suspicious_ranges(segments, *, spaced=True, mismatched=()):
    """근거가 하나라도 있는 구간(다시 인식해 비교할 대상). mismatched: 언어가 다른 구간의 시작 ms."""
    found = []
    mismatched = set(mismatched)
    for segment in segments:
        signals = evidence(segment, spaced=spaced).signals
        if segment.start in mismatched:
            signals = signals + ('language mismatch',)
        if signals:
            found.append(Range(segment.start, segment.end, signals[0]))
    return found


# ── 후보 고르기 ──
@dataclass(frozen=True)
class Decision:
    range: Range
    original: str
    candidate: str
    accepted: bool
    why: str


def _quality(segments, spaced):
    """여러 구간의 대표 근거: 확신도는 글자 수 가중 평균, 나머지는 하나라도 나쁘면 나쁨."""
    if not segments:
        return None
    weights = [max(1, len(speech.normalize(item.text))) for item in segments]
    prob = sum(item.prob * weight for item, weight in zip(segments, weights)) / sum(weights)
    found = [evidence(item, spaced=spaced) for item in segments]
    return Evidence(prob, max(item.compression for item in found), max(item.rate for item in found),
                    any(item.loop for item in found), any(item.filler for item in found),
                    all(item.plausible_rate for item in found))


def choose(range_, original, candidate, *, spaced=True, margin=0.08):
    """원래 구간들과 다시 인식한 후보 중 하나를 고른다. 후보는 근거가 깨끗하고 명확히 나을 때만."""
    original_text = ' '.join(item.text for item in original).strip()
    candidate_text = ' '.join(item.text for item in candidate).strip()
    new = _quality(candidate, spaced)
    if new is None or not speech.normalize(candidate_text):
        return Decision(range_, original_text, candidate_text, False, 'no candidate text')
    if new.signals:
        return Decision(range_, original_text, candidate_text, False,
                        'candidate also suspicious: ' + ', '.join(new.signals))
    old = _quality(original, spaced)
    if old is None:                       # 발언 누락 후보: 깨끗하고 확신도가 충분할 때만 넣는다
        accepted = new.prob >= 0.55
        return Decision(range_, '', candidate_text, accepted,
                        'recovered missing speech' if accepted else 'candidate confidence too low')
    if speech.normalize(candidate_text) == speech.normalize(original_text):
        return Decision(range_, original_text, candidate_text, False, 'same text')
    broken = bool(old.signals and set(old.signals) - {'low confidence'})
    if broken or new.prob >= old.prob + margin:
        return Decision(range_, original_text, candidate_text, True,
                        'original had ' + ', '.join(old.signals) if broken else 'clearly higher confidence')
    return Decision(range_, original_text, candidate_text, False, 'not clearly better; kept original')


def replace_range(segments, range_, candidate):
    """range_와 겹치는 원래 구간을 후보로 바꾼다(후보는 range_ 안으로 자른다)."""
    kept = [item for item in segments if item.end <= range_.start or item.start >= range_.end]
    clipped = []
    for item in candidate:
        words = tuple(word for word in item.words if range_.start <= word.start < range_.end)
        if words:
            clipped.append(speech.Segment(words[0].start, min(words[-1].end, range_.end),
                                          ''.join(word.text for word in words).strip(), words, item.prob))
    return sorted(kept + clipped, key=lambda item: item.start)


def shift(segments, offset):
    """잘라 낸 오디오로 인식한 구간의 시각을 원래 오디오 기준으로 옮긴다."""
    out = []
    for item in segments:
        words = tuple(speech.Word(word.start + offset, word.end + offset, word.text, word.prob)
                      for word in item.words)
        out.append(speech.Segment(item.start + offset, item.end + offset, item.text, words, item.prob))
    return out


# ── 비슷한 이름 ──
_LATIN_NAME = re.compile(r'(?<![\w\'])([A-Z][a-z]{2,}(?:[-\'][A-Z]?[a-z]+)?)')
_KATAKANA_NAME = re.compile(r'[ァ-ヺー]{3,}')


def similar_names(segments, *, threshold=0.8, limit=20):
    """철자가 비슷한 고유명사 후보 쌍(예: Katherine / Catherine, シュタイン / シュタインズ).
    자동으로 통일하지 않고 확인용으로만 돌려준다. 문장 첫 단어는 고유명사로 보지 않는다."""
    counts = {}
    for item in segments:
        text = item.text.strip()
        for match in _LATIN_NAME.finditer(text):
            before = text[:match.start()].rstrip()
            if not before or before[-1] in '.?!"':
                continue
            counts[match.group(1)] = counts.get(match.group(1), 0) + 1
        for match in _KATAKANA_NAME.finditer(text):
            counts[match.group()] = counts.get(match.group(), 0) + 1
    names = sorted(counts, key=lambda name: (-counts[name], name))[:200]
    pairs = []
    for index, first in enumerate(names):
        for second in names[index + 1:]:
            if first.lower() == second.lower():
                continue
            if SequenceMatcher(None, first.lower(), second.lower()).ratio() >= threshold:
                pairs.append((first, counts[first], second, counts[second]))
    return pairs[:limit]
