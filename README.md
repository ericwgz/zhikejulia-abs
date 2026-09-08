# 栀可 Julia · ABS Lens

消费金融 ABS 信用质量演示工作台。线上入口：<https://zhikejulia.com/>。

六只合成产品按地域和客群分类，提供四维信用评分、红黄绿信号、固定报告、
基于报告的通义千问对话，以及 AI 异常建单、负责人分派、站内抄送和领导复核。
所有产品和贷款指标均为演示数据。

新增 `/#/stress` 压力测试工作台：上传CSV/XLSX资产池日度汇总，计算24项监控指标、
信用分数与灯色，运行基准及四类3/6/12月压力情景，生成带证据的千问结构化报告。
提供3只合成ABS的180天样本、合约DOCX/TXT阈值提取、报告与现金流导出。
上传数据与现有固定演示产品分开保存。字段、公式和模型边界见 [STRESS_TESTING.md](STRESS_TESTING.md)。

## 本地运行

需要 Python 3.10+。运行服务不需要安装第三方 Python 或 npm 包：

```bash
git clone https://github.com/ericwgz/zhikejulia-abs.git
cd zhikejulia-abs
python scripts/dev.py
```

打开 <http://127.0.0.1:4317/>。Windows 也可使用 `py -3 scripts/dev.py`。
工单数据写入 `.local-data/`。要使用自己的千问 API，将 `.env.example` 复制为
`.env` 后填写 `ABS_LLM_API_KEY`。未配置时评分、报告、团队和人工工单可用，
AI 显示未配置状态。线上密钥保存在服务器，部署时继续沿用。

## 检查与测试

Python 测试使用临时数据库及模拟模型，不会发邮件或调用真实大模型：

```bash
python -m unittest discover -s tests -p "test_*.py"
node tests/test_scoring.cjs
```

前端 DOM 回归需要 Node.js 20+ 和开发依赖：

```bash
npm ci
npm test
```

修改数据生成逻辑后执行 `node scripts/build-abs-catalog.cjs`，审核生成的
`catalog.json` 并一起提交。报告快照是工单和模型上下文的依据，发布新一期时
应更新快照版本，不可默默重写既有工单证据。

## 同事协作与发布

接受 GitHub 协作邀请后可以推送分支和创建 Pull Request。建议先在分支修改、
运行测试，合并 `main` 后部署。仓库中的 GitHub Actions 只运行检查，不自动发布。

取得项目所有者提供的 `abs_deploy` 私钥文件后：

```bash
git pull --ff-only
npm ci
python scripts/deploy.py --key /path/to/abs_deploy --status
python scripts/deploy.py --key /path/to/abs_deploy
```

发布脚本要求工作区干净，运行后端及评分测试，然后上传当前提交的运行文件。
服务端验证归档、备份旧版本、切换文件、重启 ABS 服务并检查健康；失败自动回滚。
发布只覆盖 ABS 应用，不覆盖千问环境文件、工单数据库、Nginx 或原 BadRams 业务。

详细交接见 [DEPLOYMENT.md](DEPLOYMENT.md)，Agent 操作约束见 [AGENTS.md](AGENTS.md)。

## 目录与数据边界

| 路径 | 用途 |
|---|---|
| `app/static/abs/` | 原生 HTML/CSS/JS，产品及报告快照 |
| `app/abs_api.py` | 服务端报告校验、Qwen 调用和限流 |
| `app/abs_work.py` | 团队、工单、冻结证据、状态流转与通知 |
| `app/abs_stress*.py` | 数据导入、24项指标、多期瀑布、冻结报告与模型分析 |
| `scripts/dev.py` | 本地同源前端和 API 服务 |
| `scripts/deploy.py` | 通过独立 SSH 凭据部署已提交代码 |
| `deploy/` | 服务和代理配置参考、受限部署入口源代码 |
| `tests/` | API、工单、评分与前端回归测试 |

普通聊天保存在浏览器页面内存；工单及分析持久保存在服务器 SQLite。
工单当前使用站内通知，未开启邮件通知。千问 API Key、AGIDock 凭据、SSH 私钥、
数据库和日志不得提交到 GitHub。
