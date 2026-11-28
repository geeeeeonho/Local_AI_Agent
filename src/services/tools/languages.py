"""번역 언어 표 · 원문 언어 감지 · 언어쌍 지침 · 번역문 기계 검사.

언어를 추가할 때는 LANGUAGES에 한 줄을 더하면 UI 목록, 출력 파일 접미사, 감지, 검사에
함께 반영된다. 검사는 특정 언어쌍(예: 일본어→한국어)이 아니라 "문자 체계"와 "원문과의
유사도"로 판단하므로, 새 언어쌍에서도 같은 종류의 실수(원문 문자 잔류, 엉뚱한 언어 혼입,
번역 안 한 줄, 숫자 변경, 가짜 보호 토큰)를 잡는다.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher

# ── 문자 체계 ──
SCRIPTS = {
    'hangul': r'가-힣ᄀ-ᇿ㄰-㆏',
    'kana': r'぀-ゟ゠-ヿㇰ-ㇿ',
    'han': r'一-鿿㐀-䶿',
    'cyrillic': r'Ѐ-ӿ',
    'greek': r'Ͱ-Ͽ',
    'thai': r'฀-๿',
    'arabic': r'؀-ۿ',
    'hebrew': r'֐-׿',
    'devanagari': r'ऀ-ॿ',
    'latin': r'A-Za-zÀ-ɏḀ-ỿ',
}
_SCRIPT_RE = {name: re.compile('[' + chars + ']+') for name, chars in SCRIPTS.items()}


@dataclass(frozen=True)
class Language:
    label: str              # 화면 표시
    name: str               # 프롬프트에 쓰는 영어 이름
    code: str               # 출력 파일 접미사
    scripts: frozenset      # 이 언어가 정상적으로 쓰는 문자 체계
    target: bool = True     # 번역 대상으로 고를 수 있는지(원문 감지 전용 언어는 False)


def _lang(label, name, code, *scripts, target=True):
    return Language(label, name, code, frozenset(scripts), target)


LANGUAGES = (
    _lang('한국어', 'Korean', 'ko', 'hangul'),
    _lang('English', 'English', 'en', 'latin'),
    _lang('日本語', 'Japanese', 'ja', 'kana', 'han'),
    _lang('简体中文', 'Simplified Chinese', 'zh', 'han'),
    _lang('繁體中文', 'Traditional Chinese', 'zh-Hant', 'han'),
    _lang('Español', 'Spanish', 'es', 'latin'),
    _lang('Français', 'French', 'fr', 'latin'),
    _lang('Deutsch', 'German', 'de', 'latin'),
    _lang('Português', 'Portuguese', 'pt', 'latin'),
    _lang('Italiano', 'Italian', 'it', 'latin'),
    _lang('Русский', 'Russian', 'ru', 'cyrillic'),
    _lang('Tiếng Việt', 'Vietnamese', 'vi', 'latin'),
    _lang('ไทย', 'Thai', 'th', 'thai'),
    _lang('Bahasa Indonesia', 'Indonesian', 'id', 'latin'),
    # 원문으로만 감지(오른쪽→왼쪽 문자는 Tk 화면 표시가 불완전해 번역 대상으로는 내지 않는다)
    _lang('العربية', 'Arabic', 'ar', 'arabic', target=False),
    _lang('עברית', 'Hebrew', 'he', 'hebrew', target=False),
    _lang('हिन्दी', 'Hindi', 'hi', 'devanagari', target=False),
    _lang('Ελληνικά', 'Greek', 'el', 'greek', target=False),
    _lang('Українська', 'Ukrainian', 'uk', 'cyrillic', target=False),
)
BY_LABEL = {item.label: item for item in LANGUAGES}
BY_NAME = {item.name: item for item in LANGUAGES}
TARGET_LABELS = tuple(item.label for item in LANGUAGES if item.target)
SOURCE_LABELS = ('자동 감지',) + tuple(item.label for item in LANGUAGES)


def language(value):
    """화면 표시 이름이나 영어 이름으로 Language를 찾는다."""
    if isinstance(value, Language):
        return value
    found = BY_LABEL.get(value) or BY_NAME.get(value)
    if found is None:
        raise ValueError('Unsupported language: ' + str(value))
    return found


# ── 원문 언어 감지 ──
_STOPWORDS = {
    'English': 'the and of to is in that it you for was with on are this be have not your my we he she '
               'they but if or at by from will can do what please make sure before after when there',
    'Spanish': 'el la de que y o a en los se del las por un una para con no es al lo como pero mi su está '
               'muy más tu yo sí cuando porque',
    'French': 'le la les de des et est un une que qui pas pour dans ce il elle vous je mon ma mes son sa '
              'ses au aux du sur avec mais où nous très',
    'German': 'der die das und ist nicht ich sie es ein eine zu den mit von auf dass wir mein dein aber '
              'wo auch noch sehr bitte',
    'Portuguese': 'o a os as de que e do da em um uma não para com se por mais você meu minha mas onde '
                  'está muito',
    'Italian': 'il la di che e è un una non per con sono gli le del della ma anche mio mia dove molto',
    'Indonesian': 'yang dan di ini itu dengan untuk tidak ada saya dari akan ke kamu anda tapi tetapi '
                  'sudah belum mana',
    'Vietnamese': 'của là và có không tôi được này người cho với một những các đã trong nhưng ở đâu lúc',
}
_STOPWORDS = {name: frozenset(words.split()) for name, words in _STOPWORDS.items()}
# 소문자로만 된 낱말 전체(대문자로 시작하는 이름·문장 첫 단어의 일부를 잘라 내지 않도록 경계 확인)
_WORD = re.compile(r'(?<![\w])[a-z\u00df-\u00f6\u00f8-\u00ff\u0100-\u024f\u1e00-\u1eff]+(?![\w])')
# 번역문에 그대로 남아도 자연스러운 기술 용어(소문자로 쓰는 명령·형식 이름)
TECH_WORDS = frozenset('git commit push pull merge branch rebase docker python node npm pip json yaml html '
                       'css api url http https sql linux windows macos ollama wifi email online offline '
                       'app ok gpu cpu ram usb pdf mp4 mp3 png jpg zip log localhost'.split())
_VIETNAMESE = re.compile(r'[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]', re.I)
_UKRAINIAN = re.compile(r'[іїєґІЇЄҐ]')
# 간체/번체에서만 쓰는 자주 나오는 글자
TRAD_ONLY = frozenset('們這說來時會為國個學對過還沒樣開問關裡話認麼見動後讓實經從現點長電間題親聽')
SIMP_ONLY = frozenset('们这说来时会为国个学对过还没样开问关话认见动让实经从现点长电间题亲听')
# 간체 전용 글자 중 일본어 신자체와 모양이 같은 글자를 뺀 것(일본어 번역문에 있으면 중국어 잔류)
SIMP_NOT_JA = SIMP_ONLY - frozenset('来国学会点没')


def detect_language(text):
    """문자 체계와 기능어 빈도로 원문 언어 이름을 추정한다. 모르면 ''."""
    sample = text[:60000]
    counts = {name: sum(len(run) for run in pattern.findall(sample))
              for name, pattern in _SCRIPT_RE.items()}
    total = sum(counts.values())
    if not total:
        return ''
    cjk = counts['kana'] + counts['han']
    if counts['kana'] and counts['kana'] >= cjk * 0.05 and counts['kana'] >= counts['hangul']:
        return 'Japanese'
    top = max(counts, key=counts.get)
    if top == 'hangul':
        return 'Korean'
    if top == 'han':
        trad = sum(1 for c in sample if c in TRAD_ONLY)
        simp = sum(1 for c in sample if c in SIMP_ONLY)
        return 'Traditional Chinese' if trad > simp else 'Simplified Chinese'
    if top == 'cyrillic':
        return 'Ukrainian' if len(_UKRAINIAN.findall(sample)) >= 3 else 'Russian'
    simple = {'thai': 'Thai', 'arabic': 'Arabic', 'hebrew': 'Hebrew',
              'devanagari': 'Hindi', 'greek': 'Greek'}
    if top in simple:
        return simple[top]
    if len(_VIETNAMESE.findall(sample)) >= max(3, counts['latin'] * 0.02):
        return 'Vietnamese'
    words = Counter(_WORD.findall(sample.lower()))
    scores = {name: sum(words[w] for w in stop) for name, stop in _STOPWORDS.items()
              if name != 'Vietnamese'}
    best = max(scores, key=scores.get)
    ranked = sorted(scores.values(), reverse=True)
    if ranked[0] >= 2 and ranked[0] >= ranked[1] * 1.5:
        return best
    return ''


# ── 지침: 공통 규칙 + 원문 언어별 + 번역 언어별 + 검증된 언어쌍 보충 ──
_ROMANIZATION = ('Hepburn for Japanese, Hanyu Pinyin for Chinese, Revised Romanization for Korean, '
                 'standard transliteration for Cyrillic, Thai and others')
SOURCE_NOTES = {
    'Japanese': ('Japanese source: names by Japanese reading; words with several readings '
                 '(一日, 上手, 人気, 今日) by context; らしい/そうだ/って mark hearsay, ようだ/みたい a guess; '
                 'katakana loanwords by meaning in context; casual vs です/ます speech per speaker.'),
    'Simplified Chinese': ('Chinese source: translate chengyu and idioms by meaning; respect aspect '
                           '(了/过/着) and measure words; names by Mandarin pronunciation unless the target '
                           'has an established form.'),
    'Traditional Chinese': ('Chinese source: translate chengyu and idioms by meaning; respect aspect '
                            '(了/過/著); names by Mandarin pronunciation unless the target has an established form.'),
    'Korean': ('Korean source: map speech levels (반말/해요체/합니다체) to the target register; '
               'honorific -시- shows respect, not a different subject; omitted subjects come from context; '
               'Korean names are not translated.'),
    'English': ('English source: phrasal verbs and idioms by meaning; watch false friends; '
                'resolve "you" to singular/plural and formal/informal from context.'),
    'Russian': ('Russian source: keep verb aspect meaning; ты/вы marks register; '
                'names with patronymics keep their form.'),
    'Ukrainian': 'Ukrainian source: ти/ви marks register; keep names in their Ukrainian form.',
    'Spanish': 'Spanish source: tú/usted marks register; watch false friends (embarazada, actual).',
    'French': 'French source: tu/vous marks register; watch false friends (actuellement, librairie).',
    'German': 'German source: du/Sie marks register; split separable verbs correctly.',
    'Portuguese': 'Portuguese source: tu/você/o senhor marks register; watch false friends.',
    'Italian': 'Italian source: tu/Lei marks register; watch false friends.',
    'Vietnamese': 'Vietnamese source: pronouns (anh/chị/em/tôi) encode relationship and register.',
    'Thai': 'Thai source: particles ครับ/ค่ะ/นะ carry politeness and tone; omitted subjects come from context.',
    'Indonesian': 'Indonesian source: kamu/Anda marks register.',
}
TARGET_NOTES = {
    'Korean': ('Korean output: keep each speaker\'s 존댓말/반말 consistent with the source; numbers with '
               'counters as Arabic numerals (15분, 3일, 28명) and never confuse units; no hanja.'),
    'Japanese': ('Japanese output: match each speaker\'s です/ます or plain style; foreign names in katakana; '
                 'no Hangul.'),
    'Simplified Chinese': 'Simplified Chinese output: simplified characters only; Chinese punctuation.',
    'Traditional Chinese': 'Traditional Chinese output: traditional characters only; Chinese punctuation.',
    'English': 'English output: natural, idiomatic English.',
    'Spanish': 'Spanish output: keep tú/usted consistent per speaker; Spanish punctuation (¿ ¡).',
    'French': 'French output: keep tu/vous consistent per speaker.',
    'German': 'German output: keep du/Sie consistent per speaker; capitalize nouns.',
    'Portuguese': 'Portuguese output: keep tu/você consistent per speaker.',
    'Italian': 'Italian output: keep tu/Lei consistent per speaker.',
    'Russian': 'Russian output: keep ты/вы consistent per speaker; foreign names in Cyrillic.',
    'Vietnamese': 'Vietnamese output: choose pronouns by relationship and keep them consistent; full diacritics.',
    'Thai': 'Thai output: polite particles consistent per speaker; foreign names in Thai script.',
    'Indonesian': 'Indonesian output: keep kamu/Anda consistent per speaker.',
}
PAIR_NOTES = {
    ('Japanese', 'Korean'): (
        'Japanese→Korean rules: names by Japanese pronunciation in Hangul (高橋→다카하시, 渡辺→와타나베), '
        'never the Korean reading of the kanji; if the Korean Sino reading is a homonym of a different word, '
        'use the Korean word for the intended meaning (勉強→공부, not 면강); idioms by meaning '
        '(腹が立つ→화가 나다); hearsay らしい/そうだ/って→"~래/~라고 하더라", guess ようだ/みたい→"~것 같다"; '
        'loanwords by context (マンション→아파트); natural collocations (電話をかける→전화를 걸다).'),
    ('Simplified Chinese', 'Korean'): (
        'Chinese→Korean: historical/conventional names may use the Korean Sino reading, modern names use '
        'Mandarin pronunciation in Hangul; chengyu by meaning.'),
    ('Traditional Chinese', 'Korean'): (
        'Chinese→Korean: historical/conventional names may use the Korean Sino reading, modern names use '
        'Mandarin pronunciation in Hangul; chengyu by meaning.'),
    ('Korean', 'Japanese'): 'Korean→Japanese: Korean names in katakana by Korean pronunciation.',
}
CLASSICAL_JA = ('The text includes Classical Japanese (古文/文語). Interpret words with their classical '
                'meanings and grammar (e.g. あはれ is deep emotion, けり/けむ/らむ are auxiliaries); '
                'translate into natural modern target language.')


def build_guide(source_name, target_name, classical=False):
    parts = []
    if source_name:
        parts.append('Translate from %s into %s.' % (source_name, target_name))
    else:
        parts.append('Translate into %s (detect the source language yourself).' % target_name)
    parts.append(
        'General rules: write person/place names in the target script by their original pronunciation '
        '(romanization: %s); never translate the meaning of a name. Translate idioms and set phrases by '
        'meaning, not word by word. Keep numbers and their units exactly; change only formatting. Resolve '
        'words with several meanings from context. Keep each speaker\'s register consistent. Output only %s: '
        'leave no source-language words or script and do not mix in other languages.'
        % (_ROMANIZATION, target_name))
    for note in (SOURCE_NOTES.get(source_name), TARGET_NOTES.get(target_name),
                 PAIR_NOTES.get((source_name, target_name)), CLASSICAL_JA if classical else None):
        if note:
            parts.append(note)
    return ' '.join(parts)


# ── 번역문 기계 검사 ──
class ReviewError(ValueError):
    """다시 요청할 만한 의심 신호. 끝까지 남으면 원문 줄 전체를 남기는 대신 번역문을 쓰고
    '검토 필요'로 표시한다(원문 문자 잔류, 번역 안 한 줄, 숫자 변경 등)."""


_TOKEN = re.compile(r'__LOCALAI_KEEP_[0-9a-f]{8}_\d{4}__')
_ORDINAL = re.compile(r'(\d+)(?:st|nd|rd|th|er|e|º|ª)\b', re.I)


def _numbers(text):
    text = unicodedata.normalize('NFKC', _TOKEN.sub(' ', text))
    text = _ORDINAL.sub(r'\1', text)
    # 1,000 / 1.000 / 1 000 / 3,5 처럼 구분자만 다른 숫자는 같은 숫자로 본다.
    groups = re.findall(r'\d+(?:[.,   ]\d+)*', text)
    return [re.sub(r'\D', '', group) for group in groups]


# ── 숫자 값 비교 ──
# 모델은 같은 값을 번역 언어의 방식으로 쓴다(300,000 → 30만, 12,000 → 1.2万, 2 → 두, 1st → 처음).
# 글자만 비교하면 정상 번역을 거절해 그 줄이 원문으로 남았다(실사용: 자막 첫 줄이 번역되지 않음).
_SCALES = {'십': 10, '백': 100, '천': 1e3, '만': 1e4, '억': 1e8, '조': 1e12,
           '十': 10, '拾': 10, '百': 100, '千': 1e3, '万': 1e4, '萬': 1e4, '亿': 1e8, '億': 1e8, '兆': 1e12,
           'thousand': 1e3, 'million': 1e6, 'billion': 1e9, 'trillion': 1e12, 'k': 1e3, 'bn': 1e9}
_SCALE_WORD = '|'.join(sorted((re.escape(key) for key in _SCALES), key=len, reverse=True))
_QUANTITY = re.compile(r'(\d+(?:[.,  ]\d+)*)\s?((?:(?:%s)(?![a-z]))*)' % _SCALE_WORD, re.I)
# 숫자를 쓰지 않고 말로 옮겨도 되는 관용구(24/7 → 연중무휴)
_NUMBER_IDIOMS = re.compile(r'\b24\s*/\s*7\b|\b9\s*(?:-|to)\s*5\b|\b50\s*/\s*50\b', re.I)
# 10 이하의 수를 말로 쓴 형태(한국어 고유어·한자 숫자·영어). 작은 수만 이렇게 인정한다.
_SPELLED = {1: ('하나', '한 ', '한개', '첫', '처음', '一', 'one', 'first', 'once'),
            2: ('둘', '두', '二', '两', '兩', 'two', 'second', 'twice', 'both'),
            3: ('셋', '세', '三', 'three', 'third'), 4: ('넷', '네', '四', 'four', 'fourth'),
            5: ('다섯', '五', 'five', 'fifth'), 6: ('여섯', '六', 'six', 'sixth'),
            7: ('일곱', '七', 'seven', 'seventh'), 8: ('여덟', '八', 'eight', 'eighth'),
            9: ('아홉', '九', 'nine', 'ninth'), 10: ('열', '十', 'ten', 'tenth')}


def _plain_number(digits):
    """'1,234.5' → 1234.5, '3,5'(유럽식 소수) → 3.5, '1 000' → 1000."""
    text = re.sub(r'[  ]', '', digits)
    parts = re.split(r'[.,]', text)
    if len(parts) == 1:
        return float(text)
    if all(len(part) == 3 for part in parts[1:]):          # 천 단위 구분
        return float(''.join(parts))
    whole, fraction = ''.join(parts[:-1]), parts[-1]
    return float(whole + '.' + fraction)


def quantities(text):
    """글 속 수량 [(숫자 글자, 값)]. 단위(만·億·million …)를 곱하고, '3억 5천만'·'1万2000'처럼
    큰 단위 뒤에 바로 이어지는 작은 수는 합친 값도 함께 넣는다."""
    text = unicodedata.normalize('NFKC', _TOKEN.sub(' ', text))
    text = _ORDINAL.sub(r'\1', text)
    found, previous = [], None
    for match in _QUANTITY.finditer(text):
        try:
            value = _plain_number(match.group(1))
        except ValueError:
            continue
        scale = 1.0
        for unit in re.findall(_SCALE_WORD, match.group(2) or '', re.I):
            scale *= _SCALES.get(unit, _SCALES.get(unit.lower(), 1))
        value *= scale
        found.append((re.sub(r'\D', '', match.group(1)), value))
        if previous is not None and previous[2] > 1 and value < previous[2] and \
                match.start() - previous[0] <= 2:
            found.append(('', previous[1] + value))         # 큰 단위 + 이어지는 수
            previous = (match.end(), previous[1] + value, scale if scale > 1 else 1)
        else:
            previous = (match.end(), value, scale)
    return found


def _same_value(a, b):
    return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))


def _number_kept(digits, value, answer, kept_digits, kept_values):
    if digits and digits in kept_digits:                     # 예전 규칙: 숫자 글자가 그대로 있음
        return True
    if any(_same_value(value, other) for other in kept_values):
        return True
    if value == int(value) and 1 <= value <= 10:              # 작은 수는 말로 써도 된다
        lowered = answer.lower()
        return any(word in lowered for word in _SPELLED[int(value)])
    return False


# 24시간제 시각을 12시간제로 옮기는 것은 정상이다(18:30 → 오후 6시 30분). 오후·밤 같은 표시가 함께 있을 때만
# 시(18)를 12를 뺀 값(6)으로 인정한다. 표시 없이 '6:30'만 쓰면 오전으로 읽히므로 값이 바뀐 것이다.
_CLOCK = re.compile(r'(?<![\d:.,])(\d{1,2}):\d{2}(?::\d{2})?(?![\d:]|[.,]\d)')
_AFTERNOON = re.compile(r'오후|저녁|밤|午後|夜|下午|晚上|傍晚|\bp\.?\s?m\b|\bin the (?:evening|afternoon)\b|'
                        r'\bat night\b|de la (?:tarde|noche)|du soir|de l\'après-midi|abends|nachmittags', re.I)
_MIDNIGHT = re.compile(r'오전|자정|새벽|午前|深夜|凌晨|半夜|\ba\.?\s?m\b|midnight|medianoche|minuit|mitternacht', re.I)
# 앞자리 0이 있는 수(PIN 0451, 코드 007, 내선 0199)는 값이 같아도 글자가 달라지면 다른 번호다.
# 시각·날짜·소수의 일부(6:05, 03/05, 0.5, 2026-03-05)는 '6시 5분'·'3월 5일'처럼 0을 빼고 써도 된다.
_LEADING_ZERO = re.compile(r'(?<![\d:/.,\-])0\d+(?![\d:/\-]|[.,]\d)')


def _clock_alternates(source_text, answer):
    """원문 시각의 '시' 숫자 → 번역문에서 대신 써도 되는 12시간제 값."""
    alternates = {}
    for match in _CLOCK.finditer(source_text):
        hour = int(match.group(1))
        if 13 <= hour <= 23 and _AFTERNOON.search(answer):
            alternates[match.group(1)] = hour - 12
        elif hour == 0 and _MIDNIGHT.search(answer):
            alternates[match.group(1)] = 12
    return alternates


def _letters(text):
    return re.sub(r'[\W\d_]+', '', unicodedata.normalize('NFKC', text).lower())


def check_output(source_text, answer, source_name, target_name, allowed=''):
    """번역문 한 구간을 검사한다. 의심되면 ReviewError."""
    target = BY_NAME.get(target_name)
    if target is None:
        return
    source = BY_NAME.get(source_name)
    plain = _TOKEN.sub(' ', answer)
    allowed_lower = allowed.lower()

    # 1) 번역 언어가 쓰지 않는 문자 체계가 남았는가 (가나·한자·키릴·태국 문자 등)
    for script, pattern in _SCRIPT_RE.items():
        if script == 'latin' or script in target.scripts:
            continue
        for run in pattern.findall(plain):
            # 원문에 그대로 있는 그리스 문자는 수식·단위 기호(α, Δg, σ)라 잔류가 아니다.
            if script == 'greek' and run in source_text:
                continue
            if run.lower() not in allowed_lower:
                raise ReviewError('%s text left in %s output: %s' % (script, target_name, run[:20]))

    # 2) 간체/번체 혼동
    if target_name in ('Simplified Chinese', 'Traditional Chinese'):
        trad = sum(1 for c in plain if c in TRAD_ONLY)
        simp = sum(1 for c in plain if c in SIMP_ONLY)
        # 목록의 글자는 한쪽 체계에만 있으므로 하나만 있어도 섞인 것이다.
        if target_name == 'Simplified Chinese' and trad:
            raise ReviewError('Traditional characters in Simplified Chinese output')
        if target_name == 'Traditional Chinese' and simp:
            raise ReviewError('Simplified characters in Traditional Chinese output')

    source_plain = _TOKEN.sub(' ', source_text)
    source_lower = source_plain.lower()
    source_words = set(_WORD.findall(source_lower))
    # 명령·파일명·도메인처럼 코드로 보이는 원문 토큰(config.yaml, example.com, max_tokens)과
    # 기술 용어 바로 뒤에 이어지는 소문자 단어(docker compose up)는 번역하지 않아도 정상이다.
    code_words = set()
    follow = 0                      # 기술 용어 뒤 최대 두 낱말까지를 명령의 일부로 본다
    for token in source_plain.split():
        parts = _WORD.findall(token.lower())
        tech = bool(parts) and parts[0] in TECH_WORDS
        is_code = bool(re.search(r'[._/:=\\]\w|\d', token)) or tech or (follow > 0 and token.islower())
        if is_code:
            code_words.update(re.findall(r'[a-z]+', token.lower()))
        follow = 2 if tech else (follow - 1 if follow > 0 and token.islower() else 0)
    latin_source = bool(source and 'latin' in source.scripts) or (
        source is None and len(_WORD.findall(source_lower)) >= 3)

    # 3) 라틴 문자를 안 쓰는 언어(한·중·일·러·태)로 번역했는데 라틴 단어가 남은 경우
    if 'latin' not in target.scripts:
        for word in re.findall(r'[A-Za-z\u00c0-\u024f\u1e00-\u1eff]{3,}', plain):
            low = word.lower()
            if low in allowed_lower or low in TECH_WORDS or low in code_words:
                continue
            if low not in source_lower:
                raise ReviewError('Word from another language in %s output: %s' % (target_name, word))
            # 원문에 있던 단어: 이름·상표(대문자 시작)는 그대로 둘 수 있지만 소문자 일반어는 미번역
            if latin_source and word.islower() and len(word) >= 4:
                raise ReviewError('Source word left untranslated: ' + word)

    # 4) 라틴 문자끼리(영→스페인어 등): 원문 언어 기능어·원문 단어가 그대로 남았는지 점수로 판단
    if latin_source and 'latin' in target.scripts:
        own = _STOPWORDS.get(target_name, frozenset())
        foreign = _STOPWORDS.get(source_name, frozenset()) - own
        score, seen = 0.0, []
        for word in _WORD.findall(plain):          # 소문자로 쓰인 단어만(이름·상표 제외)
            if word in foreign:
                score += 2; seen.append(word)
            elif len(word) >= 3 and word in source_words and word not in own and \
                    word not in TECH_WORDS and word not in code_words and word not in allowed_lower:
                score += 1.5 if len(word) >= 6 else 1; seen.append(word)
        # 점수 3 이상, 또는 3글자 이상 기능어(the, der, mon…)가 하나라도 있으면 부분 미번역
        if score >= 3 or any(word in foreign and len(word) >= 3 for word in seen):
            raise ReviewError('%s words left in %s output: %s' % (source_name or 'Source', target_name,
                                                                    ' '.join(seen[:4])))

    # 5) 번역하지 않고 원문을 거의 그대로 돌려줬는가(같은 문자 체계끼리도 잡는다)
    chinese = {'Simplified Chinese', 'Traditional Chinese'}
    if source_name != target_name and not {source_name, target_name} <= chinese:  # 간↔번 변환은 같아도 정상
        a, b = _letters(source_plain), _letters(plain)
        enough = (len(_WORD.findall(source_lower)) >= 3 and len(a) >= 15) if latin_source else len(a) >= 8
        if enough:
            matcher = SequenceMatcher(None, a, b, autojunk=False)
            if matcher.quick_ratio() >= 0.9 and matcher.ratio() >= 0.9:
                raise ReviewError('Output looks untranslated (too similar to the source)')

    # 5b) 중국어 원문 → 일본어: 간체 전용 글자가 남거나, 긴 문장에 가나가 전혀 없으면 미번역 의심
    if target_name == 'Japanese' and source_name in ('Simplified Chinese', 'Traditional Chinese'):
        if any(c in SIMP_NOT_JA for c in plain):
            raise ReviewError('Chinese-only characters left in Japanese output')
        if len(_SCRIPT_RE['han'].findall(plain) and ''.join(_SCRIPT_RE['han'].findall(plain))) >= 10 \
                and not _SCRIPT_RE['kana'].search(plain):
            raise ReviewError('Japanese output without any kana (looks like Chinese)')

    # 6) 원문의 수는 번역문에도 같은 값으로 있어야 한다. 쓰는 방식은 바뀔 수 있다
    #    (1,000 ↔ 1000 ↔ 1천, 300,000 ↔ 30만 ↔ 30万, 2 ↔ 두, 1st ↔ 처음). 단위 환산·값 변경·누락은 거절.
    kept = quantities(answer)
    answer_groups = _numbers(answer)
    kept_digits = ''.join(answer_groups)
    kept_values = [value for _digits, value in kept]
    for code in _LEADING_ZERO.findall(unicodedata.normalize('NFKC', source_plain)):
        if code not in answer_groups:
            raise ReviewError('Number changed or dropped (leading zero): ' + code)
    alternates = _clock_alternates(unicodedata.normalize('NFKC', source_plain), answer)
    for digits, value in quantities(_NUMBER_IDIOMS.sub(' ', source_text)):
        if digits in alternates and any(_same_value(alternates[digits], other) for other in kept_values):
            continue
        if digits and not _number_kept(digits, value, answer, kept_digits, kept_values):
            raise ReviewError('Number changed or dropped: ' + digits)
