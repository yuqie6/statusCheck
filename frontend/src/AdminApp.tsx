import { useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  EyeOff,
  KeyRound,
  Layers3,
  Loader2,
  LockKeyhole,
  RefreshCw,
  Save,
  Settings2,
  ShieldCheck,
} from 'lucide-react'
import { ThemeToggle } from './components/ThemeToggle'
import { fetchAdminConfig, updateAdminConfig } from './lib/api'
import type { AdminConfig, AdminConfigResponse, AdminGroup } from './types'
import './admin.css'

const adminTokenStorageKey = 'statuscheck_admin_token'
const sourceOptions: Array<{ value: AdminConfig['sub2api_monitor_model_sources'][number]; label: string; note: string }> = [
  { value: 'groups', label: '分组配置', note: '从 default_mapped_model / routing 派生' },
  { value: 'configured', label: '手动列表', note: '使用下方模型列表' },
  { value: 'usage', label: '近期用量', note: '从高频历史模型补充' },
  { value: 'catalog', label: '模型目录', note: '从 /v1/models 目录补充' },
]

function emptyConfig(): AdminConfig {
  return {
    sub2api_group_ids: [],
    sub2api_include_exclusive_groups: false,
    dashboard_cache_ttl_seconds: 60,
    account_scan_enabled: false,
    account_scan_ttl_seconds: 180,
    account_scan_page_size: 100,
    account_scan_max_pages: 0,
    sub2api_monitor_api_key: '',
    sub2api_monitor_group_api_keys: '',
    sub2api_monitor_models: [],
    sub2api_monitor_group_models: {},
    sub2api_monitor_model_sources: ['groups', 'configured'],
    sub2api_monitor_usage_model_limit: 10,
    sub2api_monitor_timeout_seconds: 18,
    sub2api_monitor_max_tokens: 8,
    sub2api_monitor_temperature: 0,
    sub2api_monitor_prompt: 'Reply with OK only.',
    sub2api_monitor_concurrency: 3,
    sub2api_monitor_probe_endpoint: 'chat_completions',
  }
}

