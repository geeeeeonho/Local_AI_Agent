"""음성 인식(Whisper) 결과 해석: 모델 목록, 단어 시각, 환각·반복 정리.

whisper.cpp의 상세 JSON(-ojf)은 구간(segment)마다 토큰과 그 시각·확률을 준다. 이 모듈은
토큰을 단어로 묶고(한중일은 토큰 자체가 단위), 무음·음악 구간에서 Whisper가 흔히 지어내는
문장(반복 루프, '시청해 주셔서 감사합니다' 같은 정형 문구)을 걸러 낸다. 자막 문법은
core.tools.subtitles가 맡는다. 외부 의존이 없다.
"""
from __future__ import annotations

import re
import unicodedata
import zlib
from dataclasses import dataclass, field

from core.tools.subtitles import NO_LINE_START, Word


@dataclass(frozen=True)
class SpeechModel:
    key: str
    label: str
    file: str               # Hugging Face ggerganov/whisper.cpp 의 파일 이름
    sha1: str               # whisper.cpp models/README.md(고정 버전)의 SHA
    size_mib: int
    vram_gib: float         # 대략적인 GPU 메모리(실행 중)
    dtw: str                # 정밀 단어 시각(DTW) 프리셋 이름
    note: str


# 정확도 높은 순. SHA는 whisper.cpp v1.9.5 models/README.md 의 'Available models' 표.
MODELS = (
    SpeechModel('large-v3', 'large-v3 · 최고 정확도', 'ggml-large-v3.bin',
                'ad82bf6a9043ceed055076d0fd39f5f186ff8062', 2950, 4.0, 'large.v3',
                '가장 정확합니다. 느리고 GPU 메모리를 가장 많이 씁니다.'),
    SpeechModel('large-v3-turbo', 'large-v3-turbo · 권장', 'ggml-large-v3-turbo.bin',
                '4af2b29d7ec73d781377bfd1758ca957a807e941', 1550, 2.0, 'large.v3.turbo',
                'large-v3에 가까운 정확도로 몇 배 빠릅니다.'),
    SpeechModel('large-v3-q5_0', 'large-v3 (압축) · 정확도 우선 저용량', 'ggml-large-v3-q5_0.bin',
                'e6e2ed78495d403bef4b7cff42ef4aaadcfea8de', 1080, 1.8, 'large.v3',
                'large-v3를 압축해 용량과 메모리를 줄였습니다. 정확도는 조금 낮습니다.'),
    SpeechModel('large-v3-turbo-q5_0', 'large-v3-turbo (압축) · 저사양', 'ggml-large-v3-turbo-q5_0.bin',
                'e050f7970618a659205450ad97eb95a18d69c9ee', 547, 1.0, 'large.v3.turbo',
                'GPU 메모리가 적거나 CPU만 있는 PC용입니다.'),
    SpeechModel('medium', 'medium', 'ggml-medium.bin',
                'fd9727b6e1217c2f614f9b698455c4ffd82463b4', 1530, 2.0, 'medium',
                '중간 크기 모델입니다. 대개 large-v3-turbo가 더 낫습니다.'),
    SpeechModel('small', 'small · 가벼움', 'ggml-small.bin',
                '55356645c2b361a969dfd0ef2c5a50d530afd8d5', 466, 0.8, 'small',
                '가볍고 빠르지만 오류가 눈에 띄게 늘어납니다.'),
)
BY_KEY = {model.key: model for model in MODELS}
RECOMMENDED = 'large-v3-turbo'
MODEL_URL = 'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/'


# 자막을 만들 수 있는 파일. 영상과 대부분의 오디오는 ffmpeg로 읽고,
# ffmpeg가 없어도 whisper.cpp가 직접 읽는 형식은 NATIVE_AUDIO다.
VIDEO = frozenset({'.mp4', '.mkv', '.mov', '.avi', '.webm', '.wmv', '.flv', '.m4v', '.ts', '.mts',
                   '.m2ts', '.mpg', '.mpeg', '.3gp', '.ogv'})
AUDIO = frozenset({'.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg', '.opus', '.wma', '.aif', '.aiff'})
MEDIA = VIDEO | AUDIO
NATIVE_AUDIO = frozenset({'.wav', '.mp3', '.flac'})


