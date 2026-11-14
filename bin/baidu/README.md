# 百度引擎

运行时将 BaiduPCS-Go.exe 放在本目录。使用本项目 R06 修复构建，可从便携 Release 取得或按开发说明从源码构建。

上游：https://github.com/qjfoidnh/BaiduPCS-Go ，基线 v4.0.2。
release.json 是原上游发布 ZIP 的来源记录；local_patch.json 记录本地修复构建和 EXE 摘要，两者对应不同工件。

修复源码位于 ../../third_party/baidupcs-go，补丁位于 ../../patches/baidupcs-address-fallback.patch。原上游源码许可与本目录 LICENSE 均予保留。EXE 不进入 Git 历史。
