"""Baidu QR login in an app-owned WebView2 profile. No existing browser profile is read."""
import json
import threading
import time
from urllib.parse import urlparse
from uploader_core import WorkerLock
from uploader_engine import Backend

def cookie_header(cookies):
    values = {}
    for cookie in cookies:
        for name, morsel in cookie.items():
            domain = morsel["domain"].lstrip(".").lower()
            if domain == "baidu.com" or domain.endswith(".baidu.com"):
                values[name] = morsel.value
    if not values.get("BDUSS"):
        return None
    return "; ".join(name + "=" + value for name,value in values.items())

def connect_cookie(backend, header, closed):
    for attempt in range(3):
        if closed.is_set():
            return False
        try:
            backend.run(["login","--cookies",header],cancelled=closed.is_set,timeout=45)
            if backend.is_logged_in(closed.is_set):
                return True
        except Exception:
            pass
        if closed.wait(min(2**attempt,8)):
            return False
    return False

def login(home):
    import webview
    result_file = home / "baidu_login_result.json"
    def record(state,message):
        result_file.write_text(json.dumps({"state":state,"message":message,"time":time.time()},
                                         ensure_ascii=False),encoding="utf-8")
    record("waiting","请在百度扫码登录窗口完成扫码")
    webview.settings["ALLOW_DOWNLOADS"] = False
    webview.settings["ALLOW_FILE_URLS"] = False
    webview.settings["IGNORE_SSL_ERRORS"] = False
    webview.settings["OPEN_DEVTOOLS_IN_DEBUG"] = False
    window = webview.create_window(
        "百度网盘扫码登录 · 扫码后自动接入上传助手",
        "https://pan.baidu.com/",width=1000,height=740,min_size=(800,600))
    closed = threading.Event()
    window.events.closed += closed.set
    from login_lifecycle import watch_cancel
    watch_cancel(window, closed)
    backend = Backend("baidu",home)
    succeeded = False

    def monitor():
        nonlocal succeeded
        while not closed.wait(2):
            try:
                url = window.get_current_url()
                if not url or urlparse(url).hostname != "pan.baidu.com":
                    continue
                header = cookie_header(window.get_cookies())
                if not header:
                    continue
                record("checking","已收到扫码登录状态，正在接入上传引擎")
                connected = connect_cookie(backend,header,closed)
                header = ""
                if not connected:
                    record("waiting","登录状态尚未确认，网络失败会自动重试，请完成网页确认后等待")
                    if closed.wait(10):
                        break
                    continue
                succeeded = True
                record("done","百度登录已接入，可回到主窗口开始上传")
                window.title = "百度网盘登录成功"
                window.load_html(
                    '<html><meta charset="utf-8"><body style="font:20px Microsoft YaHei;'
                    'padding:70px;color:#24405b"><h2>百度网盘登录成功</h2>'
                    '<p>扫码登录状态已保存在本机上传助手中。</p>'
                    '<p>回到主窗口刷新账号后即可开始上传。本窗口即将关闭。</p></body></html>')
                if not closed.wait(3):
                    window.destroy()
                return
            except Exception:
                record("waiting","尚未接入上传引擎，请完成网页登录并等待；也可关闭后重新登录")
        if not succeeded:
            record("cancelled","扫码登录窗口已关闭，尚未完成接入")

    finished = threading.Event()
    def monitored():
        try:
            monitor()
        finally:
            finished.set()

    with WorkerLock(home / "worker.lock"):
        try:
            webview.start(monitored,gui="edgechromium",debug=False,private_mode=False,
                          storage_path=str(home/"accounts"/"baidu_webview"))
        except Exception as exc:
            record("error","无法打开百度扫码窗口，请检查 WebView2 运行环境")
            raise RuntimeError("无法打开百度扫码窗口") from exc
        finally:
            closed.set()
            finished.wait(12)
    return 0 if succeeded else 2
