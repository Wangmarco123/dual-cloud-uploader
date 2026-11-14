import tempfile
import unittest
from pathlib import Path
from uploader_core import Queue, normalize_remote, redact, expand_sources, verify_hashes, WorkerLock

class UploadRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.queue = Queue(self.root / "tasks.db")
        self.file = self.root / "客户 文件.zip"
        self.file.write_bytes(b"customer delivery")

    def tearDown(self):
        self.tmp.cleanup()

    def test_paths_remain_absolute_and_cannot_escape(self):
        self.assertEqual(normalize_remote("/我的作品/图纸"), "/我的作品/图纸")
        for value in ("../other", "/a/../b", "//server/share", "/a/*", "/a\nb", "C:/files"):
            with self.assertRaises(ValueError):
                normalize_remote(value)

    def test_log_redacts_cookies_tokens_json_and_signed_urls(self):
        raw = ('Cookie: BDUSS=abc; STOKEN=xyz\n'
               '{"access_token":"VERYSECRET","refresh_token": "SECRET2"}\n'
               'https://upload.example/file?security-token=HIDDEN&x-oss-signature=SIGN\n'
               'Authorization: Bearer SENSITIVE\n')
        clean = redact(raw)
        for secret in ("abc", "xyz", "VERYSECRET", "SECRET2", "HIDDEN", "SIGN", "SENSITIVE"):
            self.assertNotIn(secret, clean)

    def test_folder_expansion_preserves_relative_paths(self):
        folder = self.root / "交付"
        (folder / "子目录").mkdir(parents=True)
        (folder / "子目录" / "a.zip").write_bytes(b"a")
        items = expand_sources([folder], "/我的作品")
        self.assertEqual(items[0][1], "/我的作品/交付/子目录/a.zip")

    def test_same_destination_collision_is_rejected_atomically(self):
        other = self.root / "other"
        other.mkdir()
        same = other / self.file.name
        same.write_bytes(b"different")
        with self.assertRaises(ValueError):
            self.queue.enqueue("ali", [self.file, same], "/我的作品")
        self.assertEqual(self.queue.list(), [])

    def test_cancel_survives_restart_and_running_tasks_are_recovered(self):
        ids = self.queue.enqueue("ali", [self.file], "/我的作品")
        self.queue.update(ids[0], status="uploading")
        restarted = Queue(self.root / "tasks.db")
        restarted.recover()
        self.assertEqual(restarted.get(ids[0])["status"], "pending")
        restarted.cancel(ids[0])
        restarted.recover()
        self.assertEqual(restarted.get(ids[0])["status"], "cancelled")

    def test_changed_file_is_detected_before_upload(self):
        task = self.queue.get(self.queue.enqueue("baidu", [self.file], "/我的作品")[0])
        self.file.write_bytes(b"changed file")
        with self.assertRaises(ValueError):
            self.queue.validate_source(task)

    def test_conflicting_active_target_is_not_duplicated(self):
        first = self.queue.enqueue("ali", [self.file], "/我的作品")
        second = self.queue.enqueue("ali", [self.file], "/我的作品")
        self.assertEqual(first, second)
        self.file.write_bytes(b"new revision")
        with self.assertRaises(ValueError):
            self.queue.enqueue("ali", [self.file], "/我的作品")

    def test_verification_requires_content_evidence(self):
        self.assertTrue(verify_hashes({"size":3,"sha1":"abc"}, {"size":3,"sha1":"abc"}))
        self.assertFalse(verify_hashes({"size":3,"sha1":"abc"}, {"size":3,"sha1":"wrong"}))
        self.assertFalse(verify_hashes({"size":3}, {"size":3}))
        self.assertFalse(verify_hashes({"size":3,"md5":"abc"}, {"size":4,"md5":"abc"}))

    def test_late_progress_update_does_not_resurrect_cancelled_task(self):
        task_id = self.queue.enqueue("ali", [self.file], "/我的作品")[0]
        self.queue.cancel(task_id)
        self.queue.update(task_id, status="complete", progress=100)
        self.assertEqual(self.queue.get(task_id)["status"], "cancelled")

    def test_interrupted_last_attempt_can_resume(self):
        task_id = self.queue.enqueue("ali", [self.file], "/我的作品")[0]
        self.queue.update(task_id, status="uploading", attempts=3)
        self.queue.recover()
        task = self.queue.get(task_id)
        self.assertEqual(task["status"], "pending")
        self.assertEqual(task["attempts"], 2)

    def test_worker_lock_prevents_two_upload_workers(self):
        with WorkerLock(self.root / "worker.lock"):
            with self.assertRaises(RuntimeError):
                with WorkerLock(self.root / "worker.lock"):
                    pass

if __name__ == "__main__":
    unittest.main()
