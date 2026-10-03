"""Every test runs against a throwaway runtime root.

Off Windows the runtime root falls back to the checkout, and on Windows it is
the real ``C:\\LocalAI``. Tests that reached a path helper without overriding it
therefore wrote agent traces, settings and cache folders into the developer's
own account records - on Windows, into the live install of whoever ran the
suite. This runs before any test module imports ``project_paths``, so its
module-level constants resolve here too.

A test that wants a particular root still sets ``LLM_PROJECT_ROOT`` or
``LOCAL_AI_ROOT`` itself; that overrides this default for its duration.
"""
import atexit
import os
import shutil
import tempfile

_ROOT = tempfile.mkdtemp(prefix='localai-tests-')
atexit.register(shutil.rmtree, _ROOT, True)

# Variables that point the product at a real install. A developer shell that
# has them set must not turn the suite loose on that install.
for _name in ('LOCAL_AI_ROOT', 'LLM_MODEL_DIR', 'LLM_OLLAMA_DIR'):
    os.environ.pop(_name, None)
os.environ['LLM_PROJECT_ROOT'] = _ROOT
