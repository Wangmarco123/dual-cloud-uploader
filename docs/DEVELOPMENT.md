# 开发与验证

## 环境

应用支持 Windows 10/11 x64。R06 使用 Python 3.12.13；WebView2 Runtime 与 .NET Framework 4.7.2+ 用于独立扫码窗口。运行环境版本记录见 [runtime-versions.json](runtime-versions.json)。

在仓库根目录建立 Python 3.12 虚拟环境：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

requirements.txt 固定直接依赖版本；发行版的传递依赖版本见运行环境记录。依赖安装不会自动下载网盘引擎。

## 准备引擎

从本仓库 R06 Release 下载便携 ZIP 并完整解压，将其中两套 EXE 放到源码树对应位置：

```text
bin/ali/aliyunpan.exe
bin/baidu/BaiduPCS-Go.exe
```

这些文件被 .gitignore 排除。阿里为上游 v0.4.0；百度必须是本项目地址回退修复构建，不能用上游原版冒充修复版。bin 下的 release.json 是原上游 ZIP 记录；修复 EXE 摘要见 bin/baidu/local_patch.json。

要自行构建百度引擎，在安装 Go 1.24.1 后执行：

```powershell
Push-Location .\third_party\baidupcs-go
try {
    go test ./requester -run '^TestDialContextFallsBack' -count=1
    if ($LASTEXITCODE -ne 0) { throw 'Go regression failed' }
    go build -trimpath -o ..\..\bin\baidu\BaiduPCS-Go.exe .
    if ($LASTEXITCODE -ne 0) { throw 'Go build failed' }
} finally {
    Pop-Location
}
```

构建需要获取 go.mod/go.sum 声明的依赖，不保证离线构建。重编结果受工具链与构建参数影响；记录新 EXE 摘要，不要把历史摘要自动当成本次构建的证明。源码中的新增测试是本地回环 TCP 测试，不调用网盘。

## 启动与回归

先准备两套 EXE，再运行：

```powershell
.\.venv\Scripts\python.exe cloud_uploader.py gui
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

48 项测试使用临时数据与模拟接口，不需要真实登录，也不上传真实文件。部分测试创建 Backend 时检查 EXE 是否存在，因此源码测试前仍要准备引擎。

发布包自带 Python 是隔离环境，禁止生成缓存时应显式使用 `python.exe -B`，不能只依赖 PYTHONDONTWRITEBYTECODE 环境变量。

源码树不包含便携发行版的全文件摘要清单；check_runtime.py 在源码树主要检查依赖和引擎，在完整便携版还会核对交付清单。不要把源码环境检查当成已验证整个发行包。

## 仓库与发行包

Git 跟踪应用源码、测试、文档、百度修复源码及许可。runtime、EXE、账号和生成的压缩包不进入 Git。

R06 便携 ZIP、外置操作交接和 SHA256 清单放在 GitHub Release。该 ZIP 与已完成网盘验证的 R06 文件保持同一字节内容。GitHub 自动生成的 Source code ZIP 只包含仓库跟踪文件，不是可直接启动的便携版。
