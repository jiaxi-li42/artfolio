# 日常采集与运行

采集使用确定性的 Python 来源适配器。正常运行不调用 AI，也不需要人工逐篇整理；来源结构变化、访问限制或校验失败会进入隔离，修复适配器后才能恢复。网站与采集分开部署，内容不写回 GitHub。

## 存储与网站

准备两个 S3 兼容存储桶。可使用 Cloudflare R2 或支持条件写入的 AWS S3：

- 私有桶：原始 RSS、HTML、图片、校验记录、任务状态、租约、运行报告和状态备份，禁止公开访问。
- 公开桶：经过校验的文章 JSON、图片及预览、版本目录，以及 `current.json`。为其配置 HTTPS 域名。

默认对象前缀为 `artfolio`。例如公开域名为 `https://content.example.com` 时，网站和采集端均配置 `ARTFOLIO_CONTENT_BASE_URL=https://content.example.com/artfolio/`。域名必须直接映射到公开桶，并保留对象的 Content-Type 和 Cache-Control；`current.json` 必须遵循 `no-store`，不能被 CDN 的强制缓存规则覆盖。

网站运行 Next.js 服务端（不能只部署静态 HTML），只设置 `ARTFOLIO_CONTENT_BASE_URL`。公开 JSON 由同源服务端读取并校验 SHA-256，图片直接使用公开域名，不需要给网站配置 S3 凭据或 JSON 跨域权限。未配置域名时，继续读取本地 `public/data/catalog.json`，缺少本地内容时显示空状态。

网站进程会保留最近一次成功读取的目录；短暂网络错误时继续使用它。新进程在存储不可用时没有这个缓存。已打开页面的图片和详情仍依赖公开存储可用性。

## GitHub Actions 配置

在仓库 Settings → Secrets and variables → Actions 中设置：

| 类型 | 名称 | 内容 |
| --- | --- | --- |
| Variable | `ARTFOLIO_STATE_BUCKET` | 私有桶名 |
| Variable | `ARTFOLIO_PUBLIC_BUCKET` | 公开桶名，必须不同于私有桶 |
| Variable | `ARTFOLIO_CONTENT_BASE_URL` | 含对象前缀的公开 HTTPS 地址 |
| Variable | `ARTFOLIO_S3_ENDPOINT` | R2 S3 API endpoint；AWS S3 留空 |
| Variable | `ARTFOLIO_S3_REGION` | R2 为 `auto`；AWS 为桶所在区域 |
| Variable | `ARTFOLIO_S3_PREFIX` | 默认 `artfolio` |
| Secret | `ARTFOLIO_ACCESS_KEY_ID` | 对这两个桶有读写权限的访问密钥 ID |
| Secret | `ARTFOLIO_SECRET_ACCESS_KEY` | 密钥内容 |
| Secret，可选 | `ARTFOLIO_ALERT_WEBHOOK` | 接收 `{"text":"…"}` JSON 的告警地址 |
| Secret，可选 | `ARTFOLIO_HEARTBEAT_URL` | 成功运行后访问的外部监控地址 |
| Variable | `ARTFOLIO_PIPELINE_ENABLED` | 首次手动运行成功后设为 `true`，启用定时任务 |

凭据仅用于采集：需要对象读取（GetObject，包含 HeadObject 请求）和写入（PutObject）权限，存储必须支持 `If-Match`、`If-None-Match` 原子条件写入。程序不申请删除权限，不推送代码。网站不使用这些密钥。首次手动运行会创建状态，无需上传初始化文件。

