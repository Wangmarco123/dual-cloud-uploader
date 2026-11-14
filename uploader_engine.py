"""Backend subprocess adapters and a serialized, resumable queue worker."""
import os
import queue as thread_queue
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from uploader_core import WorkerLock, hashes, redact, verify_hashes

ROOT = Path(__file__).resolve().parent
PROVIDERS = {"ali": "阿里云盘", "baidu": "百度网盘"}

class AuthRequired(RuntimeError):
    pass

class Conflict(RuntimeError):
    pass

class Cancelled(RuntimeError):
    pass

def state_home():
    home = Path(os.environ.get("DUALCLOUD_HOME", str(Path(os.environ["LOCALAPPDATA"]) / "DualCloudUploader")))
    home.mkdir(parents=True, exist_ok=True)
    return home

def secure_state(home):
    if os.name != "nt":
        home.chmod(0o700)
        return
    import ctypes
    buffer = ctypes.create_unicode_buffer(256)
    size = ctypes.c_ulong(len(buffer))
    if not ctypes.windll.advapi32.GetUserNameW(buffer, ctypes.byref(size)):
        raise RuntimeError("无法确认当前 Windows 用户")
    account = os.environ.get("USERDOMAIN", "") + chr(92) + buffer.value
    subprocess.run(["icacls", str(home), "/inheritance:r", "/grant:r", account + ":(OI)(CI)F",
                    "*S-1-5-18:(OI)(CI)F"], check=True, capture_output=True,
                   creationflags=subprocess.CREATE_NO_WINDOW)

class Backend:
    def __init__(self, provider, home=None):
        if provider not in PROVIDERS:
            raise ValueError("未知网盘")
        self.provider = provider
        self.home = Path(home) if home else state_home()
        self.config = self.home / "accounts" / provider
        self.config.mkdir(parents=True, exist_ok=True)
        executable = "aliyunpan.exe" if provider == "ali" else "BaiduPCS-Go.exe"
        found = list((ROOT / "bin" / provider).rglob(executable))
        if len(found) != 1:
            raise RuntimeError("上传引擎缺失，请检查安装目录")
        self.executable = found[0]
        self.env = os.environ.copy()
        self.env.update({
            "ALIYUNPAN_CONFIG_DIR": str(self.home / "accounts" / "ali"),
            "BAIDUPCS_GO_CONFIG_DIR": str(self.home / "accounts" / "baidu"),
            "ALIYUNPAN_VERBOSE": "0", "BAIDUPCS_GO_VERBOSE": "0",
            "NO_COLOR": "1", "TERM": "dumb"
        })

    def run(self, arguments, emit=None, cancelled=lambda: False, timeout=3600):
        """No shell, no secrets in logs; a quiet child can still be cancelled."""
        process = subprocess.Popen(
            [str(self.executable), *arguments], cwd=self.config, env=self.env,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        lines = thread_queue.Queue()
        def read_output():
            try:
                for line in process.stdout:
                    lines.put(line)
            finally:
                lines.put(None)
        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        started = time.monotonic()
        tail = ""
        finished = False
        try:
            while not finished:
                if cancelled():
                    raise Cancelled("任务已取消或暂停")
                if time.monotonic() - started > timeout:
                    raise RuntimeError("请求超时，请检查网络后重试")
                try:
                    line = lines.get(timeout=0.15)
                except thread_queue.Empty:
                    continue
                if line is None:
                    finished = True
                    continue
                tail = (tail + line)[-12000:]
                if emit:
                    emit(redact(line).strip())
            process.wait(timeout=10)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            process.stdout.close()
            reader.join(timeout=2)
        auth_terms = ("未登录", "请先登录", "登录已过期", "token已过期", "invalidaccesstoken",
                      "invalid access token", "refresh token expired", "登录状态已失效")
        if any(term in tail.lower() for term in auth_terms):
            raise AuthRequired("登录已失效，请在登录窗口重新授权")
        if process.returncode != 0:
            raise RuntimeError(redact(tail[-1500:]) or "上传引擎执行失败")
        return tail

    def is_logged_in(self, cancelled=lambda: False):
        try:
            result = self.run(["who"], cancelled=cancelled, timeout=35)
            if self.provider == "baidu" and re.search(r"uid:\s*0(?:,|\s|$)", result):
                return False
            return bool(result.strip()) and not any(x in result for x in ("未登录", "未找到帐号", "没有登录"))
        except AuthRequired:
            return False

    def upload(self, task, emit, cancelled):
        parent = task["remote_path"].rsplit("/", 1)[0] or "/"
        if parent != "/":
            self.run(["mkdir", parent], emit, cancelled, timeout=90)
        if self.provider == "ali":
            options = ["--skip", "-p", "1", "--retry", "1", "--timeout", "60"]
        else:
            options = ["--policy", "skip", "-p", "4", "-l", "1", "--retry", "1"]
        local = Path(task["local_path"]).as_posix()
        self.run(["upload", *options, local, parent], emit, cancelled, timeout=24*3600)

    def verify(self, task, emit, cancelled):
        if task.get("verification", "full") == "quick":
            from remote_metadata import parse_metadata
            command = "ll" if self.provider == "ali" else "meta"
            output = self.run([command, task["remote_path"]], None, cancelled, timeout=90)
            return parse_metadata(self.provider, output, task["remote_path"])
        # The backends do not consistently expose trustworthy exact remote digests.
        # A fresh temporary download provides independent content evidence.
        verify_root = self.home / "verification"
        verify_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="check_", dir=verify_root) as name:
            destination = Path(name)
            options = ["--saveto", destination.as_posix(), "-p", "1", "--retry", "1"]
            if self.provider == "ali":
                options += ["--sp", "1"]
            else:
                options += ["-l", "1"]
            self.run(["download", *options, task["remote_path"]], emit, cancelled, timeout=24*3600)
            files = [p for p in destination.rglob("*") if p.is_file() and not p.is_symlink()
                     and p.name == Path(task["remote_path"]).name]
            if len(files) != 1:
                raise RuntimeError("上传已提交，但回下载校验未取得唯一文件；请重试并核查云端目录")
            if cancelled():
                raise Cancelled()
            return hashes(files[0])

    def login_console(self):
        return subprocess.call([str(self.executable), "login"], cwd=self.config, env=self.env)

