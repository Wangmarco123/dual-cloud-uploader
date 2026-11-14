# 百度地址回退修复

## 故障与证据

本机目录列表可读取，但创建目录及上传预处理请求访问 pcs.baidu.com 时，缓存 IPv6 地址的 TCP 连接报 Windows socket access permissions 错误。原引擎将 DNS 的首个地址缓存后直接连接，失败后不尝试其他地址。

## 修改

基于上游 [qjfoidnh/BaiduPCS-Go v4.0.2](https://github.com/qjfoidnh/BaiduPCS-Go/tree/v4.0.2)，提交 `225bdd3b6cb298601c4d5ef7104c3e08cd1d692d`。

本地修改保存在 `third_party/baidupcs-go/requester/dial.go`，新增测试在同目录 `dial_fallback_test.go`；对上游差异另存 [补丁](../patches/baidupcs-address-fallback.patch)。文件中的缓存连接与原主机名回退块为本地维护改动，不是上游新发布版本。

1. 先使用有超时、遵从 context 的标准 Dialer 连接缓存 IP。
2. 缓存连接失败后，再以原始主机名调用标准 DialContext，让标准库尝试其他地址并进行 IPv4/IPv6 回退。

没有改系统 DNS、hosts、防火墙或 IPv6 设置，没有放宽 TLS 证书校验，也没有改成覆盖同名文件。单次缓存连接超时仍可能增加等待时间。

## 验证与边界

新增单测将 localhost 的缓存地址设为不可达的 127.0.0.2，验证它能回退到实际监听的回环服务；修改前失败，修改后通过。这不是完整的真实 IPv6 网络测试。

修复后，本机 106 字节、103 字节和 324,000 字节百度测试文件完成快速核对；R06 约 41.7 MiB 发行包也已完成百度与阿里上传的云端精确字节数核对。这些任务没有执行回下载内容核验。

其他电脑、其他网络、持续传输及大文件性能尚未验收。
