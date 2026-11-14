"""Persistent file queue and content checks for the local dual-drive uploader."""
import hashlib
import os
import posixpath
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

ACTIVE = ("pending", "uploading", "verifying", "awaiting_login")
STATUSES = (*ACTIVE, "complete", "failed", "cancelled", "conflict")

def normalize_remote(value):
    value = value.strip()
    if not value.startswith("/") or value.startswith("//"):
        raise ValueError("云端目录必须以单个 / 开头")
    if any(ord(c) < 32 or c in "\\:*?[]\"<>|" for c in value):
        raise ValueError("云端路径包含不支持的字符")
    if ".." in value.split("/"):
        raise ValueError("云端目录不能包含 ..")
    return posixpath.normpath(value)

def redact(text):
    text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", str(text))
    text = re.sub(r"https?://[^\s\"<>]+", "[链接已隐藏]", text, flags=re.I)
    text = re.sub(r"(?im)^.*(?:cookie\s*:|authorization\s*:).*$", "[认证信息已隐藏]", text)
    keys = r"(?:access_token|refresh_token|id_token|bduss|stoken|ptoken|security.token|client_secret|signature)"
    text = re.sub(r'(?i)(["\x27]?' + keys + r'["\x27]?\s*[:=]\s*)(?:"[^"]*"|\x27[^\x27]*\x27|[^\s;,}]+)',
                  r"\1[已隐藏]", text)
    return text

def hashes(path):
    before = path.stat()
    digests = {name: hashlib.new(name) for name in ("sha256", "sha1", "md5")}
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            for digest in digests.values():
                digest.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("文件在读取过程中发生变化，请文件保存完成后重新添加")
    return {"size": after.st_size, "mtime_ns": after.st_mtime_ns,
            **{key: digest.hexdigest() for key, digest in digests.items()}}

def expand_sources(paths, destination):
    destination = normalize_remote(destination)
    result = []
    targets = set()
    for value in paths:
        path = Path(value).absolute()
        if path.is_symlink() or path.is_junction():
            raise ValueError("请直接选择文件或目录，暂不处理符号链接或目录联接")
        if not path.exists():
            raise ValueError("本地路径不存在")
        if path.is_dir():
            children = []
            for directory, dirs, files in os.walk(path, followlinks=False):
                for name in dirs + files:
                    child = Path(directory) / name
                    if child.is_symlink() or child.is_junction():
                        raise ValueError("目录含符号链接或目录联接，请移除链接后重新添加")
                children.extend(Path(directory) / name for name in sorted(files))
        elif path.is_file():
            children = [path]
        else:
            raise ValueError("只能选择普通文件或文件夹")
        for child in children:
            relative = child.relative_to(path.parent) if path.is_dir() else Path(child.name)
            remote = normalize_remote(destination.rstrip("/") + "/" + relative.as_posix())
            key = remote.casefold()
            if key in targets:
                raise ValueError("多个本地文件指向相同的云端文件名")
            targets.add(key)
            result.append((child, remote))
    if not result:
        raise ValueError("所选文件夹中没有可上传的普通文件")
    return result

def verify_hashes(local, remote):
    if local.get("size") != remote.get("size"):
        return False
    for name in ("sha256", "sha1", "md5"):
        if local.get(name) and remote.get(name):
            return str(local[name]).lower() == str(remote[name]).lower()
    return False