def model(key):
    found = BY_KEY.get(key)
    if found is None:
        raise ValueError('Unknown speech model: ' + str(key))
    return found


# 품질 설정: whisper-cli 인자. 'best'는 정밀 단어 시각(DTW)을 위해 flash attention을 끈다.
QUALITY = {
    'best': dict(beam=8, best_of=5, dtw=True),
    'balanced': dict(beam=5, best_of=5, dtw=False),
    'fast': dict(beam=1, best_of=2, dtw=False),
}

# 원문 언어로 고를 수 있는 Whisper 언어 코드(앱 언어 표의 코드 앞부분과 같다)
def whisper_code(code):
    """'zh-Hant' → 'zh', 'auto'·''은 자동 감지."""
    value = str(code or '').strip()
    if value in ('', 'auto'):
        return 'auto'
    return value.split('-')[0].lower()


# ── 상세 JSON → 구간·단어 ──
VAD_MAP_KEY = 'localai_vad_map'


def map_vad_time(t, segments, *, side=0):
    """VAD로 무음을 잘라 낸 시간 t(ms)를 원래 오디오 시간으로 되돌린다.
    segments: [(원래 시작, 원래 끝, 처리 시작, 처리 끝)]. 구간 안은 비례 보간(whisper.cpp와 같음).
    잘라 낸 틈에 떨어진 시간은 side로 정한다: +1 다음 구간 시작(단어 시작), -1 앞 구간 끝(단어 끝),
    0 가까운 쪽(whisper.cpp의 whisper_map_token_time_segment_aware)."""
    if not segments:
        return t
    if t <= segments[0][2]:
        return segments[0][0]
    if t >= segments[-1][3]:
        return segments[-1][1]
    for index, (orig_start, orig_end, vad_start, vad_end) in enumerate(segments):
        if vad_start <= t <= vad_end:
            if vad_end <= vad_start:
                return orig_start
            return orig_start + (t - vad_start) * (orig_end - orig_start) // (vad_end - vad_start)
        if index + 1 < len(segments) and vad_end < t < segments[index + 1][2]:
            if side:
                return segments[index + 1][0] if side > 0 else orig_end
            middle = (vad_end + segments[index + 1][2]) // 2
            return orig_end if t <= middle else segments[index + 1][0]
    return t


def _vad_segment_start(t, segments):
    """원래 시간 t가 속한(또는 바로 앞의) 말소리 구간의 원래 시작."""
    found = segments[0][0] if segments else 0
    for orig_start, _orig_end, _vad_start, _vad_end in segments:
        if orig_start <= t:
            found = orig_start
    return found


@dataclass(frozen=True)
class Segment:
    start: int              # ms
    end: int
    text: str
    words: tuple
    prob: float = 1.0


_SPECIAL = re.compile(r'^\s*(?:\[_[A-Z]+_?\d*\]|<\|[^|]*\|>)\s*$')
_CJK = re.compile(r'[぀-ヿ㐀-鿿豈-﫿฀-๿]')


def _is_attached(text):
    """앞 단어에 붙는 토큰: 문장부호·닫는 괄호 등."""
    stripped = text.strip()
    if not stripped or text[:1].isspace():
        return False
    return all(unicodedata.category(char)[0] in 'PS' for char in stripped) or stripped[0] in NO_LINE_START


def _token_time(token, key, vad=()):
    offsets = token.get('offsets') or {}
    value = offsets.get(key)
    side = 1 if key == 'from' else -1
    return map_vad_time(int(value), vad, side=side) if isinstance(value, (int, float)) else None