AWS S3 还需给采集身份授予两个桶的 `s3:ListBucket` 权限，使不存在的对象返回 404；否则初始化的 GetObject／HeadObject 可能返回 403，程序会安全停止。不要把 ListBucket 权限授予匿名公众，公开桶的匿名访问只需 GetObject。见 [AWS HeadObject 权限说明](https://docs.aws.amazon.com/AmazonS3/latest/API/API_HeadObject.html)。

工作流位于 `.github/workflows/daily-content.yml`。默认在伦敦时间每天 08:17、14:17、20:17 运行，自动适应夏令时。每个来源每日最多添加一篇未收录文章，后续运行用于补跑失败来源或重新检查当天没有新内容的来源。调整时间可直接修改工作流。

先将工作流推送至默认分支，再在 Actions → Daily content → Run workflow 使用 `collect`。检查运行摘要、网站目录与详情正常后启用开关。尚未设置桶、凭据和网站域名时，代码准备完成不等于采集已经上线。

## 处理流程与状态

1. 获取并持续续期存储租约，工作流另有并发限制。租约默认十分钟，进程中断后到期可恢复；失去租约的进程不能继续切换发布版本。
2. 恢复任务清单和所需缓存。按“日期／来源”建立独立任务，自动补齐上次请求日期至今天的遗漏日期，继续未完成的旧任务。
3. RSS 缓存三十分钟，之后使用 ETag／Last-Modified 条件请求。发布日期统一为 UTC，再按伦敦日期判断批次；无日期、无时区、错误 XML 不会被当作没有新内容。
4. 在 RSS 中选择截至批次日期、尚未使用的文章。网络失败固定原候选项续跑，不用别的文章掩盖网络错误；内容不合格时最多检查六个候选项。RSS 有保留期限，补历史日期只能使用当前仍可取得的条目，不能重建过去真实的每日列表。
5. 按来源的明确容器提取正文、子标题、作者、Notes、References、Credits 与图注。不从普通正文猜测署名；图注只用于全屏画廊。Teeth／PHROOM 允许只有图片的项目，Aperture／It’s Nice That／C41 要求有效正文。
6. 下载图片，检查 MIME、格式、文件哈希、实际解码、尺寸、EXIF 方向和帧数。处理上限为每图 25 MB／四千万像素、每篇一百张／250 MB，超限隔离。原始资料与不完整进度按内容哈希存入私有桶；恢复时验证路径、大小和哈希。完整文章不会每天重新下载全部历史图片。
7. 生成不可变的媒体、详情及目录；确认上传完成并读回目录后，用条件写入一次切换 `current.json`。途中失败继续保留上一版。切换后若进程中断，下次依据当前目录修正状态，避免重复发布。

状态包括 `pending`、`retry`、`no_new`、`ready`、`published`、`quarantined` 和回滚后的 `held`。网络超时、429 和 5xx 最多尝试三次；较长 Retry-After 延后到后续任务；跨任务退避为一小时、两小时、四小时，最高六小时，服务端要求更久则继续等待。当天 `no_new` 至少两小时后再查，历史 `no_new` 不反复抓取。

页面结构、登录／验证页、缺少正文或图片完整性问题进入隔离。适配器代码版本变化后会自动重新检查隔离任务；访问限制不会被绕过。缺失的可选署名不会虚构补齐，原始资料与提取规则保留供排查。正文、作者介绍和版权边界仍可能随来源改版变化，不能保证永远无需维护。

每次正常结束的摘要区分 `success`（已切换版本）、`no_new`（无变化）、`partial`（部分来源未完成）、`failed` 与 `locked`。退出码分别为 0／0／2／1／0；工作流把 2 显示为 warning，并保留有效发布结果。严重错误让工作流失败。单次采集预算三十五分钟，工作流上限四十五分钟；未完成任务下次继续。

## 运维、告警与回滚

在手动工作流选择：

- `collect`：常规采集；可选填 `through` 日期。首次只建立该日批次，需要历史样例时可先填较早日期，再运行到今天。
- `retry`：立即重试未完成任务、隔离任务和回滚保留任务，重新获取文章 HTML；不会改动已经发布的文章。
- `publish-only`：只发布已完成校验的 `ready` 任务，不访问来源。
- `audit`：逐项恢复历史档案，检查原始数据、公开详情和原图的哈希；规模较大时受单次预算限制。
- `rollback`：填入运行摘要中的旧版 64 位 release hash，切回保留的目录。不删除任何文件；被移除文章的任务设为 `held`，避免下次自动发布回来。

报告保存在私有桶 `artfolio/runs/<runId>/` 和 Actions 运行摘要；Actions 仅保存 `last-run.json` 十四天，原始内容不作为构建产物上传。每个状态检查点都有不可变备份，活动清单为私有桶 `artfolio/state/manifest.json`。损坏或不可读的状态会阻止发布，不会被空清单覆盖。所有本地内容及缓存仍被 Git 忽略。

需要恢复清单时，先关闭定时开关并等待当前任务结束，再用私有桶中已知正常的 `state-*.json` 备份替换 `state/manifest.json`，然后手动运行。不要手工删除状态来重新初始化一个已有发布版本的站点。

可选告警在任务被隔离或连续三次运行不完整后发送；端点失败会输出 warning。完整成功或没有新内容时发送外部心跳，不完整或严重失败不发送。为心跳监控设置约二十六小时容限和独立通知，便可发现计划任务停跑或凭据失效。没有配置外部监控时，只能依赖 Actions 报告及其失败通知；`partial` 为 warning，不触发工作流失败通知。

[GitHub 官方说明](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)：计划任务可能延迟或丢失；公开仓库六十天无活动会自动停用计划任务。外部心跳用于发现这种停跑，不能靠采集程序自身发现自己没有启动。

建议为私有桶 `artfolio/runs/` 配置九十天生命周期，并启用供应商提供的状态版本保留／备份。不要给 `archives/`、公开文章、媒体和 releases 设置无条件过期规则，它们可能仍被历史文章和回滚版本引用。清理这些对象需要先计算引用关系，本次不加入自动删除。R2 条件写入支持见[官方兼容说明](https://developers.cloudflare.com/r2/api/s3/api/)。

## 本地执行

Python 3.10 以上（工作流使用 3.12）：

```sh
pip install -r requirements.txt
python scripts/run_daily.py
python scripts/run_daily.py --through 2026-10-25
python scripts/run_daily.py --retry-quarantined
python scripts/run_daily.py --publish-only
python scripts/run_daily.py --audit
python scripts/run_daily.py --rollback RELEASE_HASH
```

本地需在终端显式设置 `.env.example` 列出的环境变量，其中凭据名使用 `AWS_ACCESS_KEY_ID`／`AWS_SECRET_ACCESS_KEY`。Python 不自动载入 `.env`；Next.js 可以从 `.env.local` 读取网站域名。旧 `acquire_articles.py`、`update_articles.py` 入口转入同一个运行器；`prepare_data.py` 转入 `--publish-only`。本次不提供第二套本地发布流程，以免绕过校验和原子发布。