function splitModels(text: string): string[] {
  return text
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function modelText(config: AdminConfig): string {
  return config.sub2api_monitor_models.join('\n')
}

function groupModelText(config: AdminConfig, groupId: number): string {
  return (config.sub2api_monitor_group_models[String(groupId)] ?? []).join('\n')
}

function hasGroupModelOverride(config: AdminConfig, groupId: number): boolean {
  return Object.prototype.hasOwnProperty.call(config.sub2api_monitor_group_models, String(groupId))
}

function groupKeyPlaceholder(groups: AdminGroup[]): string {
  const visibleGroups = groups.slice(0, 3)
  if (!visibleGroups.length) return '2=sk-xxx\n6=sk-yyy'
  return visibleGroups.map((group) => `${group.id}=sk-...`).join('\n')
}

function statusText(group: AdminGroup): string {
  return `${group.status}${group.is_exclusive ? ' / exclusive' : ''}`
}

function ConfigCard({
  title,
  subtitle,
  children,
}: {
  title: string
  subtitle: string
  children: React.ReactNode
}) {
  return (
    <section className="admin-card">
      <header className="admin-card__header">
        <div>
          <h2>{title}</h2>
          <p>{subtitle}</p>
        </div>
      </header>
      <div className="admin-card__body">{children}</div>
    </section>
  )
}

export default function AdminApp() {
  const [tokenInput, setTokenInput] = useState(() => sessionStorage.getItem(adminTokenStorageKey) ?? '')
  const [token, setToken] = useState(() => sessionStorage.getItem(adminTokenStorageKey) ?? '')
  const [data, setData] = useState<AdminConfigResponse | null>(null)
  const [config, setConfig] = useState<AdminConfig>(emptyConfig)
  const [modelsDraft, setModelsDraft] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const selectedGroupIds = useMemo(() => new Set(config.sub2api_group_ids), [config.sub2api_group_ids])

  async function load(nextToken = token) {
    if (!nextToken.trim()) return
    setLoading(true)
    setError(null)
    setNotice(null)
    try {
      const response = await fetchAdminConfig(nextToken.trim())
      setData(response)
      setConfig(response.config)
      setModelsDraft(modelText(response.config))
      setToken(nextToken.trim())
      setTokenInput(nextToken.trim())
      sessionStorage.setItem(adminTokenStorageKey, nextToken.trim())
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (token) void load(token)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function patch(next: Partial<AdminConfig>) {
    setConfig((current) => ({ ...current, ...next }))
  }

  function toggleGroup(groupId: number) {
    const next = new Set(config.sub2api_group_ids)
    if (next.has(groupId)) {
      next.delete(groupId)
    } else {
      next.add(groupId)
    }
    patch({ sub2api_group_ids: [...next].sort((a, b) => a - b) })
  }

  function toggleSource(value: AdminConfig['sub2api_monitor_model_sources'][number]) {
    const next = new Set(config.sub2api_monitor_model_sources)
    if (next.has(value)) {
      next.delete(value)
    } else {
      next.add(value)
    }
    patch({ sub2api_monitor_model_sources: [...next] })
  }

  function updateGroupModels(groupId: number, value: string) {
    const next = { ...config.sub2api_monitor_group_models }
    const models = splitModels(value)
    if (models.length > 0) {
      next[String(groupId)] = models
    } else {
      delete next[String(groupId)]
    }
    patch({ sub2api_monitor_group_models: next })
  }

  async function save() {
    if (!token.trim()) {
      setError('请先输入 admin token')
      return
    }
    setSaving(true)
    setError(null)
    setNotice(null)
    try {
      const payload: AdminConfig = {
        ...config,
        sub2api_monitor_models: splitModels(modelsDraft),
      }
      const response = await updateAdminConfig(token.trim(), payload)
      setData(response)
      setConfig(response.config)
      setModelsDraft(modelText(response.config))
      setNotice('配置已保存，并已触发一次 dashboard 刷新。')
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  function logout() {
    sessionStorage.removeItem(adminTokenStorageKey)
    setToken('')
    setTokenInput('')
    setData(null)
    setConfig(emptyConfig())
    setModelsDraft('')
    setNotice(null)
    setError(null)
  }

  const groups = data?.available_groups ?? []
  const modelConfigGroups = groups.filter((group) => selectedGroupIds.size === 0 || selectedGroupIds.has(group.id))
  const envFile = data?.env_file ?? '.env'

  return (
    <main className="admin-page">
      <div className="admin-page__glow admin-page__glow--left" />
      <div className="admin-page__glow admin-page__glow--right" />

      <div className="admin-shell">
        <header className="admin-hero">
          <div>
            <span className="admin-eyebrow">
              <LockKeyhole size={14} />
              Hidden Admin
            </span>
            <h1>StatusCheck 配置管理</h1>
            <p>此页面没有主站入口，只能直接访问 <code>/admin</code>。保存后会写入运行时环境配置，并立刻刷新一次状态快照。</p>
          </div>
          <div className="admin-hero__actions">
            <ThemeToggle />
            {data ? <span className="admin-env-pill">env: {envFile}</span> : null}
            {token ? (
              <button className="admin-button admin-button--ghost" type="button" onClick={logout}>
                <EyeOff size={16} />
                退出
              </button>
            ) : null}
          </div>
        </header>

        {!data ? (
          <section className="admin-login-card">
            <div className="admin-login-card__icon">
              <KeyRound size={26} />
            </div>
            <div>
              <h2>输入 admin token</h2>
              <p>Token 由后端环境变量 <code>ADMIN_TOKEN</code> 控制。</p>
            </div>
            <form
              className="admin-login-form"
              onSubmit={(event) => {
                event.preventDefault()
                void load(tokenInput)
              }}
            >
              <input
                type="password"
                value={tokenInput}
                onChange={(event) => setTokenInput(event.target.value)}
                placeholder="sk-..."
                autoFocus
              />
              <button className="admin-button admin-button--primary" type="submit" disabled={loading || !tokenInput.trim()}>
                {loading ? <Loader2 size={16} className="spin" /> : <ShieldCheck size={16} />}
                进入
              </button>
            </form>
          </section>
        ) : (
          <>
            <div className="admin-toolbar">
              <div>
                <strong>已鉴权</strong>
                <span>当前可管理 {groups.length} 个 Sub2API 分组</span>
              </div>
              <div className="admin-toolbar__actions">
                <button className="admin-button admin-button--ghost" type="button" onClick={() => void load(token)} disabled={loading || saving}>
                  <RefreshCw size={16} className={loading ? 'spin' : ''} />
                  重新读取
                </button>
                <button className="admin-button admin-button--primary" type="button" onClick={() => void save()} disabled={saving || loading}>
                  {saving ? <Loader2 size={16} className="spin" /> : <Save size={16} />}
                  保存并刷新
                </button>
              </div>
            </div>

            {error ? (
              <div className="admin-alert admin-alert--error">
                <AlertTriangle size={16} />
                {error}
              </div>
            ) : null}
            {notice ? (
              <div className="admin-alert admin-alert--success">
                <CheckCircle2 size={16} />
                {notice}
              </div>
            ) : null}

            <section className="admin-grid">
              <ConfigCard title="监控分组" subtitle="控制 dashboard、账号池统计和探针矩阵要看哪些分组。">
                <label className="admin-checkline">
                  <input
                    type="checkbox"
                    checked={config.sub2api_include_exclusive_groups}
                    onChange={(event) => patch({ sub2api_include_exclusive_groups: event.target.checked })}
                  />
                  <span>
                    包含 exclusive 私有组
                    <small>未显式选择分组时，此项决定是否纳入私有组。</small>
                  </span>
                </label>

                <div className="admin-field">
                  <label>显式分组 ID</label>
                  <input
                    value={config.sub2api_group_ids.join(',')}
                    onChange={(event) => {
                      const ids = event.target.value
                        .split(',')
                        .map((item) => Number(item.trim()))
                        .filter((item) => Number.isFinite(item) && item > 0)
                      patch({ sub2api_group_ids: [...new Set(ids)].sort((a, b) => a - b) })
                    }}
                    placeholder="留空 = 自动选择公开组，例如 2,6"
                  />
                </div>

                <div className="group-picker">
                  {groups.map((group) => (
                    <button
                      key={group.id}
                      type="button"
                      className={`group-option ${selectedGroupIds.has(group.id) ? 'is-selected' : ''}`}
                      onClick={() => toggleGroup(group.id)}
                    >
                      <span className="group-option__name">
                        <Layers3 size={14} />
                        {group.name}
                      </span>
                      <span className="group-option__meta">
                        #{group.id} · {group.platform} · {statusText(group)} · {group.account_count} 号
                      </span>
                    </button>
                  ))}
                </div>
              </ConfigCard>

              <ConfigCard title="模型探针" subtitle="控制探针模型来源、请求方式、并发和超时。">
                <div className="source-grid">
                  {sourceOptions.map((option) => (
                    <label key={option.value} className="source-option">
                      <input
                        type="checkbox"
                        checked={config.sub2api_monitor_model_sources.includes(option.value)}
                        onChange={() => toggleSource(option.value)}
                      />
                      <span>
                        {option.label}
                        <small>{option.note}</small>
                      </span>
                    </label>
                  ))}
                </div>

                <div className="admin-field">
                  <label>全局手动模型列表</label>
                  <textarea
                    rows={5}
                    value={modelsDraft}
                    onChange={(event) => setModelsDraft(event.target.value)}
                    placeholder={'gpt-5.4\ngpt-5.4-mini\ngpt-5.3-codex'}
                  />
                  <small>开启“手动列表”来源时生效；没有单独配置的分组会使用这个全局列表。</small>
                </div>

                <div className="admin-field">
                  <label>按分组覆盖手动模型</label>
                  <div className="group-model-grid">
                    {modelConfigGroups.map((group) => {
                      const overridden = hasGroupModelOverride(config, group.id)
                      return (
                        <section key={group.id} className={`group-model-card ${overridden ? 'is-overridden' : ''}`}>
                          <div className="group-model-card__head">
                            <div>
                              <strong>{group.name}</strong>
                              <small>#{group.id} · {group.platform} · {group.account_count} 号</small>
                            </div>
                            <span>{overridden ? '单独配置' : '沿用全局'}</span>
                          </div>
                          <textarea
                            rows={4}
                            value={groupModelText(config, group.id)}
                            onChange={(event) => updateGroupModels(group.id, event.target.value)}
                            placeholder="留空沿用全局；一行一个模型"
                          />
                        </section>
                      )
                    })}
                  </div>
                  <small>这里配置后，该分组会用自己的手动模型列表；留空则继续沿用全局手动模型列表。</small>
                </div>

                <div className="admin-form-grid admin-form-grid--compact">
                  <label className="admin-field">
                    <span>探针接口</span>
                    <select
                      value={config.sub2api_monitor_probe_endpoint}
                      onChange={(event) => patch({ sub2api_monitor_probe_endpoint: event.target.value as AdminConfig['sub2api_monitor_probe_endpoint'] })}
                    >
                      <option value="chat_completions">chat_completions</option>
                      <option value="responses">responses</option>
                    </select>
                  </label>
                  <label className="admin-field">
                    <span>并发</span>
                    <input type="number" min={1} max={50} value={config.sub2api_monitor_concurrency} onChange={(event) => patch({ sub2api_monitor_concurrency: Number(event.target.value) })} />
                  </label>
                  <label className="admin-field">
                    <span>超时秒</span>
                    <input type="number" min={1} max={180} value={config.sub2api_monitor_timeout_seconds} onChange={(event) => patch({ sub2api_monitor_timeout_seconds: Number(event.target.value) })} />
                  </label>
                  <label className="admin-field">
                    <span>用量模型上限</span>
                    <input type="number" min={1} max={200} value={config.sub2api_monitor_usage_model_limit} onChange={(event) => patch({ sub2api_monitor_usage_model_limit: Number(event.target.value) })} />
                  </label>
                </div>
              </ConfigCard>

              <ConfigCard title="探针 Key" subtitle="支持全局 fallback key，也支持按分组指定不同 public API key。">
                <div className="admin-field">
                  <label>全局探针 Key</label>
                  <input
                    type="password"
                    value={config.sub2api_monitor_api_key}
                    onChange={(event) => patch({ sub2api_monitor_api_key: event.target.value })}
                    placeholder="单分组时可作为 fallback；多分组建议用下方映射"
                  />
                </div>
                <div className="admin-field">
                  <label>分组 Key 映射</label>
                  <textarea
                    rows={6}
                    value={config.sub2api_monitor_group_api_keys}
                    onChange={(event) => patch({ sub2api_monitor_group_api_keys: event.target.value })}
                    placeholder={groupKeyPlaceholder(groups)}
                  />
                  <small>格式：<code>2=sk-xxx,6=sk-yyy</code>，也可以一行一个。</small>
                </div>
              </ConfigCard>

              <ConfigCard title="刷新与扫描" subtitle="调整缓存刷新周期，以及是否启用较慢的账号额度扫描。">
                <div className="admin-form-grid admin-form-grid--compact">
                  <label className="admin-field">
                    <span>刷新周期秒</span>
                    <input type="number" min={5} max={3600} value={config.dashboard_cache_ttl_seconds} onChange={(event) => patch({ dashboard_cache_ttl_seconds: Number(event.target.value) })} />
                  </label>
                  <label className="admin-field">
                    <span>Max tokens</span>
                    <input type="number" min={1} max={4096} value={config.sub2api_monitor_max_tokens} onChange={(event) => patch({ sub2api_monitor_max_tokens: Number(event.target.value) })} />
                  </label>
                  <label className="admin-field">
                    <span>Temperature</span>
                    <input type="number" min={0} max={2} step={0.1} value={config.sub2api_monitor_temperature} onChange={(event) => patch({ sub2api_monitor_temperature: Number(event.target.value) })} />
                  </label>
                </div>

                <div className="admin-field">
                  <label>探针 Prompt</label>
                  <input value={config.sub2api_monitor_prompt} onChange={(event) => patch({ sub2api_monitor_prompt: event.target.value })} />
                </div>

                <label className="admin-checkline">
                  <input
                    type="checkbox"
                    checked={config.account_scan_enabled}
                    onChange={(event) => patch({ account_scan_enabled: event.target.checked })}
                  />
                  <span>
                    启用账号额度扫描
                    <small>会分页扫描账号，开启前确认 Sub2API admin API 压力可接受。</small>
                  </span>
                </label>

                <div className="admin-form-grid admin-form-grid--compact">
                  <label className="admin-field">
                    <span>扫描 TTL 秒</span>
                    <input type="number" min={30} value={config.account_scan_ttl_seconds} onChange={(event) => patch({ account_scan_ttl_seconds: Number(event.target.value) })} />
                  </label>
                  <label className="admin-field">
                    <span>分页大小</span>
                    <input type="number" min={1} max={500} value={config.account_scan_page_size} onChange={(event) => patch({ account_scan_page_size: Number(event.target.value) })} />
                  </label>
                  <label className="admin-field">
                    <span>最大页数</span>
                    <input type="number" min={0} value={config.account_scan_max_pages} onChange={(event) => patch({ account_scan_max_pages: Number(event.target.value) })} />
                  </label>
                </div>
              </ConfigCard>
            </section>

            <footer className="admin-footer-note">
              <Settings2 size={15} />
              <span>保存会更新 <code>{envFile}</code>、当前进程环境和内存配置；容器重建后也会从同一份 env 恢复。</span>
            </footer>
          </>
        )}
      </div>
    </main>
  )
}
