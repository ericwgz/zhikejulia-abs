# AGIDock 部署交接

## 当前生产环境

| 项目 | 值 |
|---|---|
| GitHub | `https://github.com/ericwgz/zhikejulia-abs`，公开仓库 |
| 网站 | `https://zhikejulia.com/`，`https://www.zhikejulia.com/` |
| 兼容入口 | `https://badrams.com/abs/` |
| 云 API | `https://api.agidock.cloud` |
| VM | `vm_01M0Y6RAHR22AGRK1TSYDQV1XJ` / `badrams-web` |
| SSH | `ubuntu@155.103.253.33`，TCP 22 |
| 源站入口 | Nginx 443；Cloudflare Proxied / Full (strict) |
| 应用 | systemd `abs-api`，监听 `127.0.0.1:8096` |
| API 发布目录 | `/opt/badrams/abs-api/releases/`，`current` 指向在用版本 |
| 前端目录 | `/opt/badrams/current/app/static/abs/` |
| 环境文件 | `/etc/badrams/abs-api.env`，root 0600 |
| 持久数据 | `/srv/badrams-data/abs-api/`：`work.sqlite3`、`usage.sqlite3`、`stress.sqlite3` |
| 数据存储 | 40 GB 系统盘 `/dev/sda1`；2026-09-08 已迁回，原 500 GB `badrams-data` 卷已删除 |
| 回滚备份 | `/opt/badrams/abs-backups/<release>/` |

数据库仍使用原有路径。`/srv/badrams-data/` 现在是系统盘上的普通目录，
PostgreSQL 的 `/var/lib/postgresql` 仍绑定到其中的 `postgresql/` 子目录。
不要重新添加旧数据盘 UUID 的挂载配置；系统盘会随 VM 删除而丢失，删除或重建
VM 前必须另行备份数据。定时备份服务已改为依赖数据路径，不依赖旧数据盘挂载单元。
迁移前的 PostgreSQL 逻辑备份、全部数据冷备和配置副本已保存到项目所有者的本机，
并在服务器 `/root/badrams-storage-migration-20260908-r2/` 保留一份。
旧云快照 `pre-cutover-20260826` 未删除，其中记录的是迁移前的磁盘布局，不能直接
作为当前磁盘布局的回滚入口；它是独立计费资源。

## 三类权限

1. **GitHub 协作者权限**：接受写权限邀请后，可向原仓库推送改动和合并 PR。
   公开源码可直接查看和克隆；公开可见性本身不授予他人直接推送权限。
2. **部署 SSH 私钥 `abs_deploy`**：仅允许 `status` 和 `deploy <Git SHA>`，由
   服务器固定入口验证并发布 ABS。SSH 本身不提供通用 shell、PTY 或端口转发。
   获准发布的应用代码会以 `badrams` 服务用户运行，因此部署权限应交给可信同事。
3. **AGIDock Write API Key**：用于云平台资源管理。它不能代替 SSH 部署。
   AGIDock 当前不支持把 write key 限定到某一台 VM；该密钥可写整个账户资源。
   日常应用发布只需前两类权限，不需调用云资源 API。

凭据由项目所有者单独提供。不要把任何凭据写入代码、issue、PR、提交信息或日志。
`deploy/known_hosts` 是已核实的服务器公钥，用于检测主机身份变化，不是私钥。

## 同事 Agent 的操作步骤

```bash
git clone https://github.com/ericwgz/zhikejulia-abs.git
cd zhikejulia-abs
git checkout -b feature/your-change
# 修改代码
python -m unittest discover -s tests -p "test_*.py"
npm ci
npm test
git add <changed-files>
git commit -m "Describe the resulting behavior"
git push -u origin feature/your-change
# 在 GitHub 合并 PR 后
git checkout main
git pull --ff-only
python scripts/deploy.py --key /path/to/abs_deploy --status
python scripts/deploy.py --key /path/to/abs_deploy
```

Windows 的私钥路径可以写成 `C:/Users/you/.ssh/abs_deploy`。macOS/Linux 下先
`chmod 600 /path/to/abs_deploy`。本地开发用 `python scripts/dev.py`。

部署脚本从当前 Git commit 打包 `app/*.py` 和 `app/static/abs/` 的受支持静态
文件；环境变量、数据库、配置和脚本本身均不覆盖服务器。当前归档限制 15MB、
200 个文件；仅接收普通文件，不接收符号链接。部署时 ABS 服务会短暂重启。

确认网页、`/api/abs/health`、`/api/abs/status` 正常；改动 AI 时，用合成产品进行
一次实际对话验证。`configured: true` 只说明密钥存在，不保证上游调用成功。
涉及工单时使用独立演示团队验证分派、通知、处理和复核，不修改真实团队数据。
涉及压力测试时验证CSV/XLSX上传、24项计算、情景守恒与真实千问报告；使用独立
合成数据团队。Nginx的 `/api/abs/work/stress/` 须单独允许1MB请求，其他接口保持
原限制。该配置在zhikejulia和badrams两个域名入口都需保留，普通代码部署不覆盖它。

## AGIDock API

官方文档：<https://agidock.cloud/docs/api.md>；
完整接口：<https://agidock.cloud/openapi.json>。
鉴权方式：`Authorization: Bearer <AGIDOCK_API_KEY>`。
读取 VM 状态用 `GET /v1/vms/vm_01M0Y6RAHR22AGRK1TSYDQV1XJ`。
写操作按文档提供唯一 `Idempotency-Key`。账户 write key 不支持服务器命令执行。

不要为了部署代码新建/重启/删除 VM、变更 DNS 或卸载持久卷。
服务器的模型配置和 SQLite 数据是持续运行状态，不能用仓库中的示例文件覆盖。

## 项目所有者维护

`deploy/ssh-gateway.py` 是服务器强制命令的参考源。首次安装由所有者用管理 SSH
连接完成，固定为 root 拥有的 `/usr/local/sbin/abs-deploy-gateway.py`。
同事的部署上传不会更新该文件；部署入口升级需要所有者单独审核和安装。
修改 Nginx、systemd 或模型配置同样需要所有者维护连接。

每次发布将旧静态目录和前一个 API 软链接写入备份。自动健康检查失败会恢复它们。
上线后发现业务问题时，由所有者从对应备份恢复，再重启 `abs-api`；恢复代码时
不要回退 `work.sqlite3`，除非单独制定并确认数据恢复方案。
