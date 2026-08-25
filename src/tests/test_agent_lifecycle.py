from launcher.agent import agent_lifecycle


class Stoppable:
    def __init__(self):
        self.timeouts = []

    def stop(self, timeout=3.0):
        self.timeouts.append(timeout)


def test_lifecycle_registry_does_not_require_unified_agent():
    before = agent_lifecycle.count_active()
    item = Stoppable()
    agent_lifecycle.register(item)
    try:
        assert agent_lifecycle.count_active() == before + 1
        assert agent_lifecycle.cleanup_all(timeout=1.25) >= 1
        assert item.timeouts == [1.25]
    finally:
        agent_lifecycle.unregister(item)
