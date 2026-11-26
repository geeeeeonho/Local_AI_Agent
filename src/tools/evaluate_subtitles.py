"""생성 자막을 기준 자막과 비교한다(실측 평가용, 아무것도 바꾸지 않는다).

    python -m tools.evaluate_subtitles 기준.srt 생성.srt [--baseline 처리전.srt] [--language ko]

--baseline을 주면 처리 전(예: 품질 '빠름') 자막 대비 처리 후(예: '최고 정확도') 자막이
기준에 더 가까워진 큐와 멀어진 큐(과잉 교정)를 센다. --language를 주면 그 언어의 자막 규칙
위반(줄 길이·줄 수·표시 시간·간격)도 센다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.tools import subtitle_eval, subtitles


def _read(path):
    return subtitles.parse(Path(path).read_text(encoding='utf-8-sig'))


def main(argv=None):
    parser = argparse.ArgumentParser(description='Compare generated subtitles with a reference')
    parser.add_argument('reference')
    parser.add_argument('hypothesis')
    parser.add_argument('--baseline')
    parser.add_argument('--language')
    args = parser.parse_args(argv)
    reference, hypothesis = _read(args.reference), _read(args.hypothesis)
    for line in subtitle_eval.evaluate(reference, hypothesis).lines():
        print(line)
    if args.language:
        problems = subtitles.validate(hypothesis, subtitles.rules_for(args.language)).errors
        print('자막 규칙 위반 %d건' % len(problems) + ''.join('\n  %d번: %s' % item for item in problems[:20]))
    if args.baseline:
        change = subtitle_eval.compare(reference, _read(args.baseline), hypothesis)
        print('처리 전 대비: 개선 %d · 악화(과잉 교정) %d · 같음 %d · 과잉 교정률 %.1f%%' % (
            change.improved, change.worsened, change.unchanged, change.overcorrection * 100))
    return 0


if __name__ == '__main__':
    sys.exit(main())