def _words(tokens, seg_start, seg_end, spaced, vad=()):
    """토큰을 단어로 묶는다. 띄어 쓰는 언어는 공백으로 시작하는 토큰이 새 단어,
    아니면 한중일 토큰 하나하나가 단위다. 문장부호 토큰은 앞 단어에 붙인다."""
    groups = []
    for token in tokens:
        text = str(token.get('text') or '')
        if not text or _SPECIAL.match(text):
            continue
        starts_new = (not groups or text[:1].isspace()
                      or (not spaced and not _is_attached(text))
                      or (_CJK.search(text[:1]) is not None and not _is_attached(text)))
        if _is_attached(text) and groups:
            starts_new = False
        if starts_new:
            groups.append([token])
        else:
            groups[-1].append(token)
    words = []
    for index, group in enumerate(groups):
        text = ''.join(str(token.get('text') or '') for token in group)
        dtw = group[0].get('t_dtw')
        start = (map_vad_time(int(dtw) * 10, vad, side=1) if isinstance(dtw, (int, float)) and dtw >= 0
                 else _token_time(group[0], 'from', vad))
        end = _token_time(group[-1], 'to', vad)
        start = seg_start if start is None else start
        end = seg_end if end is None else end
        if vad and end > start:
            # 한 단어가 잘라 낸 무음(구간 사이)을 가로지를 수 없다: 끝이 속한 말소리 구간에서 시작한다.
            start = max(start, min(_vad_segment_start(end - 1, vad), end - 1))
        probs = [float(token.get('p', 1.0)) for token in group if isinstance(token.get('p'), (int, float))]
        words.append([start, end, text, sum(probs) / len(probs) if probs else 1.0])
    # 시각을 구간 안으로, 앞뒤 순서대로 맞춘다.
    previous = seg_start
    for index, item in enumerate(words):
        start = min(max(item[0], previous, seg_start), seg_end)
        nxt = words[index + 1][0] if index + 1 < len(words) else seg_end
        end = min(max(item[1], start + 1), max(seg_end, start + 1))
        if index + 1 < len(words) and nxt > start:
            end = min(end, max(nxt, start + 1))
        item[0], item[1] = start, end
        previous = start
    return tuple(Word(start, end, text, prob) for start, end, text, prob in words)


def _reattach_heads(words, vad, *, gap=1000, head_ms=1500):
    """문장(whisper 구간)의 첫 한두 단어만 앞 말소리 구간 끝에 남고 나머지가 몇 초 뒤 다음 구간에서
    이어지는 경우: 경계 근처 토큰 시각이 부정확해서 생긴 것이므로, 그 단어들을 다음 발화 바로 앞으로 옮긴다."""
    for cut in range(1, min(3, len(words))):
        if words[cut].start - words[cut - 1].end >= gap and \
                _vad_segment_start(words[cut].start, vad) > words[cut - 1].end and \
                words[cut - 1].end - words[0].start <= head_ms:
            moved, at = [], words[cut].start
            for word in reversed(words[:cut]):
                length = min(400, max(80, word.end - word.start))
                moved.insert(0, Word(max(0, at - length), max(1, at), word.text, word.prob))
                at -= length
            return tuple(moved) + tuple(words[cut:])
    return words


def parse_result(data, *, spaced=True):
    """whisper-cli -ojf JSON → (감지 언어 코드, [Segment]). spaced=False면 한중일 방식으로 단어를 묶는다."""
    language = str(((data or {}).get('result') or {}).get('language') or '')
    vad = [tuple(item) for item in (data or {}).get(VAD_MAP_KEY) or ()]
    segments = []
    for item in (data or {}).get('transcription') or ():
        offsets = item.get('offsets') or {}
        start, end = int(offsets.get('from', 0)), int(offsets.get('to', 0))
        tokens = item.get('tokens') or ()
        if vad and tokens:
            # whisper-cli의 구간 시각은 VAD 대응표 전체를 한 번에 보간해 무음 틈에 떨어질 수 있다.
            # 단어 시각을 구간별로 되돌린 뒤, 구간 시작·끝은 그 단어들로 다시 정한다.
            words = _reattach_heads(_words(tokens, 0, 1 << 40, spaced, vad), vad)
            if words:
                start, end = words[0].start, words[-1].end
        else:
            words = _words(tokens, start, max(end, start + 1), spaced, vad) if tokens else ()
        text = str(item.get('text') or '').strip()
        if not words and text:
            words = (Word(start, max(end, start + 1), (' ' if spaced else '') + text),)
        probs = [word.prob for word in words]
        segments.append(Segment(start, max(end, start + 1), text, words,
                                sum(probs) / len(probs) if probs else 1.0))
    return language, segments


