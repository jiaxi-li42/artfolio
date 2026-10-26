# ARTFOLIO

摄影、艺术与视觉文化网站。保留文章目录、日期归档、标题与来源搜索、响应式阅读、全屏画廊，以及采集 / 导出源码。

临时联调网站：[artfolio-wheat.vercel.app](https://artfolio-wheat.vercel.app/)。当前实例已接入 R2 和 GitHub Actions。

本目录即 Git 仓库和 Next.js 项目根目录。未附带第三方文章、图片或参考站字体；没有本地内容时显示空状态。

## 运行

需要 Node.js 20.9 或更高版本。在本目录执行：

```sh
npm ci
npm run dev
```

访问 http://127.0.0.1:3000。生产构建使用 npm run build，启动使用 npm run start；类型检查使用 npm run typecheck。

## 结构

- app、components、lib：页面、交互、样式、内容类型及空目录加载。
- public/brand：用户提供的 ARTFOLIO SVG。
- public/fonts：Inter 可变字体、Material Symbols Outlined 子集及各自许可证。
- scripts：来源解析、资料清理、任务状态、S3 存储及日常采集运行器。
- .github/workflows：日常采集、补跑、审计与回滚的工作流。
- requirements.txt：Python 依赖；仅运行前端时不需要安装。

文字字体栈为 'SF Pro', -apple-system, BlinkMacSystemFont, Inter, system-ui, sans-serif。苹果设备优先使用系统自带 SF Pro，BlinkMacSystemFont 用于苹果 Chromium 浏览器兼容；其他设备使用本地托管的 Inter 4.1。SF Pro 不随项目分发，Inter 以 SIL Open Font License 1.1 许可提供。字号、行距与字距保持原设置。图标继续使用 Material Symbols Outlined，字重 300。项目不包含测试文件、测试依赖、旧研究资料或上传副本。

手机首页在打开文章后才加载详情；阅读过程中最多复用八篇已读取详情。历史目录只挂载视口附近的卡片，日期归档每次增加二十四个日期，搜索覆盖全部摘要。来源快捷项使用独立的 `source` URL 参数进行精确筛选，普通关键词使用 `search`。Credits 的区块间距保留 32px，长署名和链接允许换行。

整页加载与路由等待保持空白。部署、运维、验收及界面说明保存在本地 `docs/`，不纳入 Git 上传。

## 内容与定时采集

页面读取 public/data/catalog.json 和文章详情 JSON。缺少目录文件时自动显示空状态，不生成示例文章或虚构更新时间。

采集在 GitHub Actions 运行，原始档案与任务状态存入私有 S3 兼容桶，通过校验的文章和图片存入另一公开桶。网站只需配置 `ARTFOLIO_CONTENT_BASE_URL`，不需要存储密钥；采集无需把内容提交至 GitHub，也不需要每次重新部署网站。

安装 Python 依赖并配置存储后，也可以在本地执行同一采集任务：

```sh
pip install -r requirements.txt
python scripts/run_daily.py
```

运行器按来源和日期记录状态，支持失败续跑、去重、有限重试、质量隔离和原子发布。原始资料和运行缓存位于 data，继续由 Git 忽略。前端数据结构见 lib/types.ts。

完整设置、密钥表、调度时间、告警与回滚方式保存在本地运维文档中。定时任务默认未启用；配置外部存储并手动验证成功后，再设置 `ARTFOLIO_PIPELINE_ENABLED=true`。启动网站或提交代码不会自动触发采集。

## GitHub

由维护者统一提交并推送源码；日常修改保持未暂存、未提交状态。保存文件不会自动推送；本项目未设置推送钩子或后台同步任务。

.gitignore 排除依赖、构建结果、环境文件、本地文档、内容与缓存。克隆后在根目录执行 npm ci 即可恢复前端依赖。素材与依赖说明见 THIRD_PARTY_NOTICES.md。