class Queue:
    def __init__(self, database):
        self.path = Path(database)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY, provider TEXT NOT NULL,
                    local_path TEXT NOT NULL, remote_path TEXT NOT NULL,
                    size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
                    sha256 TEXT NOT NULL, sha1 TEXT NOT NULL, md5 TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                    progress REAL NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '',
                    created REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, task_id INTEGER, stamp REAL, message TEXT);
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(tasks)")}
            if "verification" not in columns:
                db.execute("ALTER TABLE tasks ADD COLUMN verification TEXT NOT NULL DEFAULT 'full'")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def enqueue(self, provider, paths, destination, verification="quick"):
        if verification not in ("quick", "full"):
            raise ValueError("未知核对模式")
        if provider not in ("ali", "baidu"):
            raise ValueError("未知网盘")
        items = [(path, remote, hashes(path)) for path, remote in expand_sources(paths, destination)]
        ids = []
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for path, remote, info in items:
                existing = db.execute(
                    "SELECT * FROM tasks WHERE provider=? AND remote_path=? AND status IN (?,?,?,?)",
                    (provider, remote, *ACTIVE)).fetchone()
                if existing:
                    if existing["verification"] != verification:
                        raise ValueError("该路径已有不同核对模式的活动任务，请先取消旧任务再重新添加")
                    if existing["sha256"] != info["sha256"]:
                        raise ValueError("该云端路径已有不同内容的待上传任务，请更换目录或先取消旧任务")
                    ids.append(existing["id"])
                    continue
                now = time.time()
                cursor = db.execute("""
                    INSERT INTO tasks (provider,local_path,remote_path,size,mtime_ns,sha256,sha1,md5,created,updated,verification)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (provider,str(path),remote,info["size"],info["mtime_ns"],info["sha256"],
                     info["sha1"],info["md5"],now,now,verification))
                ids.append(cursor.lastrowid)
        return ids

    def get(self, task_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise ValueError("任务不存在")
        return dict(row)

    def list(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM tasks ORDER BY id DESC")]

    def update(self, task_id, **fields):
        allowed = {"status", "attempts", "progress", "message"}
        if not fields or not set(fields) <= allowed:
            raise ValueError("无效任务字段")
        if "status" in fields and fields["status"] not in STATUSES:
            raise ValueError("无效状态")
        if "message" in fields:
            fields["message"] = redact(fields["message"])[-1200:]
        fields["updated"] = time.time()
        with self.connect() as db:
            db.execute("UPDATE tasks SET " + ",".join(key+"=?" for key in fields) + " WHERE id=? AND status!='cancelled'",
                       (*fields.values(), task_id))

    def recover(self):
        # Caller must own WorkerLock. Never reset work owned by another process.
        with self.connect() as db:
            db.execute("UPDATE tasks SET status='pending',attempts=MAX(attempts-1,0),message='上次运行中断，等待恢复',updated=? "
                       "WHERE status IN ('uploading','verifying')", (time.time(),))

    def cancel(self, task_id):
        with self.connect() as db:
            db.execute("UPDATE tasks SET status='cancelled',message='已取消',updated=? "
                       "WHERE id=? AND status!='complete'", (time.time(), task_id))

    def retry(self, task_id):
        with self.connect() as db:
            db.execute("UPDATE tasks SET status='pending',attempts=0,progress=0,message='',updated=? "
                       "WHERE id=? AND status IN ('failed','conflict','cancelled','awaiting_login')",
                       (time.time(),task_id))

    def event(self, task_id, message):
        with self.connect() as db:
            db.execute("INSERT INTO events(task_id,stamp,message) VALUES(?,?,?)",
                       (task_id,time.time(),redact(message)[-2000:]))
            db.execute("DELETE FROM events WHERE id < (SELECT MAX(id)-3000 FROM events)")

    def events(self, task_id=None):
        with self.connect() as db:
            if task_id is None:
                rows = db.execute("SELECT * FROM events ORDER BY id DESC LIMIT 150")
            else:
                rows = db.execute("SELECT * FROM events WHERE task_id=? ORDER BY id DESC LIMIT 150", (task_id,))
            return [dict(row) for row in rows][::-1]

    def validate_source(self, task):
        path = Path(task["local_path"])
        if path.is_symlink() or not path.is_file():
            raise ValueError("本地源文件丢失或变成链接，请重新添加")
        current = hashes(path)
        if current["sha256"] != task["sha256"] or current["size"] != task["size"]:
            raise ValueError("本地文件已修改，请取消任务并重新添加")
        return current

class WorkerLock:
    def __init__(self, path):
        self.path = Path(path)
        self.file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            self.file = None
            raise RuntimeError("已有上传或登录进程正在运行") from exc
        return self

    def __exit__(self, *_):
        if self.file:
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_UN)
            self.file.close()

