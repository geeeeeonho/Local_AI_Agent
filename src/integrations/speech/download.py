"""검증하며 받는 다운로드: 크기 제한 · 해시 검증 · 이어받기 · 취소.

받는 중에는 '<이름>.part'에 쓰고, 해시가 맞을 때만 최종 이름으로 바꾼다. 중단되면 .part가
남아 다음에 이어서 받는다(서버가 Range를 지원할 때). 해시가 다르면 .part를 지우고 실패한다.
고정한 배포처(GitHub 릴리스, Hugging Face)만 부르며 받은 파일을 실행하지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

USER_AGENT = 'Local_AI_Agent'
CHUNK = 1024 * 1024


class DownloadCancelled(InterruptedError):
    pass


def _request(url, *, accept='application/octet-stream', start=0):
    headers = {'User-Agent': USER_AGENT, 'Accept': accept}
    if start:
        headers['Range'] = 'bytes=%d-' % start
    return urllib.request.Request(url, headers=headers)


def get_json(url, *, limit=4 * 1024 * 1024, timeout=45):
    """작은 JSON 문서(릴리스 정보). limit을 넘으면 실패한다."""
    request = _request(url, accept='application/vnd.github+json, application/json')
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Metadata is larger than expected: ' + url)
    return json.loads(data.decode('utf-8'))


def get_bytes(url, *, limit, timeout=45):
    with urllib.request.urlopen(_request(url), timeout=timeout) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Download is larger than expected: ' + url)
    return data


def _hash_existing(path, algorithm):
    digest = hashlib.new(algorithm)
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(CHUNK), b''):
            digest.update(block)
    return digest


def fetch(url, destination, *, algorithm, expected, limit, progress=None, cancelled=None,
          timeout=60):
    """url을 destination으로 받는다. algorithm('sha256'·'sha1')의 hex가 expected와 같아야 한다.
    progress(받은 바이트, 전체 바이트 또는 None). 이미 같은 해시의 파일이 있으면 받지 않는다."""
    destination = Path(destination)
    expected = str(expected or '').lower()
    if not expected:
        raise ValueError('A pinned checksum is required for ' + url)
    if destination.is_file() and _hash_existing(destination, algorithm).hexdigest() == expected:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_name(destination.name + '.part')
    start = part.stat().st_size if part.is_file() else 0
    if start > limit:
        part.unlink(missing_ok=True)
        start = 0
    digest = _hash_existing(part, algorithm) if start else hashlib.new(algorithm)
    try:
        response = urllib.request.urlopen(_request(url, start=start), timeout=timeout)
    except urllib.error.HTTPError as exc:
        if exc.code != 416 or not start:        # 416: 이미 끝까지 받은 .part
            raise
        response = None
    try:
        if response is not None and start and response.status != 206:
            # 서버가 이어받기를 무시하고 처음부터 보낸다.
            start, digest = 0, hashlib.new(algorithm)
            mode = 'wb'
        else:
            mode = 'ab' if start else 'wb'
        length = response.headers.get('Content-Length') if response is not None else None
        total = start + int(length) if length and length.isdigit() else None
        if total is not None and total > limit:
            raise ValueError('Download is larger than expected: ' + url)
        received = start
        if progress:
            progress(received, total)
        with open(part, mode) as output:
            while response is not None:
                if cancelled and cancelled():
                    raise DownloadCancelled('Download cancelled; it resumes next time')
                block = response.read(CHUNK)
                if not block:
                    break
                received += len(block)
                if received > limit:
                    raise ValueError('Download is larger than expected: ' + url)
                output.write(block)
                digest.update(block)
                if progress:
                    progress(received, total)
    finally:
        if response is not None:
            response.close()
    if digest.hexdigest() != expected:
        part.unlink(missing_ok=True)
        raise ValueError('Checksum mismatch for %s (expected %s)' % (destination.name, expected))
    os.replace(part, destination)
    return destination
