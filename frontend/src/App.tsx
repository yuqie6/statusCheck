import { useEffect, useMemo, useState } from 'react'
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock3,
  KeyRound,
  Layers3,
  RefreshCw,
  ShieldAlert,
  Sparkles,
  type LucideIcon,
} from 'lucide-react'
import { ThemeToggle } from './components/ThemeToggle'
import { fetchDashboard } from './lib/api'
import {
  formatDateTime,
  formatLatency,
  formatNumber,
  formatPercent,
} from './lib/format'
import type {
  DashboardResponse,
  GroupRow,
  InsightSeverity,
  ModelGroupSection,
  ModelRow,
  ProbeGroupRef,
} from './types'
import './styles.css'

const autoRefreshMs = Number(import.meta.env.VITE_AUTO_REFRESH_MS ?? 15000)

type ModelBadgeTone = 'healthy' | 'degraded' | 'down' | 'history' | 'disabled'
type HeroStateTone = 'healthy' | 'warning' | 'critical' | 'disabled'

function ratio(value: number, total: number): number {
  if (!total) return 0
  return value / total
}

function percentWidth(value: number, total: number): number {
  return Math.max(0, Math.min(100, ratio(value, total) * 100))
}

function MetricCard({
  title,
  value,
  note,
  icon: Icon,
  tone,
}: {
  title: string
  value: string
  note: string
  icon: LucideIcon
  tone: 'neutral' | 'good' | 'warn' | 'critical'
}) {
  return (
    <article className={`metric-card metric-card--${tone} fade-up`}>
      <div className="metric-card__header">
        <span>{title}</span>
        <div className="metric-card__icon">
          <Icon size={16} />
        </div>
      </div>
      <strong>{value}</strong>
      <p>{note}</p>
    </article>
  )
}

function StatusBadge({ status }: { status: ModelBadgeTone }) {
  const config = {
    healthy: { className: 'status-badge is-healthy', label: '正常', icon: CheckCircle2 },
    degraded: { className: 'status-badge is-degraded', label: '波动', icon: AlertTriangle },
    down: { className: 'status-badge is-down', label: '失败', icon: ShieldAlert },
    history: { className: 'status-badge is-history', label: '历史', icon: Activity },
    disabled: { className: 'status-badge is-disabled', label: '未探测', icon: Clock3 },
  }[status]

  const Icon = config.icon
  return (
    <span className={config.className}>
      <Icon size={13} />
      {config.label}
    </span>
  )
}

function InsightBadge({ severity }: { severity: InsightSeverity }) {
  const config = {
    critical: {
      className: 'insight-badge is-critical',
      label: '优先处理',
      icon: ShieldAlert,
    },
    warning: {
      className: 'insight-badge is-warning',
      label: '需要关注',
      icon: AlertTriangle,
    },
    info: {
      className: 'insight-badge is-info',
      label: '提示',
      icon: Sparkles,
    },
  }[severity]

  const Icon = config.icon
  return (
    <span className={config.className}>
      <Icon size={13} />
      {config.label}
    </span>
  )
}

function ScopeChip({
  group,
  configured,
}: {
  group: ProbeGroupRef
  configured: boolean
}) {
  return (
    <span className={`scope-chip ${configured ? 'is-configured' : 'is-missing'}`}>
      {configured ? <CheckCircle2 size={13} /> : <AlertTriangle size={13} />}
      {group.name}
    </span>
  )
}

function modelBadge(row: ModelRow): ModelBadgeTone {
  switch (row.probe_status) {
    case 'healthy':
      return 'healthy'
    case 'degraded':
      return 'degraded'
    case 'down':
      return 'down'
    case 'untracked':
      return 'history'
    case 'disabled':
      return 'disabled'
    default:
      return 'history'
  }
}

function groupTone(status: string): 'good' | 'warn' | 'bad' | 'muted' {
  switch (status) {
    case 'healthy':
      return 'good'
    case 'warning':
    case 'critical':
    case 'saturated':
      return 'warn'
    case 'error':
    case 'down':
      return 'bad'
    default:
      return 'muted'
  }
}

function modelGroupBadge(section: ModelGroupSection): ModelBadgeTone {
  switch (section.status) {
    case 'healthy':
      return 'healthy'
    case 'degraded':
      return 'degraded'
    case 'down':
      return 'down'
    case 'disabled':
    default:
      return 'disabled'
  }
}

