"""Read-only local prerequisites and delivery-file integrity check."""
import hashlib
import importlib.metadata
import json
import os
import struct
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent

def main():
    result={"platform":sys.platform,"bits":struct.calcsize("P")*8,
            "python":sys.version.split()[0],"root":str(ROOT),"checks":{}}
    checks=result["checks"]
    try:
        import tkinter
        checks["tkinter"]=tkinter.Tcl().eval("info patchlevel")
        import pystray
        from PIL import Image
        checks["pystray"]=importlib.metadata.version("pystray")
        checks["pillow"]=importlib.metadata.version("pillow")
        import webview
        import clr
        import System
        checks["pywebview"]=importlib.metadata.version("pywebview")
        checks["dotnet"]=str(System.Environment.Version)
    except Exception as exc:
        checks["runtime_error"]=type(exc).__name__
    for provider,name in (("ali","aliyunpan.exe"),("baidu","BaiduPCS-Go.exe")):
        checks[provider+"_engine"]=(ROOT/"bin"/provider/name).is_file()
    candidates=[Path(os.environ.get(key,"C:/"))/"Microsoft"/"EdgeWebView"/"Application"
                for key in ("ProgramFiles(x86)","ProgramFiles","LOCALAPPDATA")]
    checks["webview2_common_path_detected"]=any(p.is_dir() for p in candidates)
    manifest=ROOT/"交付文件SHA256.json"
    errors=[]
    if manifest.exists():
        entries=json.loads(manifest.read_text(encoding="utf-8"))
        for name,expected in entries.items():
            file=(ROOT/name).resolve()
            if not file.is_relative_to(ROOT) or not file.is_file():
                errors.append(name)
                continue
            with file.open("rb") as stream:
                digest=hashlib.file_digest(stream,"sha256").hexdigest()
            if digest!=expected:
                errors.append(name)
        checks["integrity_files"]=len(entries)
        checks["integrity_errors"]=errors
    else:
        checks["integrity_manifest"]="not generated yet"
    good=(sys.platform=="win32" and result["bits"]==64 and "runtime_error" not in checks
          and checks["ali_engine"] and checks["baidu_engine"] and not errors)
    result["ok"]=good
    print(json.dumps(result,ensure_ascii=False))
    return 0 if good else 2

if __name__=="__main__":
    raise SystemExit(main())
