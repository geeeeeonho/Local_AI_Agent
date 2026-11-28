"""자막 문법: 단어 시각 → 자막 큐, 줄 나눔, 표시 시간, SRT·WebVTT 쓰기와 읽기.

규칙은 방송·스트리밍 자막 지침에서 널리 쓰는 값을 따른다.

* 한 큐는 최대 2줄, 한 줄 글자 수는 언어별(라틴 문자 42, 한국어·중국어 16, 일본어 13).
  한 줄에 들어가면 한 줄로 두고, 두 줄이면 단어·구절 경계에서 길이를 맞춰 나눈다.
* 표시 시간은 최소 5/6초(833ms) · 최대 7초, 큐 사이는 최소 2프레임(83ms)을 비운다.
  0.5초보다 짧은 틈은 2프레임으로 이어 붙여(chaining) 화면이 깜박이지 않게 한다.
* 읽기 속도(초당 글자 수)를 넘으면 말이 끝난 뒤에도 다음 큐 전까지 더 오래 보여 준다.
* 한 문장은 되도록 한 큐에, 긴 문장은 쉼표·접속사·쉼(무음) 앞뒤에서 나눈다.

외부 의존이 없고 화면·실행 파일을 모른다. 같은 규칙을 원문 자막과 번역 자막이 함께 쓴다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class Word:
    """인식된 한 단어(또는 한중일 문자 몇 개). text는 앞 공백을 포함한 원래 모양 그대로다."""
    start: int              # ms
    end: int                # ms
    text: str
    prob: float = 1.0


@dataclass(frozen=True)
class Cue:
    start: int              # ms
    end: int                # ms
    lines: tuple
    confidence: float = 1.0

    @property
    def text(self):
        return '\n'.join(self.lines)


@dataclass(frozen=True)
class Rules:
    max_chars: int = 42     # 한 줄 최대 글자 수
    max_lines: int = 2
    cps: float = 17.0       # 읽기 속도(초당 글자 수)
    min_ms: int = 833       # 5/6초
    max_ms: int = 7000
    gap_ms: int = 83        # 2프레임(24fps)
    chain_ms: int = 500     # 이보다 짧은 틈은 gap_ms로 이어 붙인다
    pause_ms: int = 700     # 이만큼 말이 끊기면 큐를 닫는다
    spaced: bool = True     # 단어를 공백으로 띄어 쓰는 언어인지

    @property
    def capacity(self):
        return self.max_chars * self.max_lines


# 언어별 줄 길이·읽기 속도. 없는 언어는 기본값(라틴 문자 기준)을 쓴다.
_LANGUAGE_RULES = {
    'ko': dict(max_chars=16, cps=12.0),
    'ja': dict(max_chars=13, cps=4.0, spaced=False),
    'zh': dict(max_chars=16, cps=9.0, spaced=False),
    'yue': dict(max_chars=16, cps=9.0, spaced=False),
    'th': dict(max_chars=35, cps=15.0, spaced=False),
    'ar': dict(max_chars=42, cps=17.0),
    'he': dict(max_chars=42, cps=17.0),
}


def rules_for(language, *, max_chars=None, max_lines=None):
    """언어 코드('ko', 'en', 'zh-Hant' …)의 규칙. 사용자가 정한 줄 길이·줄 수가 있으면 그 값."""
    code = str(language or '').split('-')[0].lower()
    values = dict(_LANGUAGE_RULES.get(code, {}))
    if max_chars:
        values['max_chars'] = max(4, int(max_chars))
    if max_lines:
        values['max_lines'] = max(1, min(3, int(max_lines)))
    return Rules(**values)


# ── 글자 분류 ──
SENTENCE_END = frozenset('.?!。？！…‼⁇⁈⁉')
CLAUSE_END = frozenset(',;:、，；：—–')
CLOSERS = frozenset('"\'»」』）)]】〉》’”')
# 줄 머리에 올 수 없는 글자(일본어·중국어 줄 바꿈 금칙)
NO_LINE_START = frozenset('、。，．,.!?！？)]}）」』】〉》’”ゝゞーぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶ々…‥・:;：；')
NO_LINE_END = frozenset('([{（「『【〈《‘“')
# 영어 등에서 줄 끝에 남기지 않는 기능어, 줄 머리에 두기 좋은 접속어
_WEAK_END = frozenset('a an the of to in on at for with by from into onto my your his her its our their '
                      'this that these those and or but if as is are was were be de la le les des du '
                      'el los las un una et ou der die das ein eine und oder zu von mit'.split())
_GOOD_START = frozenset('and but or so because when while which who that if then although though '
                        'however unless until since where after before et mais ou donc parce quand '
                        'und aber oder weil wenn dass y pero porque cuando que e ma perché quando '
                        '그리고 그러나 하지만 그런데 그래서 그러면 그러니까 왜냐하면 또는 혹은 그래도 근데'.split())
_LATIN_RUN = re.compile(r'[A-Za-z0-9À-ɏ]')
# 한중일: 이 글자 뒤에서 줄을 바꾸면 자연스럽다(일본어 조사·중국어 구조 조사).
_PARTICLE_END = frozenset('はがをにでともへやのか的了地得着过和与在把被')
_KATAKANA = re.compile(r'[゠-ヿㇰ-ㇿー]')
_KANJI = re.compile(r'[一-鿿㐀-䶿々]')
_HIRAGANA = re.compile(r'[ぁ-ゖ]')

# 한국어: 띄어 쓰지만 앞말에 기대는 말이 있다. 그 앞에서 줄을 바꾸면 낱말이 끊겨 보인다.
_HANGUL = re.compile(r'[가-힣]')
_KO_PARTICLES = frozenset('은 는 이 가 을 를 의 에 에서 에게 께 께서 한테 로 으로 와 과 도 만 까지 부터 처럼 '
                          '보다 이나 나 랑 이랑 하고 요 이다 입니다 예요 이에요 이야 야'.split())
# 관형형(-ㄴ/-ㄹ/-는/-던) 뒤에 오는 의존 명사. 뒤에 붙는 조사·어미까지만 허용한다(수학, 것처럼 구분).
_KO_BOUND = ('때문', '덕분', '만큼', '대로', '동안', '무렵', '듯이', '수', '것', '거', '게', '걸', '건', '겁',
             '줄', '데', '뿐', '듯', '척', '체', '채', '터', '셈', '리', '바', '때', '적', '지', '뻔')
_KO_BOUND_REST = frozenset(('', '이', '가', '은', '는', '을', '를', '도', '만', '에', '에는', '에도', '이다',
                            '입니다', '이에요', '예요', '이야', '야', '이지만', '지만', '죠', '요', '처럼',
                            '이라', '라', '라고', '이라고', '으로', '로', '인', '일', '이고', '고', '밖에', '부터'))
# 보조 용언: 앞말의 연결 어미(마지막 음절)와 함께 쓰이는 말의 첫머리.
_KO_AUXILIARY = (('고', ('있', '계', '싶', '나서')),
                 ('지', ('않', '못하', '못해', '못했')),
                 ('게', ('되', '돼', '됐', '하', '해', '했', '만들')),
                 ('야', ('하', '해', '했', '돼', '되', '됐')),
                 # '-아/-어' 꼴. 조사와 헷갈리는 '와·가'와 흔한 낱말 첫머리(가·오·내·지)는 넣지 않는다.
                 ('아어여워해돼려쳐겨져줘봐놔둬써', ('주', '줘', '준', '줄', '줍', '드리', '드려', '드릴', '드립',
                                                    '보', '봐', '봤', '본', '볼', '봅', '버리', '버려', '버렸',
                                                    '놓', '놔', '두', '둬', '있')))
_KO_NOT_ENDING = frozenset('그게 이게 저게 내게 네게 제게 뭐게 그래야 이래야'.split())  # 대명사+조사
_KO_COUNTER_HEADS = ('개', '명', '번', '살', '시', '분', '초', '마리', '권', '잔', '대', '장', '가지', '년', '달',
                     '주', '시간', '층', '배', '곳', '군데', '사람', '병', '그릇', '켤레', '쌍')
_KO_NATIVE_NUMBERS = frozenset('한 두 세 네 다섯 여섯 일곱 여덟 아홉 열 스무 몇 여러'.split())
_KO_CONNECTIVE = ('지만', '는데', '은데', '니까', '면서', '도록', '려고', '으며', '고', '서', '면', '며')
_NUMBER = re.compile(r'^[+-]?\d[\d,.]*%?$')


def _bound_after(tail):
    """tail(앞 어절)이 관형형으로 끝나는가: 받침 ㄴ·ㄹ 또는 '는/던'."""
    last = tail[-1:]
    if not _HANGUL.match(last):
        return False
    return last in '는던' or (ord(last) - 0xAC00) % 28 in (4, 8)


def _korean_score(tail, head):
    """한국어 어절 사이에서 끊을 때의 점수. 앞말에 기대는 말(조사·의존 명사·보조 용언·단위) 앞은 피한다."""
    if head in _KO_PARTICLES:
        return -4.0                 # 조사가 떨어져 있다(띄어쓰기 오류): 줄을 바꾸면 낱말이 끊겨 보인다
    if _bound_after(tail) and any(head.startswith(noun) and head[len(noun):] in _KO_BOUND_REST
                                  for noun in _KO_BOUND):
        return -3.0                 # '할 / 수 있다', '모르는 / 것'
    for endings, stems in _KO_AUXILIARY:
        if tail[-1:] in endings and head.startswith(stems) and tail not in _KO_NOT_ENDING:
            return -2.5             # '하고 / 있다', '해 / 주세요', '가지 / 않는다'
    if tail in _KO_NATIVE_NUMBERS and head.startswith(_KO_COUNTER_HEADS):
        return -2.5                 # '세 / 개', '두 / 명'
    if tail.endswith(_KO_CONNECTIVE) and _HANGUL.match(head[:1] or ' '):
        return 1.0                  # '…했지만 / …', '…하고 / …': 절이 끝나는 곳
    return 0.0


# 이 점수보다 낮은 곳(낱말·어절이 끊겨 보이는 곳)에서는 줄을 바꾸지 않는다. 다른 곳이 없으면 큐를 나누거나
# (시간이 짧으면) 줄을 조금 길게 쓴다(force_wrap).
BAD_BREAK = -2.0


def boundary_score(left, right, spaced):
    """left 뒤·right 앞에서 끊을 때의 자연스러움. 클수록 좋은 위치다."""
    a, b = left.rstrip(), right.lstrip()
    if not a or not b:
        return 0.0
    last = _last_char(a)
    if last in SENTENCE_END:
        return 4.0
    if last in CLAUSE_END:
        return 2.5
    if spaced:
        tail = a.rsplit(None, 1)[-1].lower().strip('.,;:!?"\'')
        head = b.split(None, 1)[0].lower().strip('.,;:!?"\'')
        if _NUMBER.match(tail) and len(head) <= 4:
            return -3.0             # 숫자와 단위('3 / 센치', '10 / km')
        score = 0.0
        if head in _GOOD_START:
            score += 1.5
        if tail in _WEAK_END:
            score -= 2.0
        if _HANGUL.match(tail[-1:]) and _HANGUL.match(head[:1]):
            score += _korean_score(tail, head)
        return score
    if b[0] in NO_LINE_START or a[-1] in NO_LINE_END:
        return -10.0
    if (_KATAKANA.match(a[-1]) and _KATAKANA.match(b[0])) or \
            (_LATIN_RUN.match(a[-1]) and _LATIN_RUN.match(b[0])):
        return -4.0                 # 가타카나 낱말·라틴 단어 한가운데
    score = 0.0
    if a[-1] in _PARTICLE_END and b[0] not in _PARTICLE_END:
        score += 1.5
    if _KANJI.match(a[-1]) and _KANJI.match(b[0]):
        score -= 1.5                # 한자어 한가운데일 가능성
    if _KANJI.match(a[-1]) and _HIRAGANA.match(b[0]):
        score -= 2.5                # 한자 → 히라가나: 활용 어미('新/しい')나 조사가 떨어진다
    if _HIRAGANA.match(a[-1]) and (_KANJI.match(b[0]) or _KATAKANA.match(b[0])):
        score += 1.0                # 히라가나 → 한자·가타카나: 대개 낱말 경계
    elif _HIRAGANA.match(a[-1]) and _HIRAGANA.match(b[0]) and a[-1] not in _PARTICLE_END:
        score -= 1.0                # 히라가나 낱말·어미 한가운데일 가능성
    if a[-1] in 'すまだ' and b[0] in 'すまだしたよね':
        score -= 2.0                # 'し/ます' 'です/ね' 같은 어미 사이
    return score


def _last_char(text):
    text = text.rstrip()
    while text and text[-1] in CLOSERS:
        text = text[:-1]
    return text[-1:] if text else ''


def ends_sentence(text):
    return _last_char(text) in SENTENCE_END


def display_length(text):
    return len(text.strip())


def _join(words):
    return ''.join(word.text for word in words).strip()


# ── 줄 나눔 ──
def _pieces(text, spaced):
    """줄을 나눌 수 있는 위치로 자른 조각. 띄어 쓰는 언어는 단어, 아니면 글자(라틴 단어·숫자는 통째로)."""
    if spaced:
        return [piece for piece in re.split(r'(?<=\S)(?=\s)', text) if piece]
    pieces, current = [], ''
    for char in text:
        if current and _LATIN_RUN.match(char) and _LATIN_RUN.match(current[-1]):
            current += char
            continue
        if current and (char in NO_LINE_START or current[-1] in NO_LINE_END or char.isspace()):
            current += char
            continue
        if current:
            pieces.append(current)
        current = char
    if current:
        pieces.append(current)
    return pieces


def _break_cost(first, second, spaced):
    """두 줄로 나눌 때의 비용. 작을수록 좋다(길이 균형 + 끊는 위치의 자연스러움)."""
    a, b = first.strip(), second.strip()
    # 끊는 위치의 자연스러움(문장부호 뒤·접속사 앞)을 길이 균형보다 우선한다. 균형은 그다음.
    cost = abs(len(a) - len(b)) * 0.4
    if len(b) < len(a):
        cost += 0.8                 # 아랫줄이 긴 피라미드 모양을 조금 더 선호
    return cost - boundary_score(a, b, spaced) * 4.0


def _token_pieces(words):
    """인식 토큰 경계를 줄 나눔 위치로 쓴다(한중일은 토큰이 대개 낱말이다). 문장부호는 앞에 붙인다."""
    pieces = []
    for word in words:
        text = word.text
        if pieces and (not text.strip() or text.strip()[0] in NO_LINE_START or pieces[-1][-1:] in NO_LINE_END):
            pieces[-1] += text
        else:
            pieces.append(text)
    if pieces:
        pieces[0] = pieces[0].lstrip()
    return pieces


def wrap(text, rules, pieces=None):
    """한 큐의 글을 규칙에 맞는 줄들로 나눈다. 넣을 수 없으면 None.
    pieces를 주면 그 경계에서만 나눈다(인식 토큰), 없으면 단어·글자 경계."""
    text = ' '.join(text.split()) if rules.spaced else re.sub(r'\s*\n\s*', '', text).strip()
    if not text:
        return ()
    if display_length(text) <= rules.max_chars:
        return (text,)
    if rules.max_lines < 2:
        return None
    if pieces is None or ''.join(pieces).strip() != text:
        pieces = _pieces(text, rules.spaced)
    best = None
    for cut in range(1, len(pieces)):
        first = ''.join(pieces[:cut]).strip()
        rest = ''.join(pieces[cut:]).strip()
        if display_length(first) > rules.max_chars:
            break
        if boundary_score(first, rest, rules.spaced) < BAD_BREAK:
            continue
        if rules.max_lines == 2:
            if display_length(rest) > rules.max_chars:
                continue
            tail = (rest,)
        else:
            tail = wrap(rest, replace(rules, max_lines=rules.max_lines - 1), pieces[cut:])
            if tail is None:
                continue
        cost = _break_cost(first, tail[0], rules.spaced)
        if best is None or cost < best[0]:
            best = (cost, (first,) + tuple(tail))
    return best[1] if best else None


def force_wrap(text, rules, pieces=None):
    """규칙에 맞게 나눌 수 없는 글도 낱말을 자르지 않고 표시한다.
    1) 줄 수는 지키고 줄을 조금(최대 1.5배) 길게, 2) 그래도 안 되면 줄을 늘린다(낱말 경계에서만).
    띄어 쓰지 않은 한 덩어리가 1.5배보다 길 때만 그 길이에서 자른다."""
    lines = wrap(text, rules, pieces)
    if lines is not None:
        return lines
    limit = max(rules.max_chars + 1, int(rules.max_chars * 1.5))
    for width in range(rules.max_chars + 1, limit + 1):
        lines = wrap(text, replace(rules, max_chars=width), pieces)
        if lines is not None:
            return lines
    flat = ' '.join(text.split()) if rules.spaced else re.sub(r'\s*\n\s*', '', text).strip()
    out, current = [], ''
    for piece in _pieces(flat, rules.spaced):
        if current.strip() and display_length(current + piece) > rules.max_chars:
            out.append(current.strip())
            current = piece.lstrip()
        else:
            current += piece
        while display_length(current) > limit:
            out.append(current.strip()[:limit])
            current = current.strip()[limit:]
    if current.strip():
        out.append(current.strip())
    return tuple(out)


def fits(words, rules):
    return wrap(_join(words), rules, None if rules.spaced else _token_pieces(words)) is not None


# ── 단어 → 큐 ──
def _split_point(words, rules, *, tail_must_fit=False):
    """넘친 큐를 나눌 가장 좋은 위치(앞 단어 개수). 앞부분은 용량의 35% 이상이어야 한다.
    tail_must_fit이면 뒷부분도 한 큐에 들어가고 35% 이상인 위치만 고른다(문장을 두 큐로 균형 있게)."""
    total = display_length(_join(words))
    best, best_score = None, None
    for cut in range(1, len(words)):
        head = words[:cut]
        if not fits(head, rules):
            break
        size = display_length(_join(head))
        if size < max(1, min(rules.capacity, total) * 0.35):
            continue
        if tail_must_fit:
            tail = words[cut:]
            if not fits(tail, rules) or display_length(_join(tail)) < rules.capacity * 0.35 \
                    or tail[-1].end - tail[0].start > rules.max_ms:
                continue
        gap = words[cut].start - words[cut - 1].end
        score = size / rules.capacity            # 많이 채울수록 조금 좋다
        score += boundary_score(_join(head), words[cut].text, rules.spaced)
        if gap >= 250:
            score += min(gap, 1500) / 500.0
        if best_score is None or score > best_score:
            best, best_score = cut, score
    return best


def _next_sentence(words, index, rules=None, hard=()):
    """index부터 문장이 끝나는 단어까지(포함). rules를 주면 긴 쉼·강제 경계 앞에서 멈춘다."""
    for end in range(index, len(words)):
        if end > index and (end in hard or (rules is not None and
                                            words[end].start - words[end - 1].end >= rules.pause_ms)):
            return words[index:end]
        if ends_sentence(words[end].text):
            return words[index:end + 1]
    return words[index:]


def group_words(words, rules, *, boundaries=()):
    """단어를 큐 단위로 묶는다. boundaries는 반드시 끊어야 하는 단어 위치(앞에서 끊음)."""
    words = [word for word in words if word.text.strip()]
    hard = set(boundaries)
    groups, current = [], []
    index = 0
    opened_at_sentence = True        # 지금 큐가 문장 첫머리에서 시작했는지
    while index < len(words):
        word = words[index]
        if current:
            gap = word.start - current[-1].end
            close = (index in hard or gap >= rules.pause_ms
                     or word.end - current[0].start > rules.max_ms)
            if not close and ends_sentence(current[-1].text):
                # 짧은 문장 여러 개("네. 알겠어요.")는 다음 문장까지 한 큐에 들어가면 붙인다.
                # 앞 큐에서 이어진 문장 꼬리는 새 문장과 섞지 않는다.
                upcoming = _next_sentence(words, index)
                together = current + upcoming
                close = (not opened_at_sentence or not fits(together, rules)
                         or together[-1].end - current[0].start > rules.max_ms
                         or display_length(_join(current)) >= rules.capacity * 0.5
                         or gap >= 300
                         or any(i in hard for i in range(index, index + len(upcoming))))
            if close:
                groups.append(current)
                opened_at_sentence = ends_sentence(current[-1].text)
                current = []
            elif not fits(current + [word], rules):
                # 문장 끝까지 보고 두 큐로 균형 있게 나눌 수 있으면 그렇게 한다
                # (앞 큐를 꽉 채우고 꼬리 한두 낱말만 다음 큐로 넘기지 않게).
                span = current + _next_sentence(words, index, rules, hard)
                if ends_sentence(span[-1].text) and not fits(span, rules):
                    cut = _split_point(span, rules, tail_must_fit=True)
                    if cut is not None:
                        groups.append(span[:cut])
                        opened_at_sentence = ends_sentence(span[cut - 1].text)
                        index = index - len(current) + cut      # span[cut]의 위치
                        current = []
                        continue
                cut = _split_point(current + [word], rules)
                if cut is None or cut >= len(current) + 1:
                    groups.append(current)
                    opened_at_sentence = ends_sentence(current[-1].text)
                    current = []
                else:
                    merged = current + [word]
                    groups.append(merged[:cut])
                    opened_at_sentence = ends_sentence(merged[cut - 1].text)
                    current = merged[cut:]
                    index += 1
                    continue
        current.append(word)
        index += 1
    if current:
        groups.append(current)
    return groups


def _confidence(words):
    return sum(word.prob for word in words) / len(words) if words else 1.0


def _merge_short(groups, rules, starts=frozenset()):
    """최소 표시 시간을 채울 수 없는 짧은 큐(다음 큐가 바로 이어짐)는 앞이나 뒤 큐에 합친다.
    starts: 반드시 큐 첫머리여야 하는 단어(id) — 그 앞에서는 합치지 않는다(대본 줄 경계 등)."""
    out = []
    for index, group in enumerate(groups):
        nxt = groups[index + 1] if index + 1 < len(groups) else None
        room = (nxt[0].start - rules.gap_ms if nxt else group[-1].end + rules.min_ms) - group[0].start
        if room >= rules.min_ms:
            out.append(group)
            continue
        previous = out[-1] if out else None
        if previous and id(group[0]) not in starts and group[0].start - previous[-1].end < rules.pause_ms \
                and fits(previous + group, rules) and group[-1].end - previous[0].start <= rules.max_ms:
            out[-1] = previous + group
        elif nxt and id(nxt[0]) not in starts and nxt[0].start - group[-1].end < rules.pause_ms \
                and fits(group + nxt, rules) and nxt[-1].end - group[0].start <= rules.max_ms:
            groups[index + 1] = group + nxt
        else:
            out.append(group)
    return out


def build_cues(words, rules, *, boundaries=()):
    """인식된 단어를 규칙에 맞는 자막 큐로 만든다(줄 나눔·표시 시간 포함)."""
    cues = []
    kept = [word for word in words if word.text.strip()]       # group_words와 같은 위치 기준
    starts = frozenset(id(kept[index]) for index in boundaries if 0 <= index < len(kept))
    for group in _merge_short(group_words(kept, rules, boundaries=boundaries), rules, starts):
        text = _join(group)
        if not text:
            continue
        pieces = None if rules.spaced else _token_pieces(group)
        cues.append(Cue(group[0].start, max(group[-1].end, group[0].start + 1),
                        force_wrap(text, rules, pieces), _confidence(group)))
    return retime(cues, rules)


def retime(cues, rules):
    """표시 시간 규칙: 최소·최대 표시 시간, 읽기 속도만큼 연장, 큐 사이 간격·이어 붙이기."""
    cues = sorted((cue for cue in cues if cue.lines), key=lambda cue: (cue.start, cue.end))
    out = []
    for index, cue in enumerate(cues):
        start = max(0, cue.start)
        if out and start < out[-1].end + rules.gap_ms:
            start = out[-1].end + rules.gap_ms
        chars = sum(display_length(line) for line in cue.lines)
        wanted = max(rules.min_ms, int(chars / rules.cps * 1000)) if rules.cps else rules.min_ms
        end = max(cue.end, start + min(wanted, rules.max_ms))
        end = min(end, start + rules.max_ms) if cue.end - start <= rules.max_ms else cue.end
        nxt = cues[index + 1].start if index + 1 < len(cues) else None
        if nxt is not None:
            limit = nxt - rules.gap_ms
            if end > limit:
                end = max(limit, start + 1)
            elif 0 < nxt - end < rules.chain_ms:
                end = limit
        if end <= start:
            end = start + 1
        out.append(replace(cue, start=start, end=end))
    return out


# ── 검토 ──
@dataclass(frozen=True)
class Review:
    index: int              # 1부터
    reason: str


def review(cues, rules, *, low_confidence=0.45):
    """사람이 확인하면 좋은 큐: 인식 확신도 낮음, 읽기 속도 초과, 줄 규칙 초과."""
    found = []
    for number, cue in enumerate(cues, 1):
        chars = sum(display_length(line) for line in cue.lines)
        seconds = max(0.001, (cue.end - cue.start) / 1000)
        if cue.confidence < low_confidence:
            found.append(Review(number, 'low confidence'))
        if rules.cps and chars / seconds > rules.cps * 1.35 and chars > rules.max_chars // 2:
            found.append(Review(number, 'fast reading speed'))
        if len(cue.lines) > rules.max_lines or any(display_length(line) > rules.max_chars
                                                    for line in cue.lines):
            found.append(Review(number, 'line too long'))
    return found


# ── 다시 나누기(번역 자막) ──
def _halves(text, rules):
    """한 큐에 들어가지 않는 글을 자연스러운 경계에서 둘로 나눈다(길이는 되도록 비슷하게)."""
    pieces = _pieces(text, rules.spaced)
    best = None
    for cut in range(1, len(pieces)):
        first, second = ''.join(pieces[:cut]).strip(), ''.join(pieces[cut:]).strip()
        if not first or not second:
            continue
        cost = abs(len(first) - len(second)) * 0.15 - boundary_score(first, second, rules.spaced) * 4.0
        if best is None or cost < best[0]:
            best = (cost, first, second)
    return best[1:] if best else None


def _fit(text, start, end, rules, depth=0):
    """글을 시간 [start, end]의 큐들로: 한 큐에 넣을 수 없으면 둘로 나누고 시간은 글자 수 비율로 나눈다."""
    lines = wrap(text, rules)
    halves = None if lines is not None or depth >= 3 else _halves(text, rules)
    if halves is None or end - start < rules.min_ms * 2:
        return [(start, end, lines if lines is not None else force_wrap(text, rules))]
    first, second = halves
    middle = start + int((end - start) * len(first) / max(1, len(first) + len(second)))
    return (_fit(first, start, middle - rules.gap_ms // 2, rules, depth + 1)
            + _fit(second, middle + rules.gap_ms - rules.gap_ms // 2, end, rules, depth + 1))


def reflow(cues, rules):
    """시각을 유지하면서 각 큐의 글을 규칙에 맞게 다시 나눈다(번역문은 원문보다 길거나 짧다).
    번역문이 한 큐(최대 줄 수)에 들어가지 않으면 그 큐의 시간 안에서 둘로 나눈다."""
    out = []
    for cue in cues:
        text = (' ' if rules.spaced else '').join(line.strip() for line in cue.lines)
        for start, end, lines in _fit(text, cue.start, cue.end, rules):
            if lines:
                out.append(replace(cue, start=start, end=end, lines=lines))
    return retime(out, rules)


# ── 쓰기 ──
def timestamp(ms, *, separator=','):
    ms = max(0, int(round(ms)))
    hours, rest = divmod(ms, 3600000)
    minutes, rest = divmod(rest, 60000)
    seconds, millis = divmod(rest, 1000)
    return '%02d:%02d:%02d%s%03d' % (hours, minutes, seconds, separator, millis)


def _safe(line):
    # 시간 구분자와 빈 줄은 자막 구조를 깨뜨린다.
    return line.replace('-->', '→').strip()


def to_srt(cues):
    """SubRip: 번호, 'HH:MM:SS,mmm --> HH:MM:SS,mmm', 글, 빈 줄. 줄 끝은 CRLF(구형 재생기 호환)."""
    blocks = []
    for number, cue in enumerate(cues, 1):
        lines = [_safe(line) for line in cue.lines if _safe(line)]
        if not lines:
            continue
        blocks.append('%d\r\n%s --> %s\r\n%s\r\n' % (
            len(blocks) + 1, timestamp(cue.start), timestamp(cue.end), '\r\n'.join(lines)))
    return '\r\n'.join(blocks)


def _vtt_escape(line):
    return line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def to_vtt(cues):
    """WebVTT: 'WEBVTT' 머리, 'HH:MM:SS.mmm --> HH:MM:SS.mmm', &·<·> 이스케이프."""
    out = ['WEBVTT', '']
    for cue in cues:
        lines = [_vtt_escape(_safe(line)) for line in cue.lines if _safe(line)]
        if not lines:
            continue
        out.append('%s --> %s' % (timestamp(cue.start, separator='.'),
                                  timestamp(cue.end, separator='.')))
        out.extend(lines)
        out.append('')
    return '\n'.join(out)


FORMATS = {'srt': ('.srt', to_srt), 'vtt': ('.vtt', to_vtt)}


def render(cues, fmt):
    return FORMATS[fmt][1](cues)


# ── 읽기 ──
_TIME = r'(?:(\d{1,3}):)?(\d{1,2}):(\d{2})[,.](\d{1,3})'
_CUE_TIME = re.compile(r'^\s*' + _TIME + r'\s*-->\s*' + _TIME + r'(?:\s+.*)?$')


def _ms(hours, minutes, seconds, millis):
    return ((int(hours or 0) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + int(millis.ljust(3, '0'))


def _unescape(line):
    return line.replace('&lt;', '<').replace('&gt;', '>').replace('&nbsp;', ' ').replace('&amp;', '&')


def parse(text):
    """SRT·WebVTT 글을 큐 목록으로 읽는다(번호·식별자·NOTE·STYLE 블록은 건너뜀)."""
    text = text.lstrip('﻿').replace('\r\n', '\n').replace('\r', '\n')
    vtt = text.lstrip().startswith('WEBVTT')
    cues = []
    for block in re.split(r'\n\s*\n', text):
        lines = [line for line in block.split('\n')]
        while lines and not lines[0].strip():
            lines.pop(0)
        if not lines:
            continue
        head = lines[0].strip()
        if vtt and (head.startswith('WEBVTT') or head.split(' ', 1)[0] in ('NOTE', 'STYLE', 'REGION')):
            continue
        timing = next((i for i, line in enumerate(lines[:3]) if _CUE_TIME.match(line)), None)
        if timing is None:
            continue
        match = _CUE_TIME.match(lines[timing])
        start, end = _ms(*match.groups()[:4]), _ms(*match.groups()[4:])
        body = [line.rstrip() for line in lines[timing + 1:] if line.strip()]
        if vtt:
            body = [_unescape(line) for line in body]
        cues.append(Cue(start, end, tuple(body)))
    return cues


@dataclass
class Validation:
    errors: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.errors


def validate(cues, rules=None):
    """형식 오류: 시간 역전·겹침·빈 큐, (규칙이 있으면) 줄 수·줄 길이·표시 시간 위반."""
    result = Validation()
    previous_end = -1
    for number, cue in enumerate(cues, 1):
        if cue.end <= cue.start:
            result.errors.append((number, 'end is not after start'))
        if cue.start < previous_end:
            result.errors.append((number, 'overlaps the previous cue'))
        if not any(line.strip() for line in cue.lines):
            result.errors.append((number, 'empty cue'))
        if rules is not None:
            if len(cue.lines) > rules.max_lines:
                result.errors.append((number, 'too many lines'))
            if any(display_length(line) > rules.max_chars for line in cue.lines):
                result.errors.append((number, 'line too long'))
            if cue.end - cue.start > rules.max_ms:
                result.errors.append((number, 'shown too long'))
            if previous_end >= 0 and 0 <= cue.start - previous_end < rules.gap_ms:
                result.errors.append((number, 'gap shorter than two frames'))
        previous_end = cue.end
    return result
