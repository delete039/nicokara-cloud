# v4.3 上传与发布路径恢复

## 已定位的故障

线上同名部署包重复执行时，旧脚本在获得部署锁之前移动发布目录，并重新创建了空目录。仍在运行的 Node/Python 进程保留旧的绝对文件路径，导致大体积 JavaScript 静态文件 GET 返回 502、任务页面空白，以及 HTTPX 创建 TLS 上下文时找不到 certifi 证书。

另一路上传故障与慢速网络有关：8 MiB 分片配合 120 秒固定请求超时，会反复中断首片。服务器本机接收 8 MiB 请求体仅数十毫秒，公网传输则明显更慢；这些证据不足以将取消请求归因于 Cloudflare 单独一层。

## 修复行为

- 新会话申请 512 KiB 分片，既有会话返回原分片尺寸、总数和缺失序号；客户端按服务器返回的边界续传。文件名、文件大小及提交 ID 仍校验一致性。
- 请求在 120 秒无新增上传字节后中止；传输完成后最多再等待 120 秒响应；每次请求绝对上限 15 分钟。失败最多尝试三次，暂停会清理定时器。
- 快速成功分片继续不写高频请求日志；失败及超过 30 秒的请求在默认级别保留 request_id、会话、分片序号、Content-Length 和耗时。日志写入移到线程池。
- 发布目录和备份目录不可变。升级先获取部署锁，再读取 current、检查目标及创建目录；已有目录直接退出。历史首次安装脚本拒绝覆盖已有安装。
- 新版本先校验 TLS 上下文；切换后对所有 JavaScript 资源执行 GET 并比对文件哈希，失败自动切回旧版本。

## 排查与回滚

先比较 `readlink -f /data/nicokara/current`、systemd MainPID 对应的 `/proc/PID/cwd` 和磁盘发布目录。不要对仍有运行进程引用的目录改名或原地覆盖。若 current 目标为空且旧目录完整，须取得部署锁、记录原始路径及哈希、验证文件完整性，再恢复原路径；恢复后验证真实静态资源 GET、后端健康状态和 HTTPX TLS 初始化。

常规版本回滚使用本次部署记录中的旧发布目录，先等待活动任务结束，再停止前后端、原子切换 current 并重启。数据库不倒退，模型、上传文件和用户任务不删除。部署备份包含原配置、systemd 配置和 SQLite 快照。

诊断接口使用管理员 Bearer 鉴权；凭据仅由调用环境提供，不写入源码、日志或报告。可通过 `/api/v1/admin/logs` 的 request_id/reference_id 定位上传请求，通过 `/api/v1/admin/jobs/{id}/timeline` 追踪任务后续处理。

## 验证入口

```bash
python release/check_version.py
cd backend
python -m pytest -q
cd ../frontend
npm ci --registry=https://registry.npmjs.org
npm test
npm run build
cd ..
python release/package_release.py
```

打包前提交已验证源码；打包器从 HEAD 读取文件，并生成逐文件及整包 SHA-256。发布后还应通过公网完成真实多分片上传、断点续传和任务页访问，不能只检查首页或 HEAD 请求。
