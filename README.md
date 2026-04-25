# statusCheck

一个给 Sub2API 部署使用的模型健康状态页：

- 用 **FastAPI + uv** 做后端聚合
- 用 **React + Vite** 做前端展示
- admin 侧按 Sub2API 的 **`x-api-key`** 鉴权方式调用
- 支持展示：
  - 按分组展示账号池可用 / 限流 / 异常 / 并发，避免只看总池大盘
  - 分组容量、并发占用、今日 / 累计成本
  - admin dashboard / ops overview / realtime 的关键运行指标
  - 近 7 天请求与成本趋势
  - 历史高消耗模型分布
  - 可选的 **真实模型探针**（需要额外 public API key）

## 在线预览

当前公网参考站点：<https://status.devbin.de/>

> 参考站点只暴露只读状态页和 token 保护的隐藏 `/admin` 页面；真实密钥、成本、请求量、token 量、用户数和 API key 数不会出现在公开接口字段里。

![statusCheck 深色模式预览](docs/statuscheck-preview.png)

## 目录结构

```text
.
├── app/                # FastAPI 后端
├── frontend/           # React 前端
├── demo.html           # 初始 UI 草稿，保留作参考
├── pyproject.toml      # uv / Python 依赖
└── .env.example        # 后端环境变量示例
```

## 环境变量

### 后端 `.env`

先复制：

```bash
cp .env.example .env
```

最少要填：

```env
SUB2API_BASE_URL=http://127.0.0.1:18081
SUB2API_ADMIN_API_KEY=your-admin-api-key
```

管理员 API Key 会通过请求头传递：
>
> ```text
> x-api-key: <your-admin-api-key>
> ```

可选的分组范围控制：

```env
# 留空 = 自动只看非 exclusive 的公开组
SUB2API_GROUP_IDS=

# true = 不排除 exclusive 私有组；false = 默认排除
SUB2API_INCLUDE_EXCLUSIVE_GROUPS=false
```

- 如果你填了 `SUB2API_GROUP_IDS=2,6`，后端会只展示这些分组的号池、容量、availability 和 probe 候选模型
- 如果你不填 `SUB2API_GROUP_IDS`，默认会**排除 `is_exclusive=true` 的私有组**

### 前端 `frontend/.env`

```bash
cp frontend/.env.example frontend/.env
```

默认建议留空走同源，这样通过 Tailscale / 反代访问时不会写死到 localhost：

```env
VITE_API_BASE_URL=
VITE_AUTO_REFRESH_MS=15000
```

## 开发启动

### 1) 安装后端依赖

```bash
uv sync
```

### 2) 启动 FastAPI

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 38481
```

### 3) 安装前端依赖

```bash
npm --prefix frontend install
```

### 4) 启动前端

```bash
npm --prefix frontend run dev
```

打开：

- 前端开发页：`http://127.0.0.1:38482`
- 后端 API：`http://127.0.0.1:38481/api/dashboard`

## 生产构建

### 构建前端

```bash
npm --prefix frontend run build
```

构建完成后，FastAPI 会直接把 `frontend/dist` 当静态站点托管。

### 生产运行

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 38481
```

然后直接访问：

- `http://127.0.0.1:38481`

## Docker Compose 一键启动

先准备运行时配置：

```bash
cp .env.example .env
```

至少填写管理员 Key：

```env
SUB2API_ADMIN_API_KEY=your-admin-api-key
```

如果 Sub2API 跑在宿主机 `18081` 端口，Docker Compose 默认会通过下面这个地址从容器访问宿主机服务：

```env
DOCKER_SUB2API_BASE_URL=http://host.docker.internal:18081
```

启动：

```bash
docker compose up -d
```

查看状态和日志：

```bash
docker compose ps
docker compose logs -f statuscheck
```

默认访问：

- `http://127.0.0.1:38481`

如果要改宿主机暴露端口，只改 `.env`：

```env
STATUSCHECK_PORT=38481
```


## 前端展示口径

主状态页默认只提供观测能力，不会主动修改 Sub2API 状态。当前展示口径是：

- 顶部指标展示整体探针与运行快照。
- 模型健康区按分组拆成独立卡片，每个分组之间有独立边框、间距和标题，避免多组模型混在同一张表里。
- 右侧“各分组账号情况”把原来的账号池总览和分组栏合并：
  - 每个分组单独显示账号总量、可用数、限流数、异常数。
  - 每个分组单独显示可用率和账号状态分布条。
  - 每个分组单独显示当前并发 / 最大并发。
- 页面不再单独保留一个“账号池大杂烩”模块，避免看不到单个分组真实情况。

如果需要改变展示哪些分组，直接进入隐藏 admin 页面修改 `SUB2API_GROUP_IDS`。

## 安全性说明

这个项目适合公开展示只读状态页，但需要注意公开数据边界：

