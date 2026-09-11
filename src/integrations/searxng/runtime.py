"""Search-only container lifecycle. NetworkManager prepares proxies first.

The original installer settings stay untouched. A mode-specific derivative is
mounted as a writable derivative for upstream entrypoint initialization. Unrecognized custom proxy blocks require explicit repair;
we never guess how to rewrite arbitrary YAML or fall back to direct egress.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import socket
import tempfile
import time
from urllib.parse import urlsplit
from core.network.policy import NetworkMode

_BLOCK=re.compile(r'^# ===== proxy / Tor \(INSTALLER_NET_v1\) =====\r?\n.*?^# ={10,}\r?$',re.M|re.S)


def settings_for(source,mode,proxy):
    mode=NetworkMode(mode)
    if mode is NetworkMode.BLOCK:raise ValueError('Search is disabled in Block')
    if mode is not NetworkMode.DIRECT:
        if not isinstance(proxy,str) or any(ord(c)<32 for c in proxy):raise ValueError('Invalid search proxy')
        parts=urlsplit(proxy)
        if parts.scheme!='socks5h' or not parts.hostname or not parts.port or parts.username or parts.password:
            raise ValueError('Protected search requires a prepared SOCKS5h proxy')
    matches=list(_BLOCK.finditer(source))
    if len(matches)!=1:raise ValueError('Unrecognized SearXNG proxy configuration; use Setup / Repair')
    match=matches[0]
    remainder=source[:match.start()]+source[match.end():]
    if re.search(r'^outgoing\s*:',remainder,re.M):raise ValueError('Ambiguous SearXNG outgoing configuration')
    route='  proxies: {}' if mode is NetworkMode.DIRECT else '  proxies:\n    "all://": '+json.dumps(proxy)
    block='outgoing:\n'+route+'\n  request_timeout: 15.0\n  max_request_timeout: 30.0\n'
    return source[:match.start()]+block+source[match.end():]


def tcp_ready(port,timeout=30):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        try:
            with socket.create_connection(('127.0.0.1',int(port)),timeout=1):return True
        except OSError:time.sleep(.2)
    return False


class SearchRuntime:
    def __init__(self,source,cache,docker,*,image,container,network,host_port,container_port,ready=None):
        self.source,self.cache=Path(source),Path(cache)
        self.docker,self.image,self.container,self.network=docker,image,container,network
        self.host_port,self.port=int(host_port),int(container_port)
        self.ready=ready if ready is not None else lambda:tcp_ready(self.host_port)
        self.owned=False

    def start(self,mode,proxy):
        # Validate Block before reading config or touching Docker.
        if NetworkMode(mode) is NetworkMode.BLOCK:raise ValueError('Search is disabled in Block')
        with self.source.open('rb') as stream:raw=stream.read(4*1024*1024+1)
        if len(raw)>4*1024*1024:raise ValueError('SearXNG settings exceed size limit')
        payload=settings_for(raw.decode('utf-8'),mode,proxy).encode('utf-8')
        identity=json.dumps([self.image,self.container,self.network,self.host_port,self.port,str(self.cache.resolve())]).encode()
        fingerprint=hashlib.sha256(payload+identity).hexdigest()
        if not self.docker.image_exists(self.image):return False
        inspected=self.docker.run(['inspect','--format',
            '{{.Config.Image}}|{{index .Config.Labels "localai.search.fingerprint"}}|{{.State.Running}}',self.container],timeout=15)
        if inspected is None:raise RuntimeError('Cannot inspect search container')
        existing=inspected.returncode==0
        if existing:
            parts=(inspected.stdout or '').strip().split('|')
            if len(parts)!=3 or parts[0]!=self.image:raise RuntimeError('Search container name belongs to another configuration')
            if parts[1]==fingerprint and parts[2]=='true':return bool(self.ready())
        # Immutable, private, derived config; the installed original is retained.
        folder=self.cache/fingerprint;folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        target=folder/'settings.yml'
        fd,name=tempfile.mkstemp(prefix='.settings-',dir=folder)
        try:
            with os.fdopen(fd,'wb') as output:output.write(payload);output.flush();os.fsync(output.fileno())
            os.replace(name,target)
        finally:Path(name).unlink(missing_ok=True)
        if existing:
            removed=self.docker.run(['rm','-f',self.container],timeout=30)
            if removed is None or removed.returncode:raise RuntimeError('Cannot replace managed search container')
        found=self.docker.network_inspect(self.network,timeout=15)
        if found is None or found.returncode:
            created=self.docker.network_create(self.network,driver='bridge',timeout=20)
            if created is None or created.returncode:raise RuntimeError('Cannot prepare search network')
        result=self.docker.run(['run','-d','--rm','--name',self.container,
            '--label','localai.search.fingerprint='+fingerprint,'--label','localai.search.mode='+mode,
            '--network',self.network,'-p',f'127.0.0.1:{self.host_port}:{self.port}',
            '-v',str(folder)+':/etc/searxng:rw','--add-host=host.docker.internal:host-gateway',self.image],timeout=45)
        if result is None or result.returncode:return False
        self.owned=True
        return bool(self.ready())

    def stop(self):
        if not self.owned:return True
        result=self.docker.run(['stop',self.container],timeout=25)
        state=self.docker.run(['ps','--filter',f'name=^{self.container}$','--format','{{.Names}}'],timeout=15)
        stopped=state is not None and state.returncode==0 and self.container not in (state.stdout or '').split()
        if stopped:self.owned=False
        return stopped
