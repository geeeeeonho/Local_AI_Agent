import json
from types import SimpleNamespace as NS
import pytest

SOURCE='''use_default_settings: true
# ===== proxy / Tor (INSTALLER_NET_v1) =====
outgoing:
  proxies:
    "all://": socks5h://llm_tor:9050
  request_timeout: 15.0
# ==========================================
server:
  secret_key: "keep-secret"
engines:
  - name: google
    disabled: true
'''


def test_direct_config_contains_no_proxy_and_preserves_user_settings():
    from integrations.searxng.runtime import settings_for
    value=settings_for(SOURCE,'direct','')
    assert 'proxies: {}' in value
    assert 'socks5' not in value
    assert 'keep-secret' in value and 'disabled: true' in value


def test_protected_search_requires_exact_proxy_and_never_guesses():
    from integrations.searxng.runtime import settings_for
    assert 'socks5h://llm_warp:1080' in settings_for(SOURCE,'warp','socks5h://llm_warp:1080')
    for mode,proxy in [('block',''),('warp',''),('tor','http://x:80'),('warp','socks5h://x:1\nmalicious')]:
        with pytest.raises(ValueError):settings_for(SOURCE,mode,proxy)


def test_custom_unmanaged_or_duplicate_settings_are_not_rewritten():
    from integrations.searxng.runtime import settings_for
    for value in ('outgoing: {}', SOURCE+'\noutgoing: {}\n'):
        with pytest.raises(ValueError):settings_for(value,'direct','')


class Docker:
    def __init__(self):self.calls=[];self.active=False
    def run(self,args,**kwargs):
        self.calls.append(args)
        if args[0]=='inspect':return NS(returncode=1,stdout='')
        if args[0]=='run':self.active=True
        if args[0]=='stop':self.active=False
        if args[0]=='ps':return NS(returncode=0,stdout='search' if self.active else '')
        return NS(returncode=0,stdout='id')
    def image_exists(self,image):return True
    def network_inspect(self,name,**kwargs):return NS(returncode=0)
    def network_create(self,name,**kwargs):return NS(returncode=0)


def runtime(tmp_path):
    from integrations.searxng.runtime import SearchRuntime
    src=tmp_path/'settings.yml';src.write_text(SOURCE)
    docker=Docker()
    return SearchRuntime(src,tmp_path/'cache',docker,image='search-image',container='search',
        network='net',host_port=8888,container_port=8080,ready=lambda:True),docker,src


def test_search_starts_only_search_container_and_leaves_original_file_untouched(tmp_path):
    r,d,src=runtime(tmp_path)
    assert r.start('direct','')
    commands=' '.join(str(c) for c in d.calls)
    assert 'warp' not in commands and 'tor' not in commands
    assert src.read_text()==SOURCE
    assert '127.0.0.1:8888:8080' in commands
    assert ':rw' in commands
    assert str(src) not in commands
    assert r.stop() and not d.active


def test_foreign_container_is_not_removed(tmp_path):
    r,d,_=runtime(tmp_path)
    old=d.run
    d.run=lambda args,**kw:NS(returncode=0,stdout='foreign|abc|true') if args[0]=='inspect' else old(args,**kw)
    with pytest.raises(RuntimeError):r.start('direct','')
    assert not any(c[0] in ('rm','stop','run') for c in d.calls)


def test_search_failure_after_run_is_still_owned_for_cleanup(tmp_path):
    r,d,_=runtime(tmp_path);r.ready=lambda:False
    assert not r.start('direct','')
    assert d.active and r.stop() and not d.active