- `/api/dashboard` 是公开只读接口，只保留分组名、账号数量、可用率、容量、延迟和模型探针状态等展示所需字段。
- `/admin` 页面没有主站入口，但 URL 本身不是安全边界；真正的保护来自后端 `ADMIN_TOKEN`。
- `/api/admin/*` 必须携带 `Authorization: Bearer <ADMIN_TOKEN>`，未授权会返回 `401`。
- `.env`、`frontend/.env` 等真实配置已被 `.gitignore` 排除，仓库只保留 `.env.example`。
- Docker Compose 会把宿主机 `.env` 挂载到容器 `/app/.env`，admin 保存配置时会写回这份文件；不要把真实 `.env` 提交到 GitHub。
- 后端响应会附加基础安全响应头：
  - `Content-Security-Policy`
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `Referrer-Policy: no-referrer`
  - `Permissions-Policy`
  - `Cross-Origin-Opener-Policy`
- `/api/dashboard` 默认移除请求量、token 量、成本、quota、API key 数、用户数和底层成功/失败请求计数，避免把运营隐私暴露在公开 JSON 字段里。
- 如确实需要公开某类字段，可在 `/admin` 的“公开展示”里显式勾选；对应环境变量是 `PUBLIC_DASHBOARD_FIELDS`。
- 首页顶部指标、模型表、快照、监控范围、分组账号池和告警卡片也可在 `/admin` 的“公开展示”里控制；对应环境变量是 `PUBLIC_DASHBOARD_CARDS`。
- `/api/*` 响应默认带 `Cache-Control: no-store`，避免中间层缓存带状态的 API 响应。

### 公开展示字段与卡片

默认公开账号数量、可用率、分组容量、延迟和模型探针结果；以下敏感字段默认不出现在 `/api/dashboard`，只能在 admin 页面显式开启：

- `costs`：成本相关字段
- `request_volume`：请求量、RPM、QPS 和趋势请求数
- `token_volume`：TPM、TPS、token 趋势和模型 token 量
- `api_keys`：API key 数量
- `users`：活跃用户数
- `quota`：额度估算
- `model_usage`：模型 7 日用量字段
- `ops_counts`：底层成功 / 失败 / 总请求计数

首页卡片也可配置：

```env
PUBLIC_DASHBOARD_CARDS=metric_monitor_items,metric_healthy_models,metric_abnormal_models,metric_probe_groups,model_groups,snapshot,scope,group_pool,insights
```


## 隐藏 Admin 配置页

项目提供一个隐藏配置页：

- 访问路径：`/admin`
- 主状态页没有入口链接，需要手动输入路径
- 后端通过环境变量 `ADMIN_TOKEN` 鉴权
- 前端登录后会用 `Authorization: Bearer <ADMIN_TOKEN>` 调用 admin API

最少配置：

```env
ADMIN_TOKEN=your-admin-token
```

当前 admin 页支持在线修改并立即刷新：

- `SUB2API_GROUP_IDS`
- `SUB2API_INCLUDE_EXCLUSIVE_GROUPS`
- `DASHBOARD_CACHE_TTL_SECONDS`
- `ACCOUNT_SCAN_*` 慢速扫描配置
- `SUB2API_MONITOR_API_KEY`
- `SUB2API_MONITOR_GROUP_API_KEYS`
- `SUB2API_MONITOR_MODELS`
- `SUB2API_MONITOR_GROUP_MODELS`
- `SUB2API_MONITOR_MODEL_SOURCES`
- `SUB2API_MONITOR_*` 探针超时、并发、prompt、endpoint 等配置

Docker Compose 模式会把宿主机 `.env` 挂载到容器 `/app/.env`，admin 保存时会同步写回这份文件；同时也会更新当前进程内存配置并触发一次 dashboard 刷新，不需要手动重启。

## 真实模型探针说明

默认情况下，这个项目**只接 admin 统计**，已经能看到：

- 号池数量
- 分组容量
- usage 趋势
- 近 1h SLA / 延迟 / 上游错误率

但如果要做**真正的模型可用性探针**，还需要额外配置：

```env
SUB2API_MONITOR_API_KEY=一个普通可调用 /v1/models 和 /v1/chat/completions 的 key
SUB2API_MONITOR_GROUP_API_KEYS=
SUB2API_MONITOR_MODELS=gpt-5.4,gpt-5.4-mini,claude-sonnet-4-6
SUB2API_MONITOR_GROUP_MODELS=
SUB2API_MONITOR_MODEL_SOURCES=groups,configured
```

这样前端里的模型矩阵会从“历史 usage 展示”升级成“真实探针 + catalog + usage”。

### 模型来源与自动探针

现在探针模型支持 4 种来源，可组合：

```env
SUB2API_MONITOR_MODEL_SOURCES=groups,configured,usage,catalog
```

可选值：

