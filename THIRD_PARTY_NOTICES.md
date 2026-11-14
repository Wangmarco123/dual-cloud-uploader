# 第三方组件说明

本文件说明实际使用的第三方来源，不把整个项目统一声明为某个上游许可证。上传助手原创部分的授权状态见根目录 LICENSE。

## 仓库包含的第三方源码

| 组件 | 版本 / 来源 | 许可及修改记录 |
|---|---|---|
| BaiduPCS-Go | [v4.0.2](https://github.com/qjfoidnh/BaiduPCS-Go/tree/v4.0.2)，提交 225bdd3b6cb298601c4d5ef7104c3e08cd1d692d | [Apache-2.0 原文](third_party/baidupcs-go/LICENSE)；保留上游源码、go.mod 和 go.sum |

本地维护修改位于 requester/dial.go：缓存地址连接失败后按原主机名回退。新增 requester/dial_fallback_test.go。差异见 [补丁](patches/baidupcs-address-fallback.patch)，构建与验证说明见 docs/BAIDU_FIX.md。这不是上游新版本。

## 运行时引擎

- aliyunpan v0.4.0：[上游](https://github.com/tickstep/aliyunpan/tree/v0.4.0)，[Apache-2.0](bin/ali/LICENSE)。Git 不跟踪 EXE，版本和原上游 ZIP 摘要见 bin/ali/release.json。
- 百度本地修复 EXE：记录见 bin/baidu/local_patch.json。bin/baidu/release.json 的摘要是原上游 ZIP，不能当成修复 EXE 摘要。
- Go 编译依赖以第三方源码中的 go.mod/go.sum 为准，各模块仍保留各自许可，不由引擎的 Apache-2.0 一概覆盖。

## Python 依赖与便携运行环境

Git 源码不包含 Python 运行库或安装好的依赖；requirements.txt 固定直接依赖，完整版本快照在 docs/runtime-versions.json。便携 Release 内保留原有 runtime/LICENSE.txt 与各 .dist-info 许可；本仓库 licenses/ 另保存从 R06 环境提取的许可文本副本，清单见 docs/dependency-license-inventory.json。

| 组件 | 版本 | 许可信息 / 来源 |
|---|---|---|
| Python | 3.12.13 | [PSF 与相关内嵌组件条款](licenses/Python-3.12-LICENSE.txt)；[官方许可](https://docs.python.org/3.12/license.html) |
| pywebview | 6.1 | BSD-3-Clause；[上游](https://github.com/r0x0r/pywebview) |
| pystray | 0.19.5 | LGPLv3；[上游源码与条款](https://github.com/moses-palmer/pystray/tree/v0.19.5)；本地副本保留 COPYING 与 COPYING.LGPL |
| Pillow | 12.3.0 | MIT-CMU 及图像库相关许可；[上游](https://github.com/python-pillow/Pillow)；保留完整许可副本 |
| pythonnet / clr_loader / bottle / six | 见版本快照 | 各自安装包附带的许可文本 |
| cffi / pycparser / typing_extensions | 见版本快照 | 各自安装包附带的许可文本 |
| proxy_tools | 0.1.0 | 安装元数据标 MIT，官方仓库 LICENSE.txt 列 BSD 两条款；存在元数据差异，不能把所有组件统一写成 MIT |

pystray 在运行时以独立 Python 模块导入，便携包附有其 .py 文件及 LGPL/GPL 文本。需要检查或替换该库时，应在解压副本的 runtime/Lib/site-packages/pystray 中操作，并保留原副本；源码开发方式也允许在自己的虚拟环境安装修改后的库。本项目的应用许可声明不限制第三方许可授予的权利，包括调试库修改所必需且获其许可允许的行为。修改后能否在特定电脑正常运行需另行验证。

pywebview 附带的 Microsoft WebView2 SDK DLL 仍受微软相应条款约束，不能归入 pywebview 的 BSD 条款；系统 WebView2 Runtime 也与 SDK 文件不同。参考 [微软分发说明](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution)。

本仓库及 R06 Release 公开提供访问，现有组件许可副本予以保留。公开可访问不改变各组件的许可条款；后续打包与再分发应按实际依赖、原生 DLL 和对应版本复核完整条款。此来源清单不代表已经完成全面的再分发许可审查。