function badgeRank(status: ModelBadgeTone): number {
  switch (status) {
    case 'down':
      return 0
    case 'degraded':
      return 1
    case 'disabled':
      return 2
    case 'history':
      return 3
    case 'healthy':
    default:
      return 4
  }
}

function groupSectionStats(section: ModelGroupSection) {
  return section.models.reduce(
    (acc, row) => {
      const badge = modelBadge(row)
      acc.total += 1
      acc[badge] += 1
      return acc
    },
    {
      total: 0,
      healthy: 0,
      degraded: 0,
      down: 0,
      history: 0,
      disabled: 0,
    },
  )
}

function overallState(args: {
  total: number
  healthy: number
  degraded: number
  down: number
  missingProbeGroups: number
  monitorEnabled: boolean
}): { tone: HeroStateTone; title: string; note: string } {
  if (!args.monitorEnabled) {
    return {
      tone: 'disabled',
      title: '等待探针',
      note: '未配置探针 Key',
    }
  }
  if (args.down > 0) {
    return {
      tone: 'critical',
      title: '存在故障',
      note: `${args.down} 个模型失败`,
    }
  }
  if (args.degraded > 0 || args.missingProbeGroups > 0) {
    return {
      tone: 'warning',
      title: '存在波动',
      note:
        args.missingProbeGroups > 0
          ? `${args.missingProbeGroups} 个分组未配置 Key`
          : `${args.degraded} 个模型波动`,
    }
  }
  return {
    tone: 'healthy',
    title: '运行正常',
    note: `${args.healthy}/${args.total} 正常`,
  }
}

function groupAvailability(group: GroupRow): number {
  return ratio(group.available_count, group.account_count)
}