- `groups`
  - 自动从当前监控分组里提取模型
  - 会读取：
    - `default_mapped_model`
    - `messages_dispatch_model_config`
    - `model_routing`
- `configured`
  - 使用 `SUB2API_MONITOR_MODELS` 里手动指定的模型
- `usage`
  - 从 snapshot 最近高频模型里补充
  - 数量由 `SUB2API_MONITOR_USAGE_MODEL_LIMIT` 控制
- `catalog`
  - 直接把 `/v1/models` 返回的模型加入探针候选集合

默认值是：

```env
SUB2API_MONITOR_MODEL_SOURCES=groups,configured
```

也就是说，**现在分组探针会自动从 group 配置派生，不再只是拿 snapshot 前几名模型硬探。**

### 按分组单独配置探针模型

如果不同分组需要探测不同模型，可以配置 `SUB2API_MONITOR_GROUP_MODELS`。它只影响 `SUB2API_MONITOR_MODEL_SOURCES` 里启用了 `configured` 的“手动列表”来源。

规则是：

- 某个分组配置了自己的模型列表：该分组使用自己的手动模型列表。
- 某个分组没有配置：继续使用全局 `SUB2API_MONITOR_MODELS`。
- `groups` / `usage` / `catalog` 来源仍按原配置追加候选模型。

推荐使用 JSON，适合写入 `.env` 或通过 `/admin` 页面保存：

```env
SUB2API_MONITOR_GROUP_MODELS={"2":["gpt-5.4","gpt-5.4-mini"],"6":["gpt-5.3-codex","gpt-5.2"]}
```

也支持简写格式：

```env
SUB2API_MONITOR_GROUP_MODELS=2=gpt-5.4|gpt-5.4-mini;6=gpt-5.3-codex|gpt-5.2
```

隐藏 admin 页面会按当前监控分组展示“按分组覆盖手动模型”，留空表示沿用全局手动模型列表。

### 一个 probe key 只能监控一个分组时怎么配

如果普通探针 key 是**按 group 绑定**的，不要只配一个全局：

```env
SUB2API_MONITOR_GROUP_API_KEYS=2=group2_probe_key,6=group6_probe_key
```

支持三种格式：

- 逗号分隔：
  - `2=keyA,6=keyB`
- 换行分隔：
  - `2=keyA`
  - `6=keyB`
- JSON：
  - `{"2":"keyA","6":"keyB"}`

当前后端逻辑是：

- 如果配置了 `SUB2API_MONITOR_GROUP_API_KEYS`
  - 就按 `group_id -> key` 逐组探测
- 如果**没有**配置 group 映射，但当前监控范围里**只有 1 个分组**
  - 才会回退使用 `SUB2API_MONITOR_API_KEY`
- 如果当前监控范围里有多个分组，但你只给了一个全局 `SUB2API_MONITOR_API_KEY`
  - 后端不会再假装它能覆盖所有组
  - 没配到 key 的分组会被标记为“未配置探针 Key”

### 刷新策略

当前默认配置：

- `DASHBOARD_CACHE_TTL_SECONDS=60`
- `VITE_AUTO_REFRESH_MS=15000`

含义：

- 后台每 60 秒刷新一次探针快照
- 前端每 15 秒读取一次缓存
- `/api/dashboard` 不会因为前端请求而现场触发探测

## 慢速额度估算说明

如果你还想在界面里看**显式额度估算**，可以开启：

```env
ACCOUNT_SCAN_ENABLED=true
```

这个模式会分页扫 `/api/v1/admin/accounts`，然后只聚合带显式额度字段的账号：

- `quota_limit / quota_used`
- `window_cost_limit / current_window_cost`

注意：

- 它是**显式额度估算**，不是全池绝对真实额度
- 对 OAuth 账号这类没有统一美元额度字段的情况，只能做覆盖范围内的估算

## 当前实现的数据源

后端主要调用这些 live 接口：

- `/api/v1/admin/dashboard/snapshot-v2`
- `/api/v1/admin/dashboard/stats`
- `/api/v1/admin/dashboard/realtime`
- `/api/v1/admin/ops/dashboard/overview`
- `/api/v1/admin/groups`
- `/api/v1/admin/groups/capacity-summary`
- `/api/v1/admin/groups/usage-summary`
- `/api/v1/admin/ops/account-availability`

补充说明：

- `/api/v1/admin/ops/dashboard/overview` 和 `/api/v1/admin/ops/account-availability` 支持 `group_id`
- 但 `dashboard/snapshot-v2` 当前 **不会按 `group_id` 真正过滤历史趋势 / model usage**
- 所以当前实现里：
  - 分组列表、号池状态、capacity、availability、ops 视图、probe 候选模型都会按分组范围收口
  - 7 天历史 trend / snapshot model usage 仍然来自 live snapshot 接口本身

## License

MIT
