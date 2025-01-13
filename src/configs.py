import importlib
import os

BASE_PATH = os.path.dirname(os.path.realpath(__file__))


class LockFile:
    def __init__(self, name):
        self.path = os.path.join(BASE_PATH, f"__lock_{name}__")
        with open(self.path, 'w') as f:
            f.write("0")

    def lock(self):
        with open(self.path, 'w') as f:
            f.write("1")

    def unlock(self):
        with open(self.path, 'w') as f:
            f.write("0")

    def is_locked(self):
        with open(self.path, 'r') as f:
            res = int(f.read()) == 1
        return res


port_provider = getattr(importlib.import_module('port_providers'), os.getenv("PORT_PROVIDER", "Nginx"))()
lock_file = LockFile("service")