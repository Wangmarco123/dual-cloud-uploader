import tempfile
import threading
import unittest
from pathlib import Path
from uploader_core import Queue
from uploader_engine import Worker, AuthRequired, Conflict

class FakeBackend:
    upload_calls = 0
    def __init__(self, evidence=None, failure=None):
        self.evidence = evidence
        self.failure = failure
    def is_logged_in(self, cancelled):
        return self.failure is not AuthRequired
    def upload(self, task, emit, cancelled):
        self.upload_calls += 1
        if self.failure:
            raise self.failure("test failure")
        emit("upload 100.00%")
    def verify(self, task, emit, cancelled):
        if callable(self.evidence):
            return self.evidence(task)
        return self.evidence

class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.queue = Queue(self.root / "tasks.db")
        source = self.root / "交付.zip"
        source.write_bytes(b"approved")
        self.task_id = self.queue.enqueue("ali", [source], "/我的作品", verification="full")[0]
    def tearDown(self):
        self.tmp.cleanup()
    def run_with(self, backend):
        worker = Worker(self.queue, self.root, lambda provider: backend)
        worker.run()
    def test_exit_success_without_verification_does_not_finish(self):
        self.run_with(FakeBackend({"size":8}))
        self.assertEqual(self.queue.get(self.task_id)["status"], "failed")
    def test_verified_upload_is_complete(self):
        self.run_with(FakeBackend(lambda task: {"size":task["size"],"sha256":task["sha256"]}))
        self.assertEqual(self.queue.get(self.task_id)["status"], "complete")
        self.assertEqual(self.queue.get(self.task_id)["progress"], 100)
    def test_missing_login_is_visible_without_repeated_upload(self):
        backend = FakeBackend(failure=AuthRequired)
        self.run_with(backend)
        self.assertEqual(backend.upload_calls, 0)
        self.assertEqual(self.queue.get(self.task_id)["status"], "awaiting_login")
    def test_remote_content_conflict_is_not_marked_success(self):
        self.run_with(FakeBackend({"size":8,"sha256":"different"}))
        self.assertEqual(self.queue.get(self.task_id)["status"], "conflict")
    def test_cancelled_task_is_not_claimed(self):
        self.queue.cancel(self.task_id)
        backend = FakeBackend()
        self.run_with(backend)
        self.assertEqual(backend.upload_calls, 0)
        self.assertEqual(self.queue.get(self.task_id)["status"], "cancelled")
    def test_transient_failure_has_bounded_attempts(self):
        backend = FakeBackend(failure=RuntimeError)
        self.run_with(backend)
        task = self.queue.get(self.task_id)
        self.assertEqual(task["attempts"], 3)
        self.assertEqual(task["status"], "failed")
    def test_paused_last_attempt_remains_resumable(self):
        self.queue.update(self.task_id, attempts=2)
        worker = Worker(self.queue,self.root)
        def evidence(task):
            worker.stop.set()
            return {"size":task["size"],"sha256":task["sha256"]}
        worker.backend_factory = lambda provider: FakeBackend(evidence)
        worker.run()
        task = self.queue.get(self.task_id)
        self.assertEqual(task["status"], "pending")
        self.assertEqual(task["attempts"], 2)

    def test_cancellation_during_verification_is_preserved(self):
        def evidence(task):
            self.queue.cancel(task["id"])
            return {"size":task["size"],"sha256":task["sha256"]}
        self.run_with(FakeBackend(evidence))
        self.assertEqual(self.queue.get(self.task_id)["status"], "cancelled")

if __name__ == "__main__":
    unittest.main()
