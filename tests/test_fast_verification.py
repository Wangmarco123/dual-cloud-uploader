import sqlite3
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock
from remote_metadata import parse_metadata
from uploader_core import Queue
from uploader_engine import Worker, Backend

REMOTE="/我的作品/客户 文件.zip"
ALI="""当前目录: /我的作品/客户 文件.zip
# FILE ID 文件大小 文件SHA1 文件大小(原始) 创建日期 修改日期 文件(目录)
  1  abcdef123456  12B  aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa  12  2026-11-14 10:00:00  2026-11-14 10:00:01  客户 文件.zip
"""
BAIDU="""  类型              文件
  文件路径          /我的作品/客户 文件.zip
  文件名称          客户 文件.zip
  文件大小          12, 12B
  md5 (可能不正确)  dddddddddddddddddddddddddddddddd
"""

class MetadataTests(TestCase):
    def test_ali_uses_exact_bytes_and_server_sha1(self):
        self.assertEqual(parse_metadata("ali",ALI,REMOTE),{"size":12,"sha1":"a"*40})
    def test_baidu_uses_bytes_not_unreliable_md5(self):
        self.assertEqual(parse_metadata("baidu",BAIDU,REMOTE),{"size":12})
    def test_rejects_wrong_path_directory_rounded_size_or_duplicates(self):
        for provider,text in (("ali",ALI.replace(REMOTE,"/wrong")),
          ("ali",ALI.replace("  12  ","  12B  ")),
          ("ali",ALI+ALI.splitlines()[-1]+"\n"),
          ("baidu",BAIDU.replace(REMOTE,"/wrong")),
          ("baidu",BAIDU.replace("类型              文件","类型              目录")),
          ("baidu",BAIDU.replace("12, 12B","12B")),
          ("baidu",BAIDU+"文件大小  12\n")):
            with self.subTest(provider=provider,text=text),self.assertRaises(RuntimeError):
                parse_metadata(provider,text,REMOTE)
    def test_quick_backend_never_downloads(self):
        with tempfile.TemporaryDirectory() as directory:
            backend=Backend("baidu",Path(directory));backend.run=Mock(return_value=BAIDU)
            evidence=backend.verify({"verification":"quick","remote_path":REMOTE},None,lambda:False)
            self.assertEqual(evidence,{"size":12})
            self.assertEqual(backend.run.call_args.args[0],["meta",REMOTE])

class UploadConcurrencyTests(TestCase):
    def test_baidu_upload_uses_four_slices_without_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            backend=Backend("baidu",Path(directory));backend.run=Mock()
            backend.upload({"remote_path":"/x/a.zip","local_path":str(Path(directory)/"a.zip")},None,lambda:False)
            args=backend.run.call_args.args[0]
            self.assertEqual(args[args.index("-p")+1],"4")
            self.assertEqual(args[args.index("--policy")+1],"skip")

class QuickQueueTests(TestCase):
    def test_new_tasks_default_quick_and_full_is_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);f=root/"a.zip";f.write_bytes(b"a")
            q=Queue(root/"queue.db")
            quick=q.enqueue("ali",[f],"/quick")[0]
            full=q.enqueue("ali",[f],"/full",verification="full")[0]
            self.assertEqual(q.get(quick)["verification"],"quick")
            self.assertEqual(Queue(q.path).get(full)["verification"],"full")
    def test_invalid_mode_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            q=Queue(Path(directory)/"q.db")
            with self.assertRaises(ValueError):q.enqueue("ali",[],"/x",verification="none")
    def test_cannot_silently_reuse_quick_task_for_full_request(self):
        self.check_mode_conflict("quick","full")
    def test_cannot_silently_reuse_full_task_for_quick_request(self):
        self.check_mode_conflict("full","quick")
    def check_mode_conflict(self,first,second):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);f=root/"a";f.write_bytes(b"a")
            q=Queue(root/"q.db");task=q.enqueue("ali",[f],"/x",verification=first)[0]
            with self.assertRaisesRegex(ValueError,"核对模式"):
                q.enqueue("ali",[f],"/x",verification=second)
            self.assertEqual(q.get(task)["verification"],first)
    def test_existing_queue_migrates_without_weakening_existing_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);db=root/"q.db"
            with sqlite3.connect(db) as c:
                c.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY,provider TEXT,local_path TEXT,remote_path TEXT,size INTEGER,mtime_ns INTEGER,sha256 TEXT,sha1 TEXT,md5 TEXT,status TEXT,attempts INTEGER,progress REAL,message TEXT,created REAL,updated REAL)")
                c.execute("INSERT INTO tasks VALUES (1,'ali','a','/a',1,0,'x','x','x','complete',1,100,'old',0,0)")
            c.close()
            q=Queue(db)
            self.assertEqual(q.get(1)["verification"],"full")
            self.assertEqual(q.get(1)["message"],"old")

class FastWorkerTests(TestCase):
    def run_case(self, evidence):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);f=root/"a";f.write_bytes(b"abc")
        q=Queue(root/"q.db");task_id=q.enqueue("baidu",[f],"/x")[0]
        backend=Mock();backend.is_logged_in.return_value=True;backend.verify.return_value=evidence
        Worker(q,root,lambda _:backend).run()
        return q.get(task_id)
    def test_fast_size_match_completes_without_claiming_sha256(self):
        t=self.run_case({"size":3})
        self.assertEqual(t["status"],"complete")
        self.assertIn("未回下载",t["message"])
        self.assertNotIn("SHA256",t["message"])
    def test_fast_size_mismatch_is_conflict(self):
        self.assertEqual(self.run_case({"size":4})["status"],"conflict")
    def test_server_hash_mismatch_cannot_pass_equal_size(self):
        self.assertEqual(self.run_case({"size":3,"sha1":"wrong"})["status"],"conflict")
