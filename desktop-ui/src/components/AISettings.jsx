import { Activity, AlertTriangle, Ban, Bot, Check, ChevronDown, ChevronUp, Clock3, FileDown, Hand, KeyRound, LoaderCircle, Pause, Play, RefreshCw, RotateCcw, ScrollText, Server, ShieldCheck, X, Zap } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

const MODES = [
  { id: 'off', label: '关闭', detail: '不产生 AI 请求', icon: Ban },
  { id: 'manual', label: '手动批量', detail: '点击后统一整理', icon: Hand },
  { id: 'auto', label: '自动批量', detail: '按策略自动整理', icon: Zap },
]

const EXPORT_POLICIES = [
  { id: 'collect_only', label: '仅收藏' },
  { id: 'on_demand', label: '按需生成' },
  { id: 'auto', label: '自动生成' },
]

const BATCH_STATE = {
  queued: '等待开始', running: '正在整理', stopping: '完成当前请求后暂停', paused: '已暂停',
  completed: '已完成', partial: '部分失败', failed: '处理失败',
}

export function AISettings({ status, folders, activeFolderId, onSave, onSaveProcessing, onStartBatch, onPauseBatch, onResumeBatch, onRetryBatch, onClose }) {
  const [baseUrl, setBaseUrl] = useState(status.base_url || '')
  const [model, setModel] = useState(status.model || '')
  const [apiKey, setApiKey] = useState('')
  const [mode, setMode] = useState(status.ai_mode || 'off')
  const [idleMinutes, setIdleMinutes] = useState(status.auto_idle_minutes ?? 10)
  const [dailyLimit, setDailyLimit] = useState(status.daily_request_limit || 100)
  const [batchSize, setBatchSize] = useState(status.batch_size || 100)
  const [exportPolicy, setExportPolicy] = useState(status.export_policy || 'on_demand')
  const [exportFormats, setExportFormats] = useState(status.export_formats || ['pdf', 'docx'])
  const [includeExisting, setIncludeExisting] = useState(false)
  const [scope, setScope] = useState(activeFolderId ? 'folder' : 'all_unprocessed')
  const [batchFolderId, setBatchFolderId] = useState(activeFolderId || 'inbox')
  const [savingProvider, setSavingProvider] = useState(false)
  const [savingPolicy, setSavingPolicy] = useState(false)
  const [startingBatch, setStartingBatch] = useState(false)
  const [batchAction, setBatchAction] = useState('')
  const [saved, setSaved] = useState('')
  const [showLogs, setShowLogs] = useState(false)
  const [logs, setLogs] = useState([])
  const [logsLoading, setLogsLoading] = useState(false)
  const [logsError, setLogsError] = useState('')
  const statusFormatsKey = (status.export_formats || []).join(',')

  useEffect(() => {
    setBaseUrl(status.base_url || '')
    setModel(status.model || '')
    setMode(status.ai_mode || 'off')
    setIdleMinutes(status.auto_idle_minutes ?? 10)
    setDailyLimit(status.daily_request_limit || 100)
    setBatchSize(status.batch_size || 100)
    setExportPolicy(status.export_policy || 'on_demand')
    setExportFormats(status.export_formats || ['pdf', 'docx'])
  }, [status.base_url, status.model, status.ai_mode, status.auto_idle_minutes, status.daily_request_limit, status.batch_size, status.export_policy, statusFormatsKey])

  const availableModels = status.available_models || []
  const usage = status.usage_today || { requests: 0, total_tokens: 0 }
  const recentBatches = status.recent_batches || []
  const activeBatch = useMemo(() => recentBatches.find(batch => ['queued', 'running', 'stopping', 'paused'].includes(batch.state)), [recentBatches])
  const savedFormats = status.export_formats || ['pdf', 'docx']
  const policyDirty = mode !== (status.ai_mode || 'off')
    || Number(idleMinutes) !== Number(status.auto_idle_minutes ?? 10)
    || Number(dailyLimit) !== Number(status.daily_request_limit || 100)
    || Number(batchSize) !== Number(status.batch_size || 100)
    || exportPolicy !== (status.export_policy || 'on_demand')
    || [...exportFormats].sort().join(',') !== [...savedFormats].sort().join(',')

  const flashSaved = value => {
    setSaved(value)
    window.setTimeout(() => setSaved(''), 1800)
  }

  const saveProvider = async event => {
    event.preventDefault()
    setSavingProvider(true)
    try {
      await onSave({ base_url: baseUrl, model, api_key: apiKey || null })
      setApiKey('')
      flashSaved('provider')
    } catch {
      // App owns the visible request error.
    } finally { setSavingProvider(false) }
  }

  const savePolicy = async () => {
    setSavingPolicy(true)
    try {
      await onSaveProcessing({
        ai_mode: mode,
        auto_idle_minutes: Number(idleMinutes),
        daily_request_limit: Number(dailyLimit),
        batch_size: Number(batchSize),
        export_policy: exportPolicy,
        export_formats: exportFormats,
        include_existing_on_auto: includeExisting,
      })
      setIncludeExisting(false)
      flashSaved('policy')
    } catch {
      // App owns the visible request error.
    } finally { setSavingPolicy(false) }
  }

  const startBatch = async () => {
    setStartingBatch(true)
    try {
      await onStartBatch({ scope, folder_id: scope === 'folder' ? batchFolderId : null, recent_hours: 24, batch_size: Number(batchSize), force: false })
    } catch {
      // App owns the visible request error.
    } finally { setStartingBatch(false) }
  }

  const runBatchAction = async (action, batchId) => {
    setBatchAction(`${action}-${batchId}`)
    try {
      if (action === 'pause') await onPauseBatch(batchId)
      else if (action === 'resume') await onResumeBatch(batchId)
      else await onRetryBatch(batchId)
    } catch {
      // App owns the visible request error.
    } finally { setBatchAction('') }
  }

  const loadLogs = async () => {
    setLogsLoading(true)
    setLogsError('')
    try {
      const response = await fetch('/api/ai/logs?limit=120')
      if (!response.ok) throw new Error(`日志请求失败（${response.status}）`)
      const payload = await response.json()
      setLogs(payload.items || [])
    } catch (error) {
      setLogsError(error.message || '暂时无法读取日志')
    } finally { setLogsLoading(false) }
  }

  const toggleLogs = () => {
    setShowLogs(value => {
      const next = !value
      if (next) loadLogs()
      return next
    })
  }

  useEffect(() => {
    loadLogs()
  }, [])

  useEffect(() => {
    if (!showLogs) return undefined
    const timer = window.setInterval(loadLogs, 5000)
    return () => window.clearInterval(timer)
  }, [showLogs])

  const toggleFormat = format => setExportFormats(current => current.includes(format) ? current.filter(value => value !== format) : [...current, format])
  const usagePercent = Math.min(100, dailyLimit ? Math.round((usage.requests || 0) / dailyLimit * 100) : 0)
  const latestRequest = logs.find(log => log.kind === 'request')
  const tokenLabel = value => Number(value || 0).toLocaleString('zh-CN')

  return <section className="ai-settings automation-settings" aria-labelledby="ai-settings-title">
    <div className="ai-settings-heading">
      <div><h2 id="ai-settings-title"><Bot size={18} />自动化与 AI</h2><p>连接信息和运行方式彼此独立。保存 API 不会分析任何素材，只有下面的模式或按钮可以启动请求。</p></div>
      <button className="icon-button" type="button" onClick={onClose} title="关闭自动化设置" aria-label="关闭自动化设置"><X size={17} /></button>
    </div>

    {status.ai_alert ? <div className="ai-alert-banner" role="alert"><AlertTriangle size={17} /><div><strong>AI 处理已暂停</strong><p>{status.ai_alert.message}</p><small>错误已记录；修复模型或额度后，可在下方重试失败项。</small></div></div> : null}

    <section className="usage-summary" aria-label="AI 用量概览">
      <div className="usage-summary-main"><div><span>今日 AI 用量</span><strong>{usage.requests || 0}<small> / {dailyLimit} 次请求</small></strong></div><span className="usage-summary-state">{usagePercent >= 100 ? '已触达上限' : usagePercent ? `已使用 ${usagePercent}%` : '尚未使用'}</span></div>
      <div className="usage-meter" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow={usagePercent} aria-label="今日 AI 请求用量"><span style={{ transform: `scaleX(${usagePercent / 100})` }} /></div>
      <div className="usage-summary-meta"><span>{tokenLabel(usage.total_tokens)} Tokens</span>{latestRequest ? <span>最近一次：{latestRequest.total_tokens ? `${tokenLabel(latestRequest.total_tokens)} Tokens` : '未返回用量'} · {latestRequest.model || '模型未记录'}</span> : <span>最近一次：暂无 AI 请求记录</span>}</div>
    </section>

    <section className="activity-section" aria-label="AI 运行记录">
      <div className="automation-section-title"><div><strong>运行记录</strong><span>每次请求、批次状态和 Token 用量都会单独显示</span></div><div className="batch-header-tools"><button className="logs-toggle" type="button" onClick={toggleLogs} aria-expanded={showLogs}><ScrollText size={14} /><span>{showLogs ? '收起记录' : '查看记录'}</span><ChevronDown size={14} className={showLogs ? 'is-open' : ''} /></button><Activity size={17} /></div></div>
      {showLogs ? <section className="ai-log-panel">
        <div className="ai-log-heading"><div><strong>AI 运行记录</strong><small>每次请求、批次状态和 Token 用量都会单独显示</small></div><div className="ai-log-heading-actions"><button type="button" onClick={loadLogs} disabled={logsLoading} title="刷新日志" aria-label="刷新日志">{logsLoading ? <LoaderCircle size={14} /> : <RefreshCw size={14} />}</button><button type="button" onClick={toggleLogs} title="收起运行记录" aria-label="收起运行记录"><ChevronUp size={14} /></button></div></div>
        {logsError ? <p className="ai-log-error">{logsError}</p> : null}
        {logsLoading && !logs.length ? <p className="ai-log-empty">正在读取日志…</p> : null}
        {!logsLoading && !logsError && !logs.length ? <p className="ai-log-empty">还没有可显示的 AI 日志。</p> : null}
        {logs.length ? <div className="ai-log-list">{logs.map((log, index) => <article className={`ai-log-entry ${log.level || 'info'}`} key={`${log.created_at || 'unknown'}-${log.kind}-${log.material_id || index}`}><span className="ai-log-level" aria-hidden="true" /><div><div className="ai-log-entry-head"><strong>{log.kind === 'quota' ? '额度保护' : log.kind === 'batch' ? '批次状态' : log.kind === 'item' ? '任务提示' : 'AI 请求'}</strong><time>{log.created_at ? new Date(log.created_at * 1000).toLocaleString('zh-CN') : '—'}</time></div><p>{log.message}</p>{log.title ? <small>{log.title}</small> : null}{log.total_tokens ? <small className="ai-log-usage">本次 {tokenLabel(log.total_tokens)} Tokens{log.input_tokens || log.output_tokens ? ` · 输入 ${tokenLabel(log.input_tokens)} / 输出 ${tokenLabel(log.output_tokens)}` : ''}{log.model ? ` · ${log.model}` : ''}</small> : null}</div></article>)}</div> : null}
      </section> : null}
    </section>

    <section className="automation-section">
      <div className="automation-section-title"><div><strong>AI 介入方式</strong><span>新用户默认关闭，单条分析始终需要主动点击</span></div><span className={`automation-status ${mode}`}>{MODES.find(item => item.id === mode)?.label}</span></div>
      <div className="mode-segment" role="radiogroup" aria-label="AI 介入方式">{MODES.map(option => {
        const Icon = option.icon
        return <button key={option.id} type="button" role="radio" aria-checked={mode === option.id} className={mode === option.id ? 'active' : ''} onClick={() => setMode(option.id)}><Icon size={16} /><span><strong>{option.label}</strong><small>{option.detail}</small></span></button>
      })}</div>
      <div className="automation-options">
        {mode === 'auto' ? <label><span>{Number(idleMinutes) === 0 ? '自动触发' : '静默等待'}</span><select value={idleMinutes} onChange={event => setIdleMinutes(event.target.value)}><option value="0">立即（入队后处理）</option><option value="5">5 分钟</option><option value="10">10 分钟</option><option value="20">20 分钟</option><option value="30">30 分钟</option></select></label> : null}
        <label><span>每日安全上限</span><input type="number" min="1" max="10000" value={dailyLimit} onChange={event => setDailyLimit(event.target.value)} /></label>
        {mode === 'auto' && status.ai_mode !== 'auto' ? <label className="check-option"><input type="checkbox" checked={includeExisting} onChange={event => setIncludeExisting(event.target.checked)} /><span>同时处理现有未分析素材</span></label> : null}
      </div>
    </section>

    <section className="automation-section export-policy">
      <div className="automation-section-title"><div><strong>网页离线文档</strong><span>这项功能只使用本机计算，不会调用 AI</span></div><FileDown size={17} /></div>
      <div className="export-segment" role="radiogroup" aria-label="网页离线文档策略">{EXPORT_POLICIES.map(option => <button key={option.id} type="button" role="radio" aria-checked={exportPolicy === option.id} className={exportPolicy === option.id ? 'active' : ''} onClick={() => setExportPolicy(option.id)}>{option.label}</button>)}</div>
      {exportPolicy === 'auto' ? <div className="format-options"><label><input type="checkbox" checked={exportFormats.includes('pdf')} onChange={() => toggleFormat('pdf')} />PDF</label><label><input type="checkbox" checked={exportFormats.includes('docx')} onChange={() => toggleFormat('docx')} />Word</label></div> : null}
    </section>

    <div className="policy-save-row"><span><ShieldCheck size={14} />今天已请求 {usage.requests || 0} / {dailyLimit} 次{usage.total_tokens ? `，共 ${usage.total_tokens.toLocaleString()} Tokens` : ''}</span><button type="button" onClick={savePolicy} disabled={savingPolicy || !policyDirty || (exportPolicy === 'auto' && !exportFormats.length)}>{savingPolicy ? <LoaderCircle size={14} /> : saved === 'policy' ? <Check size={14} /> : <ShieldCheck size={14} />}{savingPolicy ? '正在保存' : saved === 'policy' ? '策略已保存' : policyDirty ? '保存运行策略' : '策略已生效'}</button></div>

    {mode !== 'off' ? <section className="automation-section batch-console">
      <div className="automation-section-title"><div><strong>批量整理</strong><span>{status.pending_items || 0} 条素材等待首次 AI 整理</span></div><Activity size={17} /></div>
      <div className="batch-launcher"><label><span>整理范围</span><select value={scope} onChange={event => setScope(event.target.value)}><option value="all_unprocessed">所有未分析素材</option><option value="recent">最近 24 小时</option><option value="folder">指定文件夹</option></select></label>{scope === 'folder' ? <label><span>文件夹</span><select value={batchFolderId} onChange={event => setBatchFolderId(event.target.value)}>{folders.map(folder => <option key={folder.id} value={folder.id}>{folder.name}</option>)}</select></label> : null}<label><span>本批分析数量</span><input className="batch-size-input" type="number" min="1" max="10000" step="1" value={batchSize} onChange={event => setBatchSize(event.target.value)} aria-describedby="batch-size-help" /><small id="batch-size-help">最多 {status.pending_items || 0} 条；每日安全上限仍为 {dailyLimit} 次</small></label><button type="button" onClick={startBatch} disabled={!status.configured || status.ai_mode === 'off' || policyDirty || startingBatch || !status.pending_items || Boolean(activeBatch)}>{startingBatch ? <LoaderCircle size={15} /> : <Play size={15} />}{startingBatch ? '正在创建批次' : '开始批量整理'}</button></div>
      {!status.configured ? <p className="automation-warning">先在下方保存 AI 接口，批量按钮才会启用。</p> : null}
      {status.configured && policyDirty ? <p className="automation-warning">先保存上面的运行策略，再启动批量整理。</p> : null}
      {recentBatches.length ? <div className="batch-list">{recentBatches.slice(0, 3).map(batch => {
        const percent = batch.total_items ? Math.round(batch.processed_items / batch.total_items * 100) : 0
        const canPause = ['queued', 'running'].includes(batch.state)
        const canResume = ['paused', 'stopping'].includes(batch.state)
        return <div key={batch.id}><span className="batch-state-icon"><Clock3 size={14} /></span><div><strong>{batch.trigger_type === 'single' ? '单条分析' : batch.trigger_type === 'auto' ? '自动批次' : '手动批次'}</strong><small><span>{BATCH_STATE[batch.state] || batch.state}</span><span>{batch.processed_items}/{batch.total_items}</span><span>预计 {batch.estimated_requests} 次请求</span></small><div className="batch-progress"><i style={{ transform: `scaleX(${percent / 100})` }} /></div></div>{canPause ? <button type="button" onClick={() => runBatchAction('pause', batch.id)} disabled={Boolean(batchAction)} title="暂停批次" aria-label="暂停批次">{batchAction === `pause-${batch.id}` ? <LoaderCircle size={14} /> : <Pause size={14} />}</button> : canResume ? <button type="button" onClick={() => runBatchAction('resume', batch.id)} disabled={Boolean(batchAction)} title="恢复批次" aria-label="恢复批次">{batchAction === `resume-${batch.id}` ? <LoaderCircle size={14} /> : <RotateCcw size={14} />}</button> : <span className="batch-complete"><Check size={14} /></span>}</div>
      })}</div> : null}
    </section> : null}

    {recentBatches.filter(batch => Number(batch.retryable_items || batch.failed_items) > 0 && ['paused', 'partial', 'failed'].includes(batch.state)).map(batch => <button key={`retry-failed-${batch.id}`} className="batch-retry-button" type="button" onClick={() => runBatchAction('retry', batch.id)} disabled={Boolean(batchAction)}><RotateCcw size={14} />{batchAction === `retry-${batch.id}` ? '正在重试失败项' : `重试失败项（${batch.retryable_items || batch.failed_items}）`}</button>)}
    <details className="provider-settings" open={!status.configured}>
      <summary><span><Server size={15} />AI 接口</span><small>{status.configured ? `${status.model} 已连接` : '尚未配置'}</small></summary>
      <form onSubmit={saveProvider}>
        <label><span><Server size={14} />API 地址</span><input type="url" value={baseUrl} onChange={event => setBaseUrl(event.target.value)} placeholder="https://你的服务地址/v1" required /></label>
        <label><span><Bot size={14} />模型名称</span><input value={model} onChange={event => setModel(event.target.value)} placeholder="支持图像输入的模型名称" required />{availableModels.length ? <small className="ai-model-hint">已检测到：{availableModels.join('、')}</small> : null}</label>
        <label><span><KeyRound size={14} />API Key</span><input type="password" value={apiKey} onChange={event => setApiKey(event.target.value)} placeholder={status.api_key_configured ? '已安全保存，留空表示不修改' : '输入 API Key'} /></label>
        <button type="submit" disabled={savingProvider}>{savingProvider ? <LoaderCircle size={14} /> : saved === 'provider' ? <Check size={14} /> : <KeyRound size={14} />}{savingProvider ? '保存中' : saved === 'provider' ? '已保存' : '保存连接'}</button>
      </form>
      <p className="ai-security">保存时只验证地址和模型。密钥使用当前 Windows 用户的 DPAPI 加密，不会因此启动素材分析。</p>
    </details>
  </section>
}
