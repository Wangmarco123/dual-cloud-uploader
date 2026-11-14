"""Read exact remote bytes without downloading content."""
import re
from pathlib import PurePosixPath

def parse_metadata(provider, text, remote):
    lines = text.splitlines()
    if provider == "ali":
        paths = re.findall(r"^\s*当前目录:\s*(.*?)\s*$", text, re.M)
        if paths != [remote] or "文件大小(原始)" not in text or "文件SHA1" not in text:
            raise RuntimeError("未取得准确的云端文件信息")
        rows = []
        for line in lines:
            fields = re.split(r"\s{2,}", line.strip(), maxsplit=7)
            if len(fields) == 8 and fields[0].isdigit() and fields[7] == PurePosixPath(remote).name:
                if not fields[4].isdigit() or not re.fullmatch(r"[a-fA-F0-9]{40}", fields[3]):
                    raise RuntimeError("云端信息缺少原始字节数或文件标识")
                rows.append({"size":int(fields[4]),"sha1":fields[3].lower()})
        if len(rows) == 1:
            return rows[0]
    elif provider == "baidu":
        def values(label):
            return re.findall(r"^\s*"+re.escape(label)+r"\s+(.+?)\s*$",text,re.M)
        sizes=values("文件大小")
        if values("类型") == ["文件"] and values("文件路径") == [remote] and len(sizes) == 1:
            size=re.fullmatch(r"(\d+)(?:,\s*.+)?",sizes[0])
            if size:
                # Baidu labels this MD5 potentially unreliable; never use it as evidence.
                return {"size":int(size.group(1))}
    raise RuntimeError("未取得唯一文件的准确云端字节数，不能确认上传完成")
