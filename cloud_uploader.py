"""Local dual-cloud uploader. Run without arguments for the Chinese desktop window."""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from uploader_core import Queue, WorkerLock, redact
from uploader_engine import Backend, Worker, PROVIDERS, secure_state, state_home

ROOT = Path(__file__).resolve().parent
STATUS_LABELS = {
    "pending":"等待上传", "uploading":"上传中", "verifying":"云端校验中",
    "awaiting_login":"等待登录", "complete":"已上传", "failed":"失败",
    "cancelled":"已取消", "conflict":"同名内容冲突"
}

def console_python():
    candidate = Path(sys.executable).with_name("python.exe")
    return str(candidate if candidate.exists() else Path(sys.executable))

def launch_login(provider, cancel_path=None):
    if provider not in PROVIDERS:
        raise ValueError("未知网盘")
    pythonw = Path(console_python()).with_name("pythonw.exe")
    env = os.environ.copy()
    env.pop("DUALCLOUD_LOGIN_CANCEL", None)
    if cancel_path is not None:
        env["DUALCLOUD_LOGIN_CANCEL"] = str(cancel_path)
    return subprocess.Popen(
        [str(pythonw), str(Path(__file__).resolve()), "login", provider, "--qr"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)


def launch_worker():
    return subprocess.Popen(
        [console_python(), str(Path(__file__).resolve()), "run"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)

def interactive_login(provider, home):
    if not sys.stdin or not sys.stdin.isatty():
        raise ValueError("请点击窗口中的登录按钮，在独立交互窗口完成登录")
    backend = Backend(provider, home)
    print("\n" + PROVIDERS[provider] + "登录授权\n")
    if provider == "ali":
        print("按上传引擎提示打开阿里官方授权页面并扫码。")
        print("该引擎的授权回调经 api.tickstep.com，页面会显示申请的权限，请核对后自行授权。")
        print("完成网页步骤后，按引擎提示返回本窗口按回车。\n")
    else:
        print("请按引擎提示在本窗口完成登录。")
        print("如果提示输入登录 Cookie，请只在此窗口填写，勿发到聊天或文件中。")
        print("可先在浏览器打开 https://pan.baidu.com 登录自己的账号。\n")
    with WorkerLock(home / "worker.lock"):
        if provider == "baidu":
            import getpass
            print("请选择登录方式")
            print("1  用户名和密码登录")
            print("2  使用已登录百度网页的 Cookie")
            mode = input("输入 1 或 2，回车确认：").strip()
            if mode == "2":
                print("在自己的百度网盘网页按 F12，打开 Network（网络），刷新页面。")
                print("选择 pan.baidu.com 的请求，在 Request Headers（请求头）中复制 Cookie 值。")
                cookie = getpass.getpass("粘贴 Cookie 后回车（输入隐藏，仅本机使用）：").strip()
                if not cookie or "BDUSS=" not in cookie:
                    raise ValueError("未取得包含 BDUSS 的登录 Cookie")
                try:
                    output = backend.run(["login", "--cookies", cookie], timeout=90)
                    print(redact(output))
                    code = 0
                finally:
                    cookie = ""
            elif mode == "1":
                code = backend.login_console()
            else:
                raise ValueError("未选择登录方式")
        else:
            code = backend.login_console()
        logged_in = backend.is_logged_in()
    print("\n" + ("登录状态已确认。回到主窗口点击「刷新账号」后开始上传。" if logged_in
                  else "尚未确认登录，请按引擎提示重新登录。"))
    input("\n按回车关闭此窗口。")
    return 0 if logged_in else (code or 2)

def gui(home):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    import queue as messages

    root = tk.Tk()
    root.title("双网盘上传助手")
    root.geometry("1160x760")
    root.minsize(970, 650)
    root.configure(bg="#f2f5fa")
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", font=("Microsoft YaHei UI", 10))
    style.configure("TFrame", background="#f2f5fa")
    style.configure("TLabel", background="#f2f5fa", foreground="#22324a")
    style.configure("TLabelframe", background="#f2f5fa", bordercolor="#d4dfef")
    style.configure("TLabelframe.Label", background="#f2f5fa", foreground="#22324a")
    style.configure("TRadiobutton", background="#f2f5fa")
    style.configure("TButton", padding=(12,8))
    style.configure("Primary.TButton", foreground="white", background="#2866cf")
    style.map("Primary.TButton", background=[("active","#2054ae")])
    style.configure("Treeview", rowheight=34, font=("Microsoft YaHei UI",10),
                    background="white", fieldbackground="white")
    style.configure("Treeview.Heading", font=("Microsoft YaHei UI",10,"bold"), padding=8)

    queue = Queue(home / "tasks.db")
    mailbox = messages.Queue()
    worker = None
    worker_thread = None
    closing = False
    from login_lifecycle import OwnedLogins
    owned_logins = OwnedLogins(home, launch_login)
    selected = []
    provider = tk.StringVar(value="ali")
    destination = tk.StringVar(value="/我的作品")
    tip = tk.StringVar(value="选择文件，确认网盘与目标目录，再开始上传。")
    selection_text = tk.StringVar(value="尚未选择文件")
    account = {"ali": tk.StringVar(value="尚未检查"), "baidu":tk.StringVar(value="尚未检查")}
    prefs_file = home / "preferences.json"
    try:
        prefs = json.loads(prefs_file.read_text(encoding="utf-8"))
        destination.set(prefs.get("remote", "/我的作品"))
        provider.set(prefs.get("provider","ali") if prefs.get("provider") in PROVIDERS else "ali")
    except (OSError, ValueError):
        pass

    main = ttk.Frame(root, padding=22)
    main.pack(fill="both", expand=True)
    ttk.Label(main, text="双网盘上传助手", font=("Microsoft YaHei UI",23,"bold")).pack(anchor="w")
    ttk.Label(main, text="本地上传队列  ·  失败重试  ·  快速上传，不回下载",
              foreground="#66758c").pack(anchor="w",pady=(4,16))
    def start_login(code):
        if not closing:
            owned_logins.start(code)

    accounts = ttk.Frame(main)
    accounts.pack(fill="x")
    for code, title in PROVIDERS.items():
        card = ttk.LabelFrame(accounts, text=title, padding=12)
        card.pack(side="left", fill="x", expand=True, padx=(0,12 if code=="ali" else 0))
        ttk.Label(card, textvariable=account[code]).pack(side="left")
        ttk.Button(card, text="登录 / 重新授权", command=lambda p=code: start_login(p)).pack(side="right")
    controls = ttk.LabelFrame(main, text="新建上传任务", padding=12)
    controls.pack(fill="x",pady=14)
    for code,title in PROVIDERS.items():
        ttk.Radiobutton(controls,text=title,variable=provider,value=code).pack(side="left",padx=(0,16))
    ttk.Label(controls,text="云端目录").pack(side="left",padx=(8,8))
    ttk.Entry(controls,textvariable=destination,width=38).pack(side="left",fill="x",expand=True)
    picker = ttk.Frame(main)
    picker.pack(fill="x",pady=(0,10))
    def choose_files():
        values = filedialog.askopenfilenames(parent=root,title="选择待上传文件")
        if values:
            selected[:] = list(values)
            selection_text.set("已选 " + str(len(selected)) + " 个文件")
    def choose_folder():
        value = filedialog.askdirectory(parent=root,title="选择待上传文件夹")
        if value:
            selected[:] = [value]
            selection_text.set(value)
    def enqueue():
        if closing:
            return
        if not selected:
            messagebox.showinfo("选择文件","请先选择文件或文件夹。",parent=root)
            return
        values = list(selected)
        target = destination.get()
        code = provider.get()
        tip.set("正在读取文件并建立校验快照……")
        def job():
            try:
                ids = queue.enqueue(code,values,target)
                prefs_file.write_text(json.dumps({"remote":target,"provider":code},ensure_ascii=False),encoding="utf-8")
                mailbox.put(("tip","已加入 " + str(len(ids)) + " 个任务，确认账号后点击开始上传。"))
            except Exception as exc:
                mailbox.put(("error",redact(exc)))
        threading.Thread(target=job,daemon=True).start()
    ttk.Button(picker,text="选择文件",command=choose_files).pack(side="left")
    ttk.Button(picker,text="选择文件夹",command=choose_folder).pack(side="left",padx=8)
    ttk.Label(picker,textvariable=selection_text).pack(side="left",padx=8)
    ttk.Button(picker,text="加入队列",style="Primary.TButton",command=enqueue).pack(side="right")

    tree = ttk.Treeview(main,columns=("provider","status","progress","name","destination"),show="headings",selectmode="extended",height=3)
    columns=[("provider","网盘",90),("status","状态",140),("progress","进度",70),
             ("name","文件",255),("destination","云端路径",400)]
    for key,title,width in columns:
        tree.heading(key,text=title)
        tree.column(key,width=width,minwidth=60,stretch=key in ("name","destination"))
    tree.pack(fill="both",expand=True)
    tree.tag_configure("complete",foreground="#257044")
    tree.tag_configure("failed",foreground="#b83b3b")
    tree.tag_configure("conflict",foreground="#a96c12")
    tree.tag_configure("awaiting_login",foreground="#a96c12")
    action = ttk.Frame(main)
    action.pack(fill="x",pady=10)
    def run_uploads():
        nonlocal worker,worker_thread
        if closing:
            return
        if worker_thread and worker_thread.is_alive():
            tip.set("队列已在运行。")
            return
        for task in queue.list():
            if task["status"] == "awaiting_login":
                queue.retry(task["id"])
        worker = Worker(queue,home)
        def work():
            try:
                worker.run()
                mailbox.put(("tip","本轮处理结束，请查看任务状态。"))
            except Exception as exc:
                mailbox.put(("error",redact(exc)))
        worker_thread = threading.Thread(target=work,daemon=False)
        worker_thread.start()
        tip.set("正在处理队列；完成状态会核对云端文件大小，不回下载。")
    def pause():
        if worker:
            worker.stop.set()
        tip.set("正在暂停，当前任务稍后可恢复。")
    def cancel():
        for item in tree.selection():
            queue.cancel(int(item))
    def retry():
        for item in tree.selection():
            queue.retry(int(item))
        tip.set("所选任务已重新排队，点击开始 / 恢复上传。")
    def refresh_accounts():
        tip.set("正在检查登录状态……")
        def job():
            result = {}
            for code in PROVIDERS:
                try:
                    result[code] = "已登录" if Backend(code,home).is_logged_in() else "需要登录"
                except Exception:
                    result[code] = "检查失败，可重试"
            mailbox.put(("accounts",result))
        threading.Thread(target=job,daemon=True).start()
    ttk.Button(action,text="开始 / 恢复上传",style="Primary.TButton",command=run_uploads).pack(side="left")
    ttk.Button(action,text="暂停",command=pause).pack(side="left",padx=8)
    ttk.Button(action,text="取消所选",command=cancel).pack(side="left")
    ttk.Button(action,text="重新排队",command=retry).pack(side="left",padx=8)
    ttk.Button(action,text="刷新账号",command=refresh_accounts).pack(side="right")

    detail = tk.Text(main,height=5,font=("Microsoft YaHei UI",9),relief="flat",
                     background="white",foreground="#465571",wrap="word",padx=10,pady=8)
    detail.pack(fill="x")
    ttk.Label(main,textvariable=tip,foreground="#2866cf").pack(anchor="w",pady=(8,3))
    ttk.Label(main,text="默认快速上传：上传后核对云端字节数，不回下载。阿里支持引擎续传；百度失败时重传当前文件。",
              foreground="#66758c",font=("Microsoft YaHei UI",9)).pack(anchor="w")
    last_detail = ""
    last_login_stamp = {}
    def refresh():
        nonlocal last_detail,last_login_stamp
        if closing:
            return
        while True:
            try:
                kind,value=mailbox.get_nowait()
            except messages.Empty:
                break
            if kind=="tray_show":
                tray.show()
            elif kind=="tray_exit":
                close()
            elif kind=="accounts":
                for code,state in value.items():
                    account[code].set(state)
                tip.set("账号状态已刷新。")
            elif kind=="error":
                tip.set(value)
                messagebox.showerror("操作未完成",value,parent=root)
            else:
                tip.set(value)
        for code in PROVIDERS:
            login_result = home / (code + "_login_result.json")
            try:
                stamp = login_result.stat().st_mtime_ns
                if stamp != last_login_stamp.get(code):
                    last_login_stamp[code] = stamp
                    result = json.loads(login_result.read_text(encoding="utf-8"))
                    if result.get("state") == "done":
                        refresh_accounts()
                    elif result.get("state") in ("waiting","checking","error"):
                        tip.set(result.get("message",""))
            except (OSError,ValueError):
                pass
        rows = queue.list()
        for task in rows:
            values=(PROVIDERS[task["provider"]],("已上传·大小已核对" if task["status"]=="complete" and task.get("verification")=="quick" else STATUS_LABELS[task["status"]]),
                    f'{task["progress"]:.0f}%',Path(task["local_path"]).name,task["remote_path"])
            key=str(task["id"])
            if tree.exists(key):
                tree.item(key,values=values,tags=(task["status"],))
            else:
                tree.insert("",0,iid=key,values=values,tags=(task["status"],))
        chosen=tree.selection()
        if chosen:
            task=queue.get(int(chosen[0]))
            lines=[task["message"],"本地文件  "+task["local_path"],
                   "SHA256  "+task["sha256"]]
            lines += [time.strftime("%H:%M:%S",time.localtime(e["stamp"]))+"  "+e["message"]
                      for e in queue.events(task["id"])[-4:]]
            content="\n".join(lines)
        else:
            content="选择任务查看详情。\n登录信息保存在本机专用目录，应用日志已脱敏。"
        if content!=last_detail:
            detail.configure(state="normal")
            detail.delete("1.0","end");detail.insert("1.0",content)
            detail.configure(state="disabled")
            last_detail=content
        root.after(800,refresh)
    def close():
        nonlocal closing
        if closing:
            return
        if worker_thread and worker_thread.is_alive():
            if not messagebox.askyesno("退出上传助手","当前任务仍在运行。退出会暂停本窗口发起的上传，是否退出？",parent=root):
                return
        closing=True
        owned_logins.request_stop()
        if worker:
            worker.stop.set()
        def wait_close():
            if (worker_thread and worker_thread.is_alive()) or owned_logins.running():
                root.after(150,wait_close)
            else:
                tray.stop()
                root.destroy()
        wait_close()
    from tray_support import TrayController
    tray = TrayController(root,
                          lambda: mailbox.put(("tray_show",None)),
                          lambda: mailbox.put(("tray_exit",None)))
    try:
        tray.start()
    except RuntimeError as exc:
        tip.set(str(exc))
    def hide_window():
        if tray.hide():
            tip.set("已隐藏到系统托盘，上传继续运行；点击托盘图标可恢复。")
        else:
            tip.set("系统托盘不可用，窗口保持显示；可使用退出程序按钮。")
    root.protocol("WM_DELETE_WINDOW",hide_window)
    ttk.Button(action,text="退出程序",command=close).pack(side="right",padx=8)
    refresh()
    root.after(150,refresh_accounts)
    root.mainloop()

def main():
    parser=argparse.ArgumentParser(description="本地双网盘上传助手")
    sub=parser.add_subparsers(dest="action")
    sub.add_parser("gui")
    add=sub.add_parser("add",help="建立文件/目录上传快照")
    add.add_argument("--provider",choices=PROVIDERS,required=True)
    add.add_argument("--remote",required=True)
    add.add_argument("--start",action="store_true")
    add.add_argument("--verification",choices=("quick","full"),default="quick",help="默认快速核对云端大小；full 为高级回下载模式")
    add.add_argument("paths",nargs="+")
    sub.add_parser("run",help="处理全部待上传任务，完成后返回 JSON")
    sub.add_parser("tasks",help="JSON 任务列表")
    sub.add_parser("status",help="检查两个网盘登录状态")
    login=sub.add_parser("login",help="打开独立登录窗口")
    login.add_argument("provider",choices=PROVIDERS)
    login.add_argument("--interactive",action="store_true")
    login.add_argument("--qr",action="store_true")
    for name in ("retry","cancel","logs"):
        p=sub.add_parser(name)
        p.add_argument("id",type=int)
    args=parser.parse_args()
    home=state_home()
    secure_state(home)
    queue=Queue(home/"tasks.db")
    if args.action in (None,"gui"):
        gui(home)
        return 0
    if args.action=="login":
        if args.qr:
            if args.provider == "ali":
                from ali_qr import login as qr_login
            else:
                from baidu_qr import login as qr_login
            return qr_login(home)
        if args.interactive:
            return interactive_login(args.provider,home)
        launch_login(args.provider)
        result={"status":"waiting_for_user","provider":args.provider}
    elif args.action=="add":
        ids=queue.enqueue(args.provider,args.paths,args.remote,verification=args.verification)
        if args.start:
            launch_worker()
        result={"task_ids":ids,"worker_started":args.start}
    elif args.action=="run":
        Worker(queue,home).run()
        tasks=queue.list()
        result={"tasks":tasks}
        print(json.dumps(result,ensure_ascii=False))
        return 0 if all(t["status"] in ("complete","cancelled") for t in tasks) else 2
    elif args.action=="tasks":
        result=queue.list()
    elif args.action=="status":
        result={}
        for provider in PROVIDERS:
            try:
                result[provider]={"logged_in":Backend(provider,home).is_logged_in()}
            except Exception as exc:
                result[provider]={"logged_in":False,"error":redact(exc)}
    elif args.action=="retry":
        queue.retry(args.id)
        result=queue.get(args.id)
    elif args.action=="cancel":
        queue.cancel(args.id)
        result=queue.get(args.id)
    else:
        result=queue.events(args.id)
    print(json.dumps(result,ensure_ascii=False))
    return 0

if __name__=="__main__":
    try:
        raise SystemExit(main())
    except (ValueError,RuntimeError,OSError) as exc:
        print(json.dumps({"error":redact(exc)},ensure_ascii=False),file=sys.stderr)
        if "--interactive" in sys.argv and sys.stdin and sys.stdin.isatty():
            input("操作未完成，按回车关闭窗口。")
        raise SystemExit(2)