export default function App() {
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function load() {
    if (dashboard) {
      setRefreshing(true)
    } else {
      setLoading(true)
    }

    try {
      const next = await fetchDashboard()
      setDashboard(next)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => {
    void load()
    const timer = window.setInterval(() => {
      void load()
    }, autoRefreshMs)
    return () => window.clearInterval(timer)
  }, [])

  const modelGroups = dashboard?.model_groups ?? []
  const modelRows = dashboard?.models ?? []

  const orderedModelGroups = useMemo(() => {
    return [...modelGroups]
      .map((section) => ({
        ...section,
        models: [...section.models].sort((a, b) => {
          const badgeDiff = badgeRank(modelBadge(a)) - badgeRank(modelBadge(b))
          if (badgeDiff !== 0) return badgeDiff

          const ttftA = a.probe_ttft_ms ?? Number.POSITIVE_INFINITY
          const ttftB = b.probe_ttft_ms ?? Number.POSITIVE_INFINITY
          if (ttftA !== ttftB) return ttftA - ttftB

          return a.model.localeCompare(b.model, 'zh-CN')
        }),
      }))
      .sort((a, b) => {
        const statusDiff = badgeRank(modelGroupBadge(a)) - badgeRank(modelGroupBadge(b))
        if (statusDiff !== 0) return statusDiff
        return a.group_name.localeCompare(b.group_name, 'zh-CN')
      })
  }, [modelGroups])

  const modelState = useMemo(() => {
    return modelRows.reduce(
      (acc, row) => {
        const view = modelBadge(row)
        acc.total += 1
        acc[view] += 1
        return acc
      },
      {
        total: 0,
        healthy: 0,
        degraded: 0,
        down: 0,
        history: 0,
        disabled: 0,
      },
    )
  }, [modelRows])

  if (loading && !dashboard) {
    return (
      <main className="status-page status-page--loading">
        <div className="loading-shell">
          <div className="loading-spinner" />
          <div>
            <p className="loading-title">正在加载模型状态</p>
            <p className="loading-note">正在获取数据…</p>
          </div>
        </div>
      </main>
    )
  }

  if (!dashboard) {
    return (
      <main className="status-page status-page--loading">
        <div className="empty-state">
          <p>{error ?? '暂时没有可展示的数据。'}</p>
          <button className="refresh-button" onClick={() => void load()}>
            <RefreshCw size={16} />
            重新加载
          </button>
        </div>
      </main>
    )
  }

  const { summary, pool, sources } = dashboard
  const scopedGroups = dashboard.config.group_scope.group_names.map((name, index) => ({
    id: dashboard.config.group_scope.group_ids[index] ?? index,
    name,
  }))
  const configuredProbeGroupIds = new Set(dashboard.config.probe_groups.map((item) => item.id))
  const heroState = overallState({
    total: modelState.total,
    healthy: modelState.healthy,
    degraded: modelState.degraded,
    down: modelState.down,
    missingProbeGroups: dashboard.config.probe_missing_groups.length,
    monitorEnabled: dashboard.config.monitor_key_configured,
  })
  const abnormalCount = modelState.degraded + modelState.down
  const scopeLabel = scopedGroups.length > 0 ? scopedGroups.map((item) => item.name).join(' / ') : '未设置'
  const visibleCards = new Set(dashboard.config.public_dashboard_cards ?? [])
  const showMetricMonitorItems = visibleCards.has('metric_monitor_items')
  const showMetricHealthyModels = visibleCards.has('metric_healthy_models')
  const showMetricAbnormalModels = visibleCards.has('metric_abnormal_models')
  const showMetricProbeGroups = visibleCards.has('metric_probe_groups')
  const showModelGroups = visibleCards.has('model_groups')
  const showSnapshot = visibleCards.has('snapshot')
  const showScope = visibleCards.has('scope')
  const showGroupPool = visibleCards.has('group_pool')
  const showInsights = visibleCards.has('insights')
  const showSidebar = showSnapshot || showScope || showGroupPool || showInsights
  const groupsView = pool.groups

  return (
    <main className="status-page">
      <div className="status-page__orb status-page__orb--left" />
      <div className="status-page__orb status-page__orb--right" />

      <div className="status-shell">
        <header className="status-hero fade-up">
          <div className="status-hero__copy">
            <span className="status-eyebrow">Sub2API Status</span>
            <h1>模型健康状态</h1>
            <p>探针结果概览</p>

            <div className="status-chip-row">
              <span className="status-chip">
                <Layers3 size={14} />
                {scopeLabel}
              </span>
              <span className="status-chip">
                <Activity size={14} />
                {formatNumber(modelState.total)} 项
              </span>
              <span className="status-chip">
                <RefreshCw size={14} />
                {Math.round(autoRefreshMs / 1000)} 秒
              </span>
            </div>
          </div>

          <div className="status-hero__side">
            <div className={`hero-state hero-state--${heroState.tone}`}>
              <span className="hero-state__label">整体状态</span>
              <strong>{heroState.title}</strong>
              <p>{heroState.note}</p>
            </div>
            <ThemeToggle />
            <button
              onClick={() => void load()}
              disabled={refreshing}
              className="refresh-button"
            >
              <RefreshCw size={16} className={refreshing ? 'spin' : ''} />
              {refreshing ? '刷新中…' : '立即刷新'}
            </button>
          </div>
        </header>

        {error ? <div className="warning-banner fade-up">最近一次刷新失败：{error}</div> : null}

        <section className="metric-grid">
          {showMetricMonitorItems ? (
          <MetricCard
            title="监控项"
            value={formatNumber(modelState.total)}
            note="按组展开"
            icon={Layers3}
            tone="neutral"
          />
          ) : null}
          {showMetricHealthyModels ? (
          <MetricCard
            title="探针正常"
            value={formatNumber(modelState.healthy)}
            note={modelState.total ? formatPercent(ratio(modelState.healthy, modelState.total)) : '—'}
            icon={CheckCircle2}
            tone="good"
          />
          ) : null}
          {showMetricAbnormalModels ? (
          <MetricCard
            title="异常模型"
            value={formatNumber(abnormalCount)}
            note={abnormalCount > 0 ? '需要处理' : '无异常'}
            icon={ShieldAlert}
            tone={abnormalCount > 0 ? 'critical' : 'neutral'}
          />
          ) : null}
          {showMetricProbeGroups ? (
          <MetricCard
            title="探针分组"
            value={`${dashboard.config.probe_groups.length}/${dashboard.config.group_scope.group_ids.length}`}
            note={
              dashboard.config.probe_missing_groups.length > 0
                ? `缺 ${dashboard.config.probe_missing_groups.length} 个 Key`
                : '已配置'
            }
            icon={KeyRound}
            tone={dashboard.config.probe_missing_groups.length > 0 ? 'warn' : 'good'}
          />
          ) : null}
        </section>

        <section className="status-layout">
          {showModelGroups ? (
          <article className="panel panel--main fade-up">
            <div className="panel__head">
              <div>
                <span className="panel__eyebrow">Model Status</span>
                <h2>分组模型</h2>
              </div>
              <p>{formatNumber(orderedModelGroups.length)} 组</p>
            </div>

            <div className="model-group-list">
              {orderedModelGroups.map((section) => {
                const stats = groupSectionStats(section)
                return (
                  <section key={section.group_id} className="model-group-section">
                    <div className="model-group-section__head">
                      <div>
                        <h3>{section.group_name}</h3>
                        <div className="model-group-section__meta">
                          <span>{formatNumber(section.models.length)} 个模型</span>
                          {!section.has_probe_key ? <span className="tiny-tag is-danger">缺 Key</span> : null}
                        </div>
                        <div className="model-group-section__stats">
                          <span className="tiny-tag is-healthy">正常 {formatNumber(stats.healthy)}</span>
                          {stats.degraded > 0 ? (
                            <span className="tiny-tag is-warn">波动 {formatNumber(stats.degraded)}</span>
                          ) : null}
                          {stats.down > 0 ? (
                            <span className="tiny-tag is-danger">失败 {formatNumber(stats.down)}</span>
                          ) : null}
                          {stats.disabled > 0 ? (
                            <span className="tiny-tag is-muted">未探测 {formatNumber(stats.disabled)}</span>
                          ) : null}
                        </div>
                      </div>
                      <StatusBadge status={modelGroupBadge(section)} />
                    </div>

                    {section.models.length > 0 ? (
                      <div className="table-wrap">
                        <table className="status-table status-table--grouped">
                          <thead>
                            <tr>
                              <th>模型</th>
                              <th>状态</th>
                              <th>TTFT</th>
                              <th>总耗时</th>
                            </tr>
                          </thead>
                          <tbody>
                            {section.models.map((row) => (
                              <tr key={`${section.group_id}-${row.model}`}>
                                <td>
                                  <div className="model-name-cell">
                                    <div className="model-name-cell__title">{row.model}</div>
                                    <div className="model-name-cell__meta">
                                      <span>{row.provider}</span>
                                      {row.catalog_available === false ? (
                                        <span className="tiny-tag is-danger">目录缺失</span>
                                      ) : null}
                                    </div>
                                  </div>
                                </td>
                                <td>
                                  <div className="status-copy">
                                    <StatusBadge status={modelBadge(row)} />
                                    {row.probe_error ? <p>{row.probe_error}</p> : null}
                                  </div>
                                </td>
                                <td>
                                  <div className="latency-pill">
                                    <Clock3
                                      size={14}
                                      className={row.probe_ttft_ms && row.probe_ttft_ms > 1000 ? 'is-hot' : ''}
                                    />
                                    <span className={row.probe_ttft_ms && row.probe_ttft_ms > 1000 ? 'is-hot' : ''}>
                                      {formatLatency(row.probe_ttft_ms)}
                                    </span>
                                  </div>
                                </td>
                                <td>
                                  <div className="latency-pill">
                                    <Clock3
                                      size={14}
                                      className={row.probe_latency_ms && row.probe_latency_ms > 1000 ? 'is-hot' : ''}
                                    />
                                    <span className={row.probe_latency_ms && row.probe_latency_ms > 1000 ? 'is-hot' : ''}>
                                      {formatLatency(row.probe_latency_ms)}
                                    </span>
                                  </div>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <div className="model-group-empty">暂无模型</div>
                    )}
                  </section>
                )
              })}
            </div>
          </article>
          ) : null}

          {showSidebar ? (
          <aside className="sidebar-stack">
            {showSnapshot ? (
            <section className="panel fade-up">
              <div className="panel__head panel__head--stacked">
                <div>
                  <span className="panel__eyebrow">快照</span>
                  <h2>概览</h2>
                </div>
              </div>
              <div className="summary-list">
                <div className="summary-row">
                  <span>更新时间</span>
                  <strong>{formatDateTime(dashboard.generated_at)}</strong>
                </div>
                <div className="summary-row">
                  <span>1h 成功率</span>
                  <strong>{formatPercent(summary.success_rate_1h)}</strong>
                </div>
                <div className="summary-row">
                  <span>P95 延迟</span>
                  <strong>{formatLatency(summary.p95_latency_ms_1h)}</strong>
                </div>
                <div className="summary-row">
                  <span>数据接口</span>
                  <strong>{sources.admin_api.latency_ms} ms</strong>
                </div>
              </div>
            </section>
            ) : null}

            {showScope ? (
            <section className="panel fade-up">
              <div className="panel__head panel__head--stacked">
                <div>
                  <span className="panel__eyebrow">监控范围</span>
                  <h2>分组</h2>
                </div>
              </div>
              <div className="scope-panel__section">
                <span className="scope-panel__label">监控分组</span>
                <div className="scope-chip-grid">
                  {scopedGroups.map((group) => (
                    <ScopeChip
                      key={group.id}
                      group={group}
                      configured={configuredProbeGroupIds.has(group.id)}
                    />
                  ))}
                </div>
              </div>
              <div className="scope-panel__section">
                <span className="scope-panel__label">探针</span>
                <p className="scope-panel__text">
                  {dashboard.config.probe_missing_groups.length > 0
                    ? `缺少 ${dashboard.config.probe_missing_groups.length} 个分组 Key`
                    : '已全部配置'}
                </p>
              </div>
            </section>
            ) : null}

            {showGroupPool ? (
            <section className="panel fade-up">
              <div className="panel__head panel__head--stacked">
                <div>
                  <span className="panel__eyebrow">分组账号池</span>
                  <h2>各分组账号情况</h2>
                </div>
                <p>不再只看汇总池，按分组拆开可用、限流、异常与并发。</p>
              </div>
              <div className="group-pool-list">
                {groupsView.length > 0 ? groupsView.map((group) => {
                  const tone = groupTone(group.status)
                  const otherCount = Math.max(
                    group.account_count - group.available_count - group.rate_limited_count - group.error_count,
                    0,
                  )
                  return (
                    <article key={group.id} className="group-pool-card">
                      <div className="group-pool-card__top">
                        <div>
                          <h3>{group.name}</h3>
                          <p>{group.platform} · 默认模型 {group.default_model}</p>
                        </div>
                        <span className={`group-badge is-${tone}`}>{formatPercent(groupAvailability(group), 0)}</span>
                      </div>
                      <div className="group-pool-bar" aria-label={`${group.name} 账号池分布`}>
                        <div className="group-pool-bar__segment is-active" style={{ width: `${percentWidth(group.available_count, group.account_count)}%` }} />
                        <div className="group-pool-bar__segment is-limited" style={{ width: `${percentWidth(group.rate_limited_count, group.account_count)}%` }} />
                        <div className="group-pool-bar__segment is-error" style={{ width: `${percentWidth(group.error_count, group.account_count)}%` }} />
                        <div className="group-pool-bar__segment is-other" style={{ width: `${percentWidth(otherCount, group.account_count)}%` }} />
                      </div>
                      <div className="group-pool-card__stats">
                        <span><b>{formatNumber(group.available_count)}</b> 可用</span>
                        <span><b>{formatNumber(group.rate_limited_count)}</b> 限流</span>
                        <span><b>{formatNumber(group.error_count)}</b> 异常</span>
                        <span><b>{formatNumber(group.concurrency_used)}/{formatNumber(group.concurrency_max)}</b> 并发</span>
                      </div>
                    </article>
                  )
                }) : <div className="model-group-empty">暂无分组账号池数据</div>}
              </div>
            </section>
            ) : null}

            {showInsights ? (
            <section className="panel fade-up">
              <div className="panel__head panel__head--stacked">
                <div>
                  <span className="panel__eyebrow">提醒</span>
                  <h2>告警</h2>
                </div>
              </div>
              <div className="insight-list">
                {dashboard.insights.slice(0, 3).map((insight) => (
                  <article key={`${insight.severity}-${insight.title}`} className="insight-card">
                    <div className="insight-card__top">
                      <InsightBadge severity={insight.severity} />
                      <h3>{insight.title}</h3>
                    </div>
                    <p>{insight.message}</p>
                  </article>
                ))}
              </div>
            </section>
            ) : null}
          </aside>
          ) : null}
        </section>

      </div>
    </main>
  )
}
