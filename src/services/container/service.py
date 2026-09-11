"""Shared container entrypoint over the existing tested Docker CLI primitives."""


class ContainerService:
    def __init__(self, client):
        self.client = client

    def health(self):
        return bool(self.client.daemon_alive())

    def ensure_ready(self, logger=None, cancel=None):
        return bool(self.client.ensure_daemon(logger=logger, timeout=90, cancel_check=cancel))

    def image_exists(self, image):
        return bool(self.client.image_exists(image))

    def inspect(self, name):
        return self.client.run(['inspect', name], timeout=10)