# ── 정리 ──
@dataclass
class Cleanup:
    segments: list = field(default_factory=list)
    removed: list = field(default_factory=list)      # (시작 ms, 글, 이유)
    flagged: list = field(default_factory=list)      # (시작 ms, 글, 이유)


def normalize(text):
    text = unicodedata.normalize('NFKC', text).lower()
    return re.sub(r'[\s\W_]+', '', text, flags=re.UNICODE)


# 무음·음악·끝부분에서 Whisper가 학습 자료(방송 자막)를 흉내 내 지어내는 대표 문구
KNOWN_FILLERS = tuple(normalize(text) for text in (
    'Thank you for watching', 'Thanks for watching', 'Please subscribe', 'like and subscribe',
    'Subtitles by the Amara.org community', 'Transcription by CastingWords',
    '시청해주셔서 감사합니다', '시청해 주셔서 감사합니다', '구독과 좋아요', 'MBC 뉴스', '자막 제공',
    'ご視聴ありがとうございました', 'チャンネル登録', '最後までご視聴',
    '字幕由Amara.org社区提供', '请不吝点赞 订阅 转发 打赏支持明镜与点点栏目',
    '請不吝點贊 訂閱 轉發 打賞支持明鏡與點點欄目', '感谢观看', '谢谢观看',
    'Subtítulos realizados por la comunidad de Amara.org', 'Gracias por ver',
    "Sous-titrage ST' 501", "Merci d'avoir regardé", 'Untertitel im Auftrag des ZDF',
    'Untertitel der Amara.org-Community', 'Obrigado por assistir', 'Редактор субтитров',
    'Продолжение следует',
))
# 소리 묘사: [음악] (박수) ♪ … 처럼 대사가 아닌 표기
SOUND_ONLY = re.compile(r'^[\s\-]*(?:[\[\(（【][^\]\)）】]{0,40}[\]\)）】]|[♪♫♬*~\s]+)[\s.\-]*$')
_MUSIC = re.compile(r'[♪♫♬]')
LOOP = re.compile(r'(.{1,40}?)(?:\1){4,}', re.UNICODE)


COMPRESSION_LIMIT = 2.4         # Whisper가 반복 환각을 거르는 기준과 같은 값
LOW_PROB = 0.45
# 사람이 실제로 낼 수 있는 발화 속도의 넉넉한 상한(정규화한 글자 / 초). 키: 띄어 쓰는 언어인지
MAX_RATE = {True: 25.0, False: 14.0}
LONG_LOOP = 8                   # 이만큼 되풀이되면 그것만으로 환각으로 본다


def compression_ratio(text):
    """글 바이트 / zlib 압축 바이트. 같은 말이 되풀이될수록 커진다. 짧은 글은 1.0으로 본다."""
    data = text.encode('utf-8')
    if len(data) < 40:
        return 1.0
    return len(data) / max(1, len(zlib.compress(data)))


def speech_rate(segment):
    seconds = max(0.2, (segment.end - segment.start) / 1000)
    return len(normalize(segment.text)) / seconds


def is_filler(text):
    norm = normalize(text)
    return bool(norm) and any(filler and filler in norm and len(norm) <= len(filler) + 12
                              for filler in KNOWN_FILLERS)


def corroborated(segment, *, spaced=True):
    """반복·정형 문구를 지우려면 필요한 추가 근거(낮은 확신도·높은 압축률·불가능한 발화 속도)."""
    return (segment.prob < LOW_PROB + 0.15 or compression_ratio(segment.text) > COMPRESSION_LIMIT
            or speech_rate(segment) > MAX_RATE[bool(spaced)])


def _loop(segment):
    """(반복 단위, 반복 횟수) 또는 None. 같은 글자·구절이 다섯 번 이상 이어질 때."""
    norm = normalize(segment.text)
    found = LOOP.search(norm)
    if not found or found.end() - found.start() < 6:
        return None
    return found, (found.end() - found.start()) // len(found.group(1))


