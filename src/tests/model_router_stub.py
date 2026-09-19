"""Stand in for a running Ollama at the one seam the program talks through.

Before the model-check pipeline was unified, a test that wanted to say "the
router is serving these models" had to patch urlopen inside whichever module
was doing the asking, and a test that patched the wrong one silently exercised
nothing. There is one transport now, so there is one thing to stub.
"""
from types import SimpleNamespace


def serve(monkeypatch, tags, *, key='name'):
    """Make the router answer with ``tags``. Returns the recorded call list."""
    calls = []

    def list_models(self):
        calls.append(self.base_url)
        return [{key: tag} for tag in tags]

    monkeypatch.setattr('integrations.ollama.client.OllamaClient.list_models',
                        list_models)
    return calls


def refuse(monkeypatch, error=None):
    """Make the router unreachable, the way a stopped server is."""
    def list_models(self):
        raise error or OSError('connection refused')
    monkeypatch.setattr('integrations.ollama.client.OllamaClient.list_models',
                        list_models)


def store(monkeypatch, tags):
    """Make the on-disk store hold exactly ``tags``, without touching a disk."""
    monkeypatch.setattr('launcher.models.model_index.read_manifests',
                        lambda path: {tag: {} for tag in tags})


def forbid_blob_walk(monkeypatch):
    """Record any full index build; the health poll must not do one."""
    walked = []
    monkeypatch.setattr('launcher.models.model_index.build_index',
                        lambda path, **k: walked.append(path) or {'models': []})
    return walked
