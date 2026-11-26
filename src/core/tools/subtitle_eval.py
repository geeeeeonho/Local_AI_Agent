"""자막 품질 평가: 기준(사람이 만든) 자막과 생성 자막을 비교한다.

  * WER / CER — 단어·글자 단위 편집 거리 비율(띄어 쓰지 않는 언어는 CER이 주 지표)
  * 환각률 — 생성 자막이 기준 자막의 발화 시간 밖에 있는 비율(시간 기준)
  * 발언 누락률 — 기준 자막 발화 시간 중 생성 자막이 덮지 못한 비율
  * 타임스탬프 MAE — 가장 많이 겹치는 큐끼리 시작·끝 시각 차이의 평균(ms)
  * 과잉 교정 — 처리 전(baseline)보다 처리 후 큐가 기준에서 더 멀어진 비율(검수·재인식 효과 확인)

실측 데이터로 재인식 기준·검수 효과를 정하기 위한 도구다. 외부 의존이 없다.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


def _norm(text):
    text = unicodedata.normalize('NFKC', text).lower()
    return re.sub(r'[^\w\s]', ' ', text, flags=re.UNICODE)


def tokens(text):
    return _norm(text).split()


def characters(text):
    return [char for char in _norm(text) if not char.isspace()]


def edit_distance(first, second):
    """레벤슈타인 거리(두 줄만 쓰는 동적 계획법)."""
    if len(first) < len(second):
        first, second = second, first
    previous = list(range(len(second) + 1))
    for i, a in enumerate(first, 1):
        current = [i]
        for j, b in enumerate(second, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def error_rate(reference, hypothesis):
    return edit_distance(reference, hypothesis) / len(reference) if reference else float(bool(hypothesis))


def _intervals(cues):
    merged = []
    for cue in sorted(cues, key=lambda item: item.start):
        if merged and cue.start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], cue.end)
        else:
            merged.append([cue.start, cue.end])
    return merged


def _overlap(first, second):
    total, j = 0, 0
    for start, end in first:
        while j < len(second) and second[j][1] <= start:
            j += 1
        k = j
        while k < len(second) and second[k][0] < end:
            total += max(0, min(end, second[k][1]) - max(start, second[k][0]))
            k += 1
    return total


def _length(intervals):
    return sum(end - start for start, end in intervals)


def _best_match(cue, others):
    best, amount = None, 0
    for other in others:
        shared = min(cue.end, other.end) - max(cue.start, other.start)
        if shared > amount:
            best, amount = other, shared
    return best


@dataclass(frozen=True)
class Report:
    wer: float
    cer: float
    hallucination: float
    omission: float
    timestamp_mae: float | None
    matched: int
    reference_cues: int
    hypothesis_cues: int

    def lines(self):
        return ['WER %.1f%% · CER %.1f%%' % (self.wer * 100, self.cer * 100),
                '환각률(기준 발화 밖) %.1f%% · 발언 누락률 %.1f%%' % (self.hallucination * 100, self.omission * 100),
                '타임스탬프 MAE %s · 대응 큐 %d / 기준 %d / 생성 %d' % (
                    '%.0f ms' % self.timestamp_mae if self.timestamp_mae is not None else '-',
                    self.matched, self.reference_cues, self.hypothesis_cues)]


def evaluate(reference, hypothesis):
    ref_text = ' '.join(cue.text for cue in reference)
    hyp_text = ' '.join(cue.text for cue in hypothesis)
    ref_time, hyp_time = _intervals(reference), _intervals(hypothesis)
    shared = _overlap(ref_time, hyp_time)
    errors = []
    for cue in hypothesis:
        match = _best_match(cue, reference)
        if match is not None:
            errors.append((abs(cue.start - match.start) + abs(cue.end - match.end)) / 2)
    return Report(error_rate(tokens(ref_text), tokens(hyp_text)),
                  error_rate(characters(ref_text), characters(hyp_text)),
                  1 - shared / _length(hyp_time) if hyp_time else 0.0,
                  1 - shared / _length(ref_time) if ref_time else 0.0,
                  sum(errors) / len(errors) if errors else None, len(errors), len(reference), len(hypothesis))


@dataclass(frozen=True)
class Change:
    improved: int
    worsened: int               # 과잉 교정: 처리 후 기준에서 더 멀어짐
    unchanged: int

    @property
    def overcorrection(self):
        changed = self.improved + self.worsened
        return self.worsened / changed if changed else 0.0


def compare(reference, before, after):
    """처리 전·후 자막을 기준 큐마다 비교한다(그 기준 큐 시간과 겹치는 글의 CER)."""
    improved = worsened = unchanged = 0
    for cue in reference:
        def text_in(cues):
            return ' '.join(item.text for item in cues if item.end > cue.start and item.start < cue.end)
        target = characters(cue.text)
        old = error_rate(target, characters(text_in(before)))
        new = error_rate(target, characters(text_in(after)))
        if abs(old - new) < 1e-9:
            unchanged += 1
        elif new < old:
            improved += 1
        else:
            worsened += 1
    return Change(improved, worsened, unchanged)
