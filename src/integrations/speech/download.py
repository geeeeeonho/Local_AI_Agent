"""검증 다운로드: 크기 제한, 해시, 안전한 이어받기, 제한된 재시도 및 취소."""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

USER_AGENT = 'Local_AI_Agent'
CHUNK = 1024 * 1024
ATTEMPTS = 3


class DownloadCancelled(InterruptedError):
    pass


class IncompleteDownload(ConnectionError):
    pass


@contextmanager
def exclusive_lock(path):
    """프로세스 간 동일 설치/모델 변경을 차단. 파일은 유지하고 OS 잠금만 해제한다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a+b') as handle:
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise OSError('다른 프로세스에서 설치 또는 복구 중입니다: ' + str(path)) from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _cancel(cancelled):
    if cancelled and cancelled():
        raise DownloadCancelled('Download cancelled; it resumes next time')


def _request(url, *, accept='application/octet-stream', start=0):
    headers = {'User-Agent': USER_AGENT, 'Accept': accept, 'Accept-Encoding': 'identity'}
    if start:
        headers['Range'] = 'bytes=%d-' % start
    return urllib.request.Request(url, headers=headers)


def _retryable(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in (408, 429, 500, 502, 503, 504)
    return isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException))


def _retry(action, cancelled=None):
    for attempt in range(ATTEMPTS):
        try:
            return action()
        except DownloadCancelled:
            raise
        except Exception as exc:
            if attempt == ATTEMPTS - 1 or not _retryable(exc):
                raise
            if isinstance(exc, urllib.error.HTTPError):
                exc.close()
            # Short bounded delay, with cancellation during backoff.
            for _ in range(5 * (attempt + 1)):
                _cancel(cancelled)
                time.sleep(0.2)


def _read_small(url, *, accept, limit, timeout, cancelled=None):
    def read():
        _cancel(cancelled)
        with urllib.request.urlopen(_request(url, accept=accept), timeout=timeout) as response:
            data = response.read(limit + 1)
        _cancel(cancelled)
        if len(data) > limit:
            raise ValueError('Download is larger than expected: ' + url)
        return data
    return _retry(read, cancelled)


def get_json(url, *, limit=4 * 1024 * 1024, timeout=45, cancelled=None):
    return json.loads(_read_small(url, accept='application/vnd.github+json, application/json',
                                  limit=limit, timeout=timeout, cancelled=cancelled).decode('utf-8'))


def get_bytes(url, *, limit, timeout=45, cancelled=None):
    return _read_small(url, accept='application/octet-stream', limit=limit, timeout=timeout,
                       cancelled=cancelled)


def _hash_existing(path, algorithm, cancelled=None):
    digest = hashlib.new(algorithm)
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(CHUNK), b''):
            _cancel(cancelled)
            digest.update(block)
    return digest


def _download_once(url, destination, *, algorithm, expected, limit, progress, cancelled, timeout):
    part = destination.with_name(destination.name + '.part')
    start = part.stat().st_size if part.is_file() else 0
    if start > limit:
        part.unlink()
        start = 0
    digest = _hash_existing(part, algorithm, cancelled) if start else hashlib.new(algorithm)
    # A complete verified .part may remain if the previous final rename failed.
    if start and digest.hexdigest() == expected:
        _cancel(cancelled)
        os.replace(part, destination)
        return destination
    try:
        response = urllib.request.urlopen(_request(url, start=start), timeout=timeout)
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and start:
            exc.close()
            part.unlink(missing_ok=True)
            raise IncompleteDownload('Invalid resume offset; restarting ' + destination.name) from exc
        raise
    with response:
        status = getattr(response, 'status', None)
        length = response.headers.get('Content-Length')
        length = int(length) if length and length.isdigit() else None
        if status == 206:
            value = response.headers.get('Content-Range', '')
            match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', value)
            if not match:
                part.unlink(missing_ok=True)
                raise IncompleteDownload('Missing or invalid Content-Range: ' + value)
            first, last, total = map(int, match.groups())
            if first != start or not first <= last < total or (length is not None and length != last - first + 1):
                part.unlink(missing_ok=True)
                raise IncompleteDownload('Unexpected Content-Range: ' + value)
            length = last - first + 1
        else:
            # Server ignored Range: safely overwrite instead of appending.
            start, digest = 0, hashlib.new(algorithm)
            total = length
        if total is not None and total > limit:
            part.unlink(missing_ok=True)
            raise ValueError('Download is larger than expected: ' + url)
        received = start
        if progress:
            progress(received, total)
        with open(part, 'ab' if start else 'wb') as output:
            while True:
                _cancel(cancelled)
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
        if (length is not None and received - start != length) or (total is not None and received != total):
            raise IncompleteDownload('Incomplete download: ' + destination.name)
    _cancel(cancelled)
    if digest.hexdigest() != expected:
        part.unlink(missing_ok=True)
        raise ValueError('Checksum mismatch for %s (expected %s)' % (destination.name, expected))
    os.replace(part, destination)
    return destination


def fetch(url, destination, *, algorithm, expected, limit, progress=None, cancelled=None,
          timeout=60):
    """해시가 맞을 때만 최종 이름으로 이동. 정상 기존 파일은 다시 받지 않는다."""
    destination = Path(destination)
    expected = str(expected or '').lower()
    if not expected:
        raise ValueError('A pinned checksum is required for ' + url)
    if not re.fullmatch(r'[0-9a-f]{%d}' % (hashlib.new(algorithm).digest_size * 2), expected):
        raise ValueError('Invalid pinned checksum for ' + url)
    # Hash the final model only on explicit installation/repair, not on GUI refresh.
    if destination.is_file() and destination.stat().st_size <= limit:
        if _hash_existing(destination, algorithm, cancelled).hexdigest() == expected:
            return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    return _retry(lambda: _download_once(url, destination, algorithm=algorithm, expected=expected,
                  limit=limit, progress=progress, cancelled=cancelled, timeout=timeout), cancelled)
