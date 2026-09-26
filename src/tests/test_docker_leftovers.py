"""What Docker is left holding after a session, and who is supposed to clear it.

Containers that opened and closed, and images orphaned by re-pulling a moved
tag, accumulate on their own. The program already knew how to sweep them, and
had a toggle for doing it on exit - but the toggle was registered only by the
terminal launcher's entrypoint, so for anyone using the desktop app it did
nothing at all. These pin both halves: what counts as ours, and when it runs.
"""
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def docker(monkeypatch):
    from launcher.core import docker_maint
    calls = []
    state = {'containers': {}, 'networks': {}}

    def run(cmd, timeout=60):
        args = [part for part in cmd if part != 'docker']
        calls.append(args)
        result = NS(returncode=0, stdout='', stderr='')
        if args[:2] == ['ps', '-a']:
            wanted = args[args.index('--filter') + 1].split('=')[1]
            result.stdout = '\n'.join(
                '%s\t%s' % (name, image)
                for name, (status, image) in state['containers'].items() if status == wanted)
        elif args[:2] == ['network', 'inspect']:
            result.stdout = str(state['networks'].get(args[-1], 1))
        elif args[:2] == ['network', 'rm']:
            state['networks'].pop(args[-1], None)
        elif args[0] == 'rm':
            state['containers'].pop(args[-1], None)
        return result

    monkeypatch.setattr(docker_maint, '_run', run)
    monkeypatch.setattr(docker_maint, '_SWEEP_REGISTERED', False)
    return NS(module=docker_maint, calls=calls, state=state)


# ── what counts as ours ──────────────────────────────────────────────────

def test_a_container_that_never_started_is_leftover_too(docker):
    """Only `exited` was collected. A `docker run` that failed leaves `created`,
    and a daemon that died leaves `dead`; both sat there forever."""
    docker.state['containers'] = {
        'llm_agent_chat_ab12': ('exited', 'sandbox'),
        'llm_searxng': ('created', 'searxng/searxng'),
        'llm_anythingllm': ('dead', 'mintplexlabs/anythingllm'),
    }
    found = docker.module.list_our_leftovers()
    assert set(found) == set(docker.state['containers'])


def test_somebody_elses_container_is_not_ours_to_remove(docker):
    docker.state['containers'] = {'their_postgres': ('exited', 'postgres:16'),
                                  'llm_searxng': ('exited', 'searxng/searxng')}
    assert docker.module.list_our_leftovers() == ['llm_searxng']
    count, _ = docker.module.prune_exited_ours()
    assert count == 1
    assert 'their_postgres' in docker.state['containers']


def test_public_image_name_does_not_make_a_foreign_container_ours(docker):
    docker.state['containers'] = {
        'their_search': ('exited', 'searxng/searxng:latest'),
        'their_chat': ('exited', 'mintplexlabs/anythingllm:latest'),
    }
    assert docker.module.list_our_leftovers() == []


def test_only_an_empty_network_of_ours_is_removed(docker):
    from launcher import config, network_policy
    block = network_policy.block_network_name()
    docker.state['networks'] = {config.LLM_NETWORK: 0, block: 2}
    assert docker.module.list_our_networks() == [config.LLM_NETWORK]
    count, _ = docker.module.prune_our_networks()
    assert count == 1
    assert block in docker.state['networks'], 'a network still in use stays'


def test_the_block_network_is_ours_too(docker):
    """config has no BLOCK_NETWORK attribute; reading it simply skipped the
    network that Block mode creates."""
    from launcher import network_policy
    docker.state['networks'] = {network_policy.block_network_name(): 0}
    assert docker.module.list_our_networks() == [network_policy.block_network_name()]


# ── who runs it, and when ────────────────────────────────────────────────

def test_cleaning_up_after_ourselves_is_not_an_opt_in(docker, monkeypatch, tmp_path):
    """Our own leftovers are removed whether or not the flag is set; only the
    machine-wide image prune is a preference."""
    docker.state['containers'] = {'llm_searxng': ('exited', 'searxng/searxng')}
    pruned = []
    monkeypatch.setattr(docker.module, 'prune_dangling_images',
                        lambda: pruned.append('images') or ('', []))
    result = docker.module.sweep_our_leftovers()
    assert result['containers'] == 1
    assert pruned == [], 'images belong to the machine, not to this program'


def test_the_flag_is_what_adds_the_machine_wide_image_prune(docker, monkeypatch):
    pruned = []
    monkeypatch.setattr(docker.module, 'prune_dangling_images',
                        lambda: pruned.append('images') or ('0B', []))
    docker.module.safe_auto_prune()
    assert pruned == ['images']


def test_every_shell_registers_the_same_exit_sweep(monkeypatch, tmp_path):
    from services.system import bootstrap
    from launcher.core import docker_maint
    import project_paths
    monkeypatch.setattr(project_paths, 'ENV_DIR', tmp_path)
    monkeypatch.setattr(docker_maint, '_SWEEP_REGISTERED', False)
    registered = []
    monkeypatch.setattr('launcher.core.lifelog.register_cleanup',
                        lambda fn, **kw: registered.append(kw))
    assert bootstrap.install_docker_sweep(tmp_path) is True
    assert registered == [{'stage': 'sweep'}]


def test_the_sweep_runs_after_the_stop_and_before_the_daemon_goes_down(monkeypatch):
    """Nothing to sweep before our containers stop, and nothing can be swept
    once the daemon is gone."""
    from launcher.core import lifelog
    monkeypatch.setattr(lifelog, '_cleanup_callbacks', [])
    monkeypatch.setattr(lifelog, '_sweep_cleanup_callbacks', [])
    monkeypatch.setattr(lifelog, '_final_cleanup_callbacks', [])
    monkeypatch.setattr(lifelog, '_cleanups_ran', False)
    order = []
    lifelog.register_cleanup(lambda: order.append('daemon'), stage='daemon')
    lifelog.register_cleanup(lambda: order.append('sweep'), stage='sweep')
    lifelog.register_cleanup(lambda: order.append('stop'))
    lifelog.shutdown_then_exit()
    assert order == ['stop', 'sweep', 'daemon']


def test_an_unknown_stage_is_refused_rather_than_silently_last():
    from launcher.core import lifelog
    with pytest.raises(ValueError):
        lifelog.register_cleanup(lambda: None, stage='whenever')
