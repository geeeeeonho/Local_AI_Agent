"""대본 맞추기 모의 시험 도우미: whisper처럼 틀리는 인식 결과(통째로 건너뜀·앞부분만·글자 오류·띄어쓰기
차이·무음에서 지어낸 문장·대본에 없는 말·시각 흔들림)를 만들고, 말하는 동안 자막이 비는 비율을 잰다."""
import random

from core.tools.script_align import align
from core.tools.subtitles import Word, build_cues, rules_for

SYL = '가나다라마바사아자차카타파하고노도로모보소오조초코토포호구누두루무부수우주기니디리미비시이지치는을를에서도만요죠네'
FATES = []


def make_script(rng, count):
    lines = []
    for _ in range(count):
        words = [''.join(rng.choice(SYL) for _ in range(rng.randint(1, 4))) for _ in range(rng.randint(2, 9))]
        text = ' '.join(words)
        if rng.random() < 0.3 and len(words) > 4:
            cut = rng.randint(2, len(words) - 2)
            text = ' '.join(words[:cut]) + ', ' + ' '.join(words[cut:])
        lines.append(text + rng.choice('.....?!'))
    return lines


def simulate(rng, lines, *, p_drop=0.07, p_partial=0.08, p_hallu=0.06, p_adlib=0.03, p_shift=0.05, err=0.10):
    """→ (인식 단어, 정답 줄 구간 [(시작, 끝)], 말소리 구간 [(시작, 끝)])"""
    t, words, truth, speech_regions = 500, [], [], []
    FATES.clear()
    for line in lines:
        gap = rng.choice([250, 400, 600, 800, 1200]) if rng.random() > 0.08 else rng.randint(3000, 8000)
        if gap > 2500 and rng.random() < p_hallu:            # 무음·음악에서 지어낸 문장
            fake = ' '.join(''.join(rng.choice(SYL) for _ in range(3)) for _ in range(4))
            for i, w in enumerate(fake.split()):
                words.append(Word(t + 500 + i * 400, t + 850 + i * 400, ' ' + w, 0.4))
        t += gap
        if rng.random() < p_adlib:                            # 대본에 없는 말
            for _ in range(rng.randint(3, 8)):
                w = ''.join(rng.choice(SYL) for _ in range(rng.randint(1, 3)))
                d = len(w) * 160
                words.append(Word(t, t + d, ' ' + w, 0.8)); t += d + 100
            speech_regions.append((t - 1000, t)); t += 400
        start = t
        spoken = []
        for raw in line.split():
            d = max(1, len([c for c in raw if c.isalpha()])) * rng.randint(130, 190)
            spoken.append((t, t + d, raw))
            t += d + (rng.randint(500, 900) if raw.endswith(',') else rng.randint(60, 160))
        truth.append((start, t))
        speech_regions.append((start, t))
        fate = rng.random()
        FATES.append('drop' if fate < p_drop else 'partial' if fate < p_drop + p_partial else 'ok')
        if fate < p_drop:
            continue                                          # whisper가 통째로 건너뜀
        if fate < p_drop + p_partial:
            spoken = spoken[:max(1, len(spoken) // 2)]       # 앞부분만
        shift = rng.choice([-400, 400]) if rng.random() < p_shift else 0
        merged = []
        for s, e, raw in spoken:                              # 띄어쓰기 다르게(붙여 씀)
            if merged and rng.random() < 0.2:
                ps, _pe, ptext = merged[-1]
                merged[-1] = (ps, e, ptext + raw)
            else:
                merged.append((s, e, raw))
        for s, e, raw in merged:
            text = ''.join(c if rng.random() > err else rng.choice(SYL) for c in raw)
            if rng.random() < 0.5:
                text = text.rstrip('.,?!')
            jitter = rng.randint(-120, 120)
            words.append(Word(max(0, s + jitter + shift), max(1, e + jitter + shift), ' ' + text, 0.9))
    words.sort(key=lambda w: w.start)
    # 인식 단어를 시간 순서대로(speech.words_of처럼 겹침은 뒤로 민다)
    out = []
    for w in words:
        if out and w.start < out[-1].end:
            w = Word(max(w.start, out[-1].end), max(w.end, out[-1].end + 1), w.text, w.prob)
        out.append(w)
    return out, truth, speech_regions


def overlap(a, b):
    return max(0, min(a[1], b[1]) - max(a[0], b[0]))


def overlap(a, b):
    return max(0, min(a[1], b[1]) - max(a[0], b[0]))


def evaluate(seed, *, speech_regions=True, **kwargs):
    """→ (말하는 동안 자막이 빈 비율, 정답 시간과 30% 미만 겹친 줄 수, 줄 수)"""
    rng = random.Random(seed)
    lines = make_script(rng, 150)
    words, truth, regions = simulate(rng, lines, **kwargs)
    placed = align('\n'.join(lines), words, spaced=True, speech=regions if speech_regions else ())
    cues = build_cues(placed.words, rules_for('ko'), boundaries=placed.boundaries)
    speech_total = sum(e - s for s, e in truth)
    uncovered = sum(max(0, (e - s) - sum(overlap((s, e), (c.start, c.end)) for c in cues)) for s, e in truth)
    starts = list(placed.line_starts) + [len(placed.words)]
    misplaced = 0
    for index, (s, e) in enumerate(truth):
        line_words = placed.words[starts[index]:starts[index + 1]]
        shown = [c for c in cues if any(c.start - 1 <= w.start <= c.end for w in line_words)]
        if sum(overlap((s, e), (c.start, c.end)) for c in shown) < 0.3 * (e - s):
            misplaced += 1
    return uncovered / speech_total, misplaced, len(lines)
