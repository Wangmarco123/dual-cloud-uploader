# 命令行与账号说明

## 工作目录

在完整便携版根目录执行以下 PowerShell 命令。源码开发环境可把 `$python` 改成自己的虚拟环境 Python，先按开发说明准备两套 EXE。

```powershell
$python = '.\runtime\python.exe'
$app = '.\cloud_uploader.py'
& $python $app status
& $python $app tasks
```

## 登录与目录

```powershell
& $python $app login ali
& $python $app login baidu
```

扫码应由账号持有人在独立窗口完成。阿里授权回调使用 `api.tickstep.com`，请核对授权页面与权限。百度助手与普通浏览器的登录状态独立。不能将密码、Cookie、Token 或账号配置贴到聊天、Issue 或 Git 提交中。

`status` 确认引擎登录状态。判断本次阿里扫码接续还须结合本次登录结果，不能只用历史账号的 `status=true`。

目标路径使用以 `/` 开头的绝对云端路径，例如 `/我的作品/示例项目`；不要使用 `..`、通配符或反斜杠。阿里上传遵循当前引擎工作盘，备份盘与资源库可能存在同名目录。

## 添加、执行、核对

```powershell
& $python $app add --provider ali --remote '/我的作品/示例项目' '.\示例文件.txt'
& $python $app add --provider baidu --remote '/我的作品' '.\示例文件夹'
& $python $app run
& $python $app tasks
```

保存返回的 `task_ids`。文件夹会展开为多个逐文件任务，保留所选文件夹名称；空目录不单独上传。源文件添加时记录大小和摘要，文件变更后取消旧任务并重新添加。

`run` 会处理当前数据目录里的全部 pending 任务。先检查队列，避免执行未授权的其他任务。它是阻塞命令，后台进程启动不等于上传完成。

本次所有任务均 `complete`、进度 100%、`verification=quick`，且结果显示“云端字节数一致（未回下载）”，才能确认快速上传完成。`remote_path` 是文件路径，不是分享链接。

## 失败与恢复

```powershell
# 将下面的 1 替换成实际任务 ID。
& $python $app logs 1
& $python $app retry 1
& $python $app run
& $python $app cancel 1
```

等待登录的任务在授权后需要重新排队。先看日志再有限重试；同名冲突使用新目录或新名称，不自动覆盖。取消任务不会删除已上传到云端的文件。

不要编辑 SQLite、删除 worker.lock 或结束其他任务的进程来强行解锁。等待合法占用结束。

## 核验模式

| 模式 | 核验范围 | 额外成本 |
|---|---|---|
| quick（默认） | 云端路径与精确字节数；阿里比较可用服务端 SHA1 | 不回下载整文件 |
| full（按需） | 回下载后计算 SHA256 | 下载流量与临时磁盘空间 |

完整模式可在添加时显式指定 `--verification full`。既有任务保存原模式，不会自动降级为 quick；需要更换模式时取消旧活动任务后重新添加。

## 账号数据

默认本机数据目录：`%LOCALAPPDATA%\DualCloudUploader`。`DUALCLOUD_HOME` 可指定另一个独立目录，但不同目录不自动共享账号。

账号目录、百度 WebView2 用户目录、tasks.db、events、worker.lock 和验证临时文件均不属于发布内容。程序设置本机目录访问权限，并未宣称凭据已加密保存。
