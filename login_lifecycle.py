"""Cooperative shutdown limited to login windows owned by one GUI instance."""
import os
from pathlib import Path
import threading
import uuid

class OwnedLogins:
    def __init__(self, home, launcher):
        self.directory = Path(home) / "login_control"
        self.launcher = launcher
        self.children = []

    def start(self, provider):
        self.directory.mkdir(parents=True, exist_ok=True)
        marker = self.directory / (uuid.uuid4().hex + ".stop")
        process = self.launcher(provider, cancel_path=marker)
        self.children.append((process, marker))
        return process

    def request_stop(self):
        for process, marker in self.children:
            if process.poll() is None:
                marker.touch()

    def running(self):
        remaining = []
        for process, marker in self.children:
            if process.poll() is None:
                remaining.append((process, marker))
            else:
                marker.unlink(missing_ok=True)
        self.children = remaining
        return bool(remaining)

def watch_cancel(window, closed):
    marker = os.environ.get("DUALCLOUD_LOGIN_CANCEL")
    if not marker:
        return
    def watch():
        while not closed.wait(.2):
            if Path(marker).is_file():
                closed.set()
                window.destroy()
                return
    window.events.shown += lambda: threading.Thread(target=watch, daemon=True).start()