def _cut_loop(segment, found):
    """반복 루프를 두 번까지로 줄인다."""
    keep_chars = found.start() + len(found.group(1)) * 2
    kept, count = [], 0
    for word in segment.words:
        size = len(normalize(word.text))
        if count + size > keep_chars and kept:
            break
        kept.append(word)
        count += size
    text = ''.join(word.text for word in kept).strip()
    end = kept[-1].end if kept else segment.start + 1
    return Segment(segment.start, end, text, tuple(kept), segment.prob)


def _drop_sound_words(words):
    """[음악]·♪ 처럼 괄호로 둘러싼 소리 표기 단어를 뺀다."""
    out, depth = [], 0
    for word in words:
        text = word.text
        opens, closes = text.count('[') + text.count('【'), text.count(']') + text.count('】')
        inside = depth > 0 or opens > 0
        depth = max(0, depth + opens - closes)
        if inside or _MUSIC.search(text) and not normalize(text):
            continue
        out.append(word)
    return tuple(out)


def clean(segments, *, keep_sounds=False, spaced=True):
    """환각·소리 표기를 정리한다. 지운 것과 확인이 필요한 것은 따로 돌려준다.

    반복·감탄사·말 더듬기는 실제 발화일 수 있으므로(원문 보존) 그것만으로 지우지 않는다.
    반복 루프는 아주 길거나(LONG_LOOP 이상) 다른 근거가 겹칠 때만 줄이고, 같은 문장이 세 번
    이상 이어지는 것과 정형 문구도 다른 근거가 있을 때만 지운다. 나머지는 '확인 필요'로 남긴다.
    """
    result = Cleanup()
    last_norm, repeats = None, 0
    for segment in segments:
        text = segment.text.strip()
        if not text or not normalize(text) and not _MUSIC.search(text):
            continue
        if not keep_sounds:
            if SOUND_ONLY.match(text) or (_MUSIC.search(text) and not normalize(_MUSIC.sub('', text))):
                result.removed.append((segment.start, text, 'sound description'))
                continue
            words = _drop_sound_words(segment.words)
            if not words:
                result.removed.append((segment.start, text, 'sound description'))
                continue
            if len(words) != len(segment.words):
                segment = Segment(words[0].start, words[-1].end,
                                  ''.join(word.text for word in words).strip(), words, segment.prob)
        backed = corroborated(segment, spaced=spaced)
        loop = _loop(segment)
        if loop:
            if loop[1] >= LONG_LOOP or backed:
                segment = _cut_loop(segment, loop[0])
                result.flagged.append((segment.start, segment.text, 'repetition loop shortened'))
            else:
                result.flagged.append((segment.start, segment.text, 'repetition kept'))
        norm = normalize(segment.text)
        if norm and norm == last_norm:
            repeats += 1
            if repeats >= 2:            # 같은 문장이 세 번째 이어짐
                if backed:
                    result.removed.append((segment.start, segment.text, 'repeated'))
                    continue
                result.flagged.append((segment.start, segment.text, 'repetition kept'))
        else:
            last_norm, repeats = norm, 0
        if is_filler(segment.text):
            if segment.prob < 0.6:
                result.removed.append((segment.start, segment.text, 'typical hallucination'))
                continue
            result.flagged.append((segment.start, segment.text, 'typical hallucination'))
        elif segment.prob < LOW_PROB - 0.05:
            result.flagged.append((segment.start, segment.text, 'low confidence'))
        if compression_ratio(segment.text) > COMPRESSION_LIMIT:
            result.flagged.append((segment.start, segment.text, 'high compression ratio'))
        if speech_rate(segment) > MAX_RATE[bool(spaced)]:
            result.flagged.append((segment.start, segment.text, 'implausible speech rate'))
        seconds = (segment.end - segment.start) / 1000
        if seconds > 12 and len(norm) < seconds * 0.6:
            result.flagged.append((segment.start, segment.text, 'long segment with little text'))
        result.segments.append(segment)
    return result


def words_of(segments):
    """정리된 구간들의 단어를 시간 순서로 이어 붙인다."""
    words = []
    for segment in segments:
        for word in segment.words:
            if words and word.start < words[-1].end:
                word = Word(max(word.start, words[-1].end), max(word.end, words[-1].end + 1),
                            word.text, word.prob)
            words.append(word)
    return words