class Worker:
    def __init__(self, queue, home=None, backend_factory=None):
        self.queue = queue
        self.home = Path(home) if home else state_home()
        self.backend_factory = backend_factory or (lambda p: Backend(p, self.home))
        self.stop = threading.Event()
        self.retry_delay = 1.0

    def run(self):
        with WorkerLock(self.home / "worker.lock"):
            self.queue.recover()
            while not self.stop.is_set():
                pending = [task for task in reversed(self.queue.list()) if task["status"] == "pending"]
                if not pending:
                    break
                self.run_task(pending[0])

    def run_task(self, task):
        task_id = task["id"]
        def cancelled():
            return self.stop.is_set() or self.queue.get(task_id)["status"] == "cancelled"
        try:
            if task["attempts"] >= 3:
                raise RuntimeError("任务已达重试上限，请检查后点重新排队")
            self.queue.validate_source(task)
            backend = self.backend_factory(task["provider"])
            if not backend.is_logged_in(cancelled):
                raise AuthRequired("需要先登录 " + PROVIDERS[task["provider"]])
            for attempt in range(task["attempts"] + 1, 4):
                if cancelled():
                    raise Cancelled()
                self.queue.update(task_id, status="uploading", attempts=attempt, progress=0, message="正在上传")
                last_progress = 0.0
                def emit(line):
                    nonlocal last_progress
                    if not line:
                        return
                    # Never turn a persistent cancellation back into a running state.
                    if cancelled():
                        return
                    now = time.monotonic()
                    match = re.search(r"(\d{1,3}(?:\.\d+)?)%", line)
                    if match and now-last_progress > 0.5:
                        fraction = min(100, float(match.group(1)))
                        verifying = self.queue.get(task_id)["status"] == "verifying"
                        progress = 90 + fraction*.09 if verifying else fraction*.90
                        self.queue.update(task_id, progress=progress)
                        last_progress = now
                    if "%" not in line:
                        self.queue.event(task_id, line)
                try:
                    backend.upload(task, emit, cancelled)
                    if cancelled():
                        raise Cancelled()
                    self.queue.update(task_id, status="verifying", progress=90,
                                      message=("正在核对云端字节数（不回下载）" if task.get("verification")=="quick" else "上传已提交，正在回下载核对 SHA256"))
                    evidence = backend.verify(task, emit, cancelled)
                    if cancelled():
                        raise Cancelled()
                    self.queue.validate_source(task)
                    quick = task.get("verification") == "quick"
                    if quick:
                        if "size" not in evidence:
                            raise RuntimeError("缺少准确的云端文件大小")
                        if evidence["size"] != task["size"]:
                            raise Conflict("云端同名文件字节数不同，请换文件名或目录")
                        for digest in ("sha1", "md5", "sha256"):
                            if evidence.get(digest) and evidence[digest].lower() != task[digest].lower():
                                raise Conflict("服务端文件摘要不同，请换文件名或目录")
                    elif not verify_hashes(task, evidence):
                        if "sha256" not in evidence and "sha1" not in evidence and "md5" not in evidence:
                            raise RuntimeError("缺少内容校验证据，不能确认完成")
                        raise Conflict("云端同名文件内容不一致，已保留原文件；请换目录或文件名")
                    self.queue.update(task_id, status="complete", progress=100,
                                      message=("已上传，云端字节数一致（未回下载）" if quick else "云端文件已回下载，SHA256 校验一致"))
                    self.queue.event(task_id, "快速上传完成，云端字节数一致" if quick else "上传及云端内容校验完成")
                    return
                except (AuthRequired, Conflict, Cancelled, ValueError):
                    raise
                except Exception as exc:
                    self.queue.event(task_id, "本次尝试失败：" + str(exc))
                    if attempt == 3:
                        raise
                    self.queue.update(task_id, message="网络或校验失败，正在重试")
                    if self.stop.wait(self.retry_delay):
                        raise Cancelled()
        except Cancelled:
            if self.queue.get(task_id)["status"] != "cancelled":
                attempts = self.queue.get(task_id)["attempts"]
                self.queue.update(task_id, status="pending", attempts=max(0,attempts-1),
                                  message="已暂停，可恢复")
        except AuthRequired as exc:
            if not cancelled():
                self.queue.update(task_id, status="awaiting_login", message=str(exc))
        except Conflict as exc:
            if not cancelled():
                self.queue.update(task_id, status="conflict", message=str(exc))
        except Exception as exc:
            if not cancelled():
                self.queue.update(task_id, status="failed", message=str(exc))
