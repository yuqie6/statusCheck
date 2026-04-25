# statusCheck

一个给 Sub2API 部署使用的模型健康状态页：

- 用 **FastAPI + uv** 做后端聚合
- 用 **React + Vite** 做前端展示
- admin 侧按 Sub2API 的 **`x-api-key`** 鉴权方式调用
- 支持展示：
  - 号池总量 / 可用量 / 限流量 / 异常量
  - 分组容量、并发占用、今日 / 累计成本
  - admin dashboard / ops overview / realtime 的关键运行指标
  - 近 7 天请求与成本趋势
  - 历史高消耗模型分布
  - 可选的 **真实模型探针**（需要额外 public API key）

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

### 一个 probe key 只能监控一个分组时怎么配

如果普通探针 key 是**按 group 绑定**的，不要只配一个全局：

```env
SUB2API_MONITOR_GROUP_API_KEYS=2=group2_probe_key,6=group6_probe_key
```

支持两种格式：

- 逗号分隔：
  - `2=keyA,6=keyB`
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
