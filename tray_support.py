"""System tray lifecycle. Tray callbacks are marshalled into the Tk mailbox."""
import threading

def make_icon(on_show,on_exit):
    import pystray
    from PIL import Image,ImageDraw
    image=Image.new("RGBA",(64,64),(0,0,0,0))
    draw=ImageDraw.Draw(image)
    draw.rounded_rectangle((3,3,61,61),radius=15,fill="#2866cf")
    draw.ellipse((12,26,34,47),fill="white")
    draw.ellipse((22,16,47,45),fill="white")
    draw.ellipse((36,28,54,47),fill="white")
    draw.rectangle((22,32,45,47),fill="white")
    draw.polygon([(32,23),(23,33),(28,33),(28,43),(36,43),(36,33),(41,33)],fill="#2866cf")
    return pystray.Icon(
        "DualCloudUploader",image,"双网盘上传助手",
        menu=pystray.Menu(
            pystray.MenuItem("显示窗口",lambda *_:on_show(),default=True),
            pystray.MenuItem("退出程序",lambda *_:on_exit())))

class TrayController:
    def __init__(self,root,on_show,on_exit,icon_factory=make_icon):
        self.root=root
        self.on_show=on_show
        self.on_exit=on_exit
        self.icon_factory=icon_factory
        self.icon=None
        self.ready=threading.Event()

    def start(self):
        try:
            self.icon=self.icon_factory(self.on_show,self.on_exit)
            def setup(icon):
                icon.visible=True
                self.ready.set()
            self.icon.run_detached(setup=setup)
            if not self.ready.wait(5):
                raise RuntimeError("系统托盘尚未就绪")
        except Exception:
            self.stop()
            raise RuntimeError("系统托盘启动失败，窗口保持显示")

    def hide(self):
        if not self.ready.is_set():
            return False
        self.root.withdraw()
        return True

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def stop(self):
        self.ready.clear()
        if self.icon:
            self.icon.stop()
            self.icon=None
