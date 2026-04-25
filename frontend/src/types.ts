export type InsightSeverity = 'critical' | 'warning' | 'info'

export interface DashboardSummary {
  total_accounts: number
  available_accounts: number
  rate_limited_accounts: number
  error_accounts: number
  overload_accounts: number
  total_api_keys?: number
  active_api_keys?: number
  active_users?: number
  today_requests?: number
  today_cost?: number
  total_cost?: number
  rpm?: number
  tpm?: number
  current_requests_per_minute: number
  current_active_requests: number
  success_rate_1h: number
  error_rate_1h: number
  avg_latency_ms_1h: number
  p95_latency_ms_1h: number
  capacity_used: number
  capacity_max: number
  capacity_utilization: number
  health_score: number
  stats_updated_at: string | null
  snapshot_generated_at: string | null
  qps?: { current: number; avg: number; peak: number }
  tps?: { current: number; avg: number; peak: number }
}

export interface QuotaEstimate {
  enabled: boolean
  coverage_accounts: number
  coverage_ratio: number
  limit_usd: number | null
  used_usd: number | null
  remaining_usd: number | null
  note: string
}

export interface DailyTrendPoint {
  date: string
  requests: number
  cost: number
  tokens?: number
}

export interface ModelRow {
  group_id: number
  group_name: string
  model: string
  provider: string
  requests_7d?: number
  cost_7d?: number
  tokens_7d?: number
  catalog_available: boolean | null
  probe_status: string
  probe_latency_ms: number | null
  probe_ttft_ms: number | null
  probe_http_status: number | null
  probe_error: string | null
  probe_streaming: boolean | null
  observed: boolean
}

export interface ModelGroupSection {
  group_id: number
  group_name: string
  has_probe_key: boolean
  status: string
  models: ModelRow[]
}

export interface GroupRow {
  id: number
  name: string
  platform: string
  default_model: string
  account_count: number
  available_count: number
  rate_limited_count: number
  error_count: number
  concurrency_used: number
  concurrency_max: number
  today_cost?: number
  total_cost?: number
  sort_order: number
  status: string
}

export interface PlatformRow {
  platform: string
  total_accounts: number
  available_count: number
  rate_limited_count: number
  error_count: number
  availability_ratio: number
}

export interface Insight {
  severity: InsightSeverity
  title: string
  message: string
}

export interface PoolSummary {
  status_breakdown: Record<string, number>
  platforms: PlatformRow[]
  groups: GroupRow[]
  capacity: {
    used: number
    max: number
    utilization: number
  }
}

export interface ProbeGroupRef {
  id: number
  name: string
}

export interface GroupScopeInfo {
  enabled: boolean
  group_ids: number[]
  group_names: string[]
  explicit_ids: number[]
  include_exclusive_groups: boolean
}

export type PublicDashboardField =
  | 'costs'
  | 'request_volume'
  | 'token_volume'
  | 'api_keys'
  | 'users'
  | 'quota'
  | 'model_usage'
  | 'ops_counts'

export type PublicDashboardCard =
  | 'metric_monitor_items'
  | 'metric_healthy_models'
  | 'metric_abnormal_models'
  | 'metric_probe_groups'
  | 'model_groups'
  | 'snapshot'
  | 'scope'
  | 'group_pool'
  | 'insights'

export interface DashboardResponse {
  generated_at: string
  config: {
    monitor_key_configured: boolean
    monitor_probe_endpoint: string
    monitor_model_sources: string[]
    account_scan_enabled: boolean
    refresh_interval_ms: number
    group_scope: GroupScopeInfo
    probe_groups: ProbeGroupRef[]
    probe_missing_groups: ProbeGroupRef[]
    public_dashboard_fields: PublicDashboardField[]
    public_dashboard_cards: PublicDashboardCard[]
  }
  summary: DashboardSummary
  quota_estimate?: QuotaEstimate
  timeseries?: {
    daily: DailyTrendPoint[]
  }
  models: ModelRow[]
  model_groups: ModelGroupSection[]
  pool: PoolSummary
  ops: {
    overview: {
      success_count?: number
      error_count_total?: number
      request_count_total?: number
      upstream_error_rate: number
      upstream_error_count_excl_429_529?: number
    }
    duration: Record<string, number>
  }
  insights: Insight[]
  sources: {
    admin_api: { ok: boolean; mode: string; latency_ms: number }
    availability_summary: { ok: boolean; latency_ms: number; enabled: boolean; timestamp: string | null }
    model_probe: {
      ok: boolean
      configured: boolean
      catalog_loaded: boolean
      probed_models: number
      configured_groups: ProbeGroupRef[]
      missing_groups: ProbeGroupRef[]
    }
  }
}


export type AdminModelSource = 'groups' | 'configured' | 'usage' | 'catalog'

export interface AdminConfig {
  sub2api_group_ids: number[]
  sub2api_include_exclusive_groups: boolean
  dashboard_cache_ttl_seconds: number
  account_scan_enabled: boolean
  account_scan_ttl_seconds: number
  account_scan_page_size: number
  account_scan_max_pages: number
  sub2api_monitor_api_key: string
  sub2api_monitor_group_api_keys: string
  sub2api_monitor_models: string[]
  sub2api_monitor_group_models: Record<string, string[]>
  sub2api_monitor_model_sources: AdminModelSource[]
  sub2api_monitor_usage_model_limit: number
  sub2api_monitor_timeout_seconds: number
  sub2api_monitor_max_tokens: number
  sub2api_monitor_temperature: number
  sub2api_monitor_prompt: string
  sub2api_monitor_concurrency: number
  sub2api_monitor_probe_endpoint: 'chat_completions' | 'responses'
  public_dashboard_fields: PublicDashboardField[]
  public_dashboard_cards: PublicDashboardCard[]
}

export interface AdminGroup {
  id: number
  name: string
  platform: string
  status: string
  is_exclusive: boolean
  account_count: number
  default_model: string
}

export interface AdminConfigResponse {
  config: AdminConfig
  available_groups: AdminGroup[]
  env_file: string
  generated_at: string
}
