"""Direct Ali authorization web window, driven by the installed CLI login flow."""
import json
import queue
import re
import subprocess
import threading
import time
import urllib.parse
from uploader_core import WorkerLock
from uploader_engine import Backend

def parse_authorize_url(text):
    for match in re.finditer(r"https://[^\s<>\"']+",text):
        url=match.group(0)
        parts=urllib.parse.urlparse(url)
        if parts.netloc!="openapi.alipan.com" or parts.path!="/oauth/authorize":
            continue
        query=urllib.parse.parse_qs(parts.query)
        target=urllib.parse.urlparse(query.get("redirect_uri",[""])[0])
        if target.scheme!="https" or target.netloc!="api.tickstep.com":
            continue
        ticket=re.fullmatch(r"/auth/tickstep/aliyunpan/token/openapi/([A-Za-z0-9_-]{8,128})/auth2?",target.path)
        if ticket:
            return url,ticket.group(1)
    return None

def authorization_completed(url, ticket):
    """Trust only the successful callback for this CLI-generated ticket."""
    parts = urllib.parse.urlparse(url or "")
    query = urllib.parse.parse_qs(parts.query)
    return (parts.scheme == "https" and parts.netloc == "api.tickstep.com"
            and parts.path == "/pages/tickstep/aliyunpan/oauth/openapi_login_result"
            and query.get("status") == ["success"]
            and query.get("ticketId") == [ticket])

class AuthorizationContinuation:
    def __init__(self, ticket):
        self.ticket = ticket
        self.completed = threading.Event()
        self.sent = False

    def observe(self, url):
        if authorization_completed(url, self.ticket):
            self.completed.set()

    def resume(self, process):
        if self.sent or not self.completed.is_set() or process.poll() is not None:
            return False
        process.stdin.write("\n")
        process.stdin.flush()
        self.sent = True
        return True

def login(home):
    import webview
    result_file=home/"ali_login_result.json"
    last_state = None
    def record(state,message):
        nonlocal last_state
        last_state = state
        result_file.write_text(json.dumps({"state":state,"message":message,"time":time.time()},
                                         ensure_ascii=False),encoding="utf-8")
    record("waiting","正在打开阿里扫码授权网页")
    backend=Backend("ali",home)
    closed=threading.Event()
    finished=threading.Event()
    window=webview.create_window(
        "阿里云盘扫码登录 · 请在网页完成授权和扫码",
        html='<html><meta charset="utf-8"><body style="font:20px Microsoft YaHei;padding:60px">'
             '<h2>正在准备阿里扫码授权网页</h2><p>稍候会自动打开，请在网页里完成授权和扫码。</p>'
             '<p>授权回调使用 api.tickstep.com，请核对网页显示的应用与权限。</p></body></html>',
        width=1020,height=780,min_size=(800,600))
    window.events.closed += closed.set
    from login_lifecycle import watch_cancel
    watch_cancel(window, closed)
    webview.settings["ALLOW_DOWNLOADS"]=False
    webview.settings["ALLOW_FILE_URLS"]=False
    webview.settings["IGNORE_SSL_ERRORS"]=False
    webview.settings["OPEN_DEVTOOLS_IN_DEBUG"]=False
    process=None
    succeeded=False

    def monitor():
        nonlocal process,succeeded
        try:
            process=subprocess.Popen(
                [str(backend.executable),"login"],cwd=backend.config,env=backend.env,
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                text=True,encoding="utf-8",errors="replace",bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW)
            lines=queue.Queue()
            def read_output():
                try:
                    for line in process.stdout:
                        lines.put(line)
                finally:
                    lines.put(None)
            reader=threading.Thread(target=read_output,daemon=True)
            reader.start()
            ticket=None
            continuation=None
            success_line=False
            deadline=time.monotonic()+360
            stream_ended=False
            while not closed.is_set() and time.monotonic()<deadline:
                try:
                    line=lines.get(timeout=.3)
                    if line is None:
                        stream_ended=True
                    else:
                        parsed=parse_authorize_url(line)
                        if parsed and not ticket:
                            url,ticket=parsed
                            continuation=AuthorizationContinuation(ticket)
                            window.load_url(url)
                            record("waiting","请在阿里网页完成授权及扫码，完成后会自动接入")
                        if "阿里云盘登录成功" in line:
                            success_line=True
                except queue.Empty:
                    pass
                if continuation and not closed.is_set():
                    # Observe the final page, never poll the one-shot token endpoint.
                    continuation.observe(window.get_current_url())
                    if continuation.resume(process):
                        record("checking","网页授权已完成，正在自动接续账号")
                if stream_ended and process.poll() is not None:
                    if process.returncode==0 and success_line and backend.is_logged_in(closed.is_set):
                        succeeded=True
                        record("done","阿里登录已接入，可开始上传")
                        window.title="阿里云盘登录成功"
                        window.load_html(
                            '<html><meta charset="utf-8"><body style="font:20px Microsoft YaHei;padding:70px">'
                            '<h2>阿里云盘登录成功</h2><p>已接入上传助手，本窗口即将关闭。</p></body></html>')
                        if not closed.wait(2):
                            window.destroy()
                    else:
                        record("error","阿里授权未完成或已过期，请关闭此窗口后重新登录")
                    break
            if not succeeded and not closed.is_set() and time.monotonic()>=deadline:
                record("error","阿里二维码或授权链接已超时，请关闭窗口后重新登录")
        except Exception:
            record("error","阿里扫码窗口暂未接入，请检查网络或重新登录")
        finally:
            if process is not None:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                for stream in (process.stdin,process.stdout):
                    if stream:
                        stream.close()
            finished.set()

    try:
        with WorkerLock(home/"worker.lock"):
            try:
                webview.start(monitor,gui="edgechromium",debug=False,private_mode=False,
                              storage_path=str(home/"accounts"/"ali_webview"))
            finally:
                closed.set()
                finished.wait(12)
    except Exception:
        record("error","无法打开阿里扫码窗口，或另一个上传/登录任务正在运行")
        raise RuntimeError("阿里扫码登录暂未启动，请检查当前任务")
    if not succeeded and last_state not in ("error", "done"):
        record("cancelled","阿里扫码窗口已关闭，尚未完成本次授权")
    return 0 if succeeded else 2
