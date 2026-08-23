import { CheckCircle2, Folder, LoaderCircle, MinusCircle, PlusCircle, Search, ShieldCheck, Tags, Undo2, X, Sparkles } from 'lucide-react'
import { useEffect, useState } from 'react'
import aiWelcomeIllustration from '../assets/ai-welcome.jpg'

async function requestJson(url, options) {
  const response = await fetch(url, options)
  if (!response.ok) {
    let detail = ''
    try { detail = (await response.json()).detail || '' } catch { detail = '' }
    throw new Error(detail || `请求失败：${response.status}`)
  }
  return response.json()
}

const ACTIONS = [
  { id: 'add_tags', label: '添加标签', icon: PlusCircle },
  { id: 'remove_tags', label: '移除标签', icon: MinusCircle },
  { id: 'move_folder', label: '移动文件夹', icon: Folder },
]

export function MaterialAssistant({ folders, aiStatus, onClose, onResults, onItemsUpdated, onToast }) {
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)
  const [action, setAction] = useState('add_tags')
  const [tagText, setTagText] = useState('')
  const [folderId, setFolderId] = useState('')
  const [plan, setPlan] = useState(null)
  const [changing, setChanging] = useState(false)
  const [execution, setExecution] = useState(null)
  const [useAI, setUseAI] = useState(false)

  useEffect(() => {
    if (!folderId && folders.length) setFolderId(folders[0].id)
  }, [folders, folderId])

  const submit = async event => {
    event?.preventDefault()
    const prompt = query.trim()
    if (!prompt || loading) return
    setLoading(true)
    setError('')
    setPlan(null)
    setExecution(null)
    try {
      const data = await requestJson('/api/assistant/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: prompt, limit: 120, use_ai: useAI }),
      })
      setResult(data)
      onResults(data)
      const proposal = data.proposed_action
      if (proposal?.action) setAction(proposal.action)
      if (proposal?.tags?.length) setTagText(proposal.tags.join('、'))
      if (proposal?.folder?.id) setFolderId(proposal.folder.id)
    } catch (requestError) {
      setError(requestError.message || '素材助手暂时无法完成检索。')
    } finally {
      setLoading(false)
    }
  }

  const buildPlan = async () => {
    if (!result?.items?.length || changing) return
    const tags = tagText.split(/[、,，\n]+/).map(value => value.trim()).filter(Boolean)
    if (action !== 'move_folder' && !tags.length) {
      setError('请先填写要添加或移除的标签。')
      return
    }
    setChanging(true)
    setError('')
    setExecution(null)
    try {
      const data = await requestJson('/api/assistant/plans', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action,
          material_ids: result.items.map(item => item.id),
          tags,
          folder_id: action === 'move_folder' ? folderId : null,
        }),
      })
      setPlan(data)
    } catch (requestError) {
      setError(requestError.message || '无法生成变更预览。')
    } finally {
      setChanging(false)
    }
  }

  const confirmPlan = async () => {
    if (!plan || changing) return
    setChanging(true)
    setError('')
    try {
      const data = await requestJson(`/api/assistant/plans/${plan.id}/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirmation_token: plan.confirmation_token }),
      })
      setExecution({ ...data, planId: plan.id })
      setPlan(null)
      onItemsUpdated(data.updated_items || [])
      onToast(data.message)
    } catch (requestError) {
      setError(requestError.message || '确认修改失败。')
    } finally {
      setChanging(false)
    }
  }

  const undo = async () => {
    if (!execution?.planId || changing) return
    setChanging(true)
    setError('')
    try {
      const data = await requestJson(`/api/assistant/plans/${execution.planId}/undo`, { method: 'POST' })
      onItemsUpdated(data.updated_items || [])
      setExecution({ ...data, planId: null })
      onToast(data.message)
    } catch (requestError) {
      setError(requestError.message || '撤销失败。')
    } finally {
      setChanging(false)
    }
  }

  const pickExample = value => {
    setQuery(value)
    setError('')
  }

  const aiAvailable = aiStatus.configured && aiStatus.ai_mode !== 'off'

  return <section className="material-assistant" aria-label="素材管理助手">
    <header className="assistant-heading">
      <div className="assistant-mark" aria-hidden="true"><span>M</span></div>
      <div>
        <h2>素材助手</h2>
        <p>用一句话找素材；修改操作会先给你看预览。</p>
      </div>
      <div className="assistant-query-mode" role="group" aria-label="素材助手理解方式">
        <button type="button" className={!useAI ? 'active' : ''} onClick={() => setUseAI(false)} aria-pressed={!useAI}>本机 · 不计费</button>
        <button type="button" className={useAI ? 'active' : ''} onClick={() => setUseAI(true)} disabled={!aiAvailable} aria-pressed={useAI} title={aiAvailable ? '本次最多调用 1 次 AI' : '需要先配置并开启 AI'}>AI 理解 · 最多 1 次</button>
      </div>
      <button className="assistant-close" type="button" onClick={onClose} aria-label="关闭素材助手"><X size={17} /></button>
    </header>

    <form className="assistant-query" onSubmit={submit}>
      <Search size={18} />
      <input value={query} onChange={event => setQuery(event.target.value)} placeholder="例如：蓝色背景、偏暗的人像、带樱花的图片" aria-label="向素材助手描述要找的内容" autoFocus />
      <button type="submit" disabled={!query.trim() || loading}>{loading ? <LoaderCircle size={16} /> : '查找'}</button>
    </form>
    {!result ? <div className="assistant-welcome-hero">
      <div className="assistant-welcome-cover" aria-hidden="true">
        <img src={aiWelcomeIllustration} alt="AI 设计灵感助手" />
        <div className="assistant-welcome-glaze"></div>
      </div>
      <div className="assistant-examples">
        <span><Sparkles size={13} /> 试着这样说：</span>
        <button type="button" onClick={() => pickExample('蓝色的背景图片')}>蓝色的背景图片</button>
        <button type="button" onClick={() => pickExample('偏暗的人像')}>偏暗的人像</button>
        <button type="button" onClick={() => pickExample('带花朵的户外照片')}>带花朵的户外照片</button>
      </div>
    </div> : null}

    {error ? <div className="assistant-error" role="alert">{error}<button type="button" onClick={() => setError('')}>知道了</button></div> : null}
    {result ? <div className="assistant-result" aria-live="polite">
      <div className="assistant-result-copy">
        <strong>{result.total ? `找到 ${result.total} 条素材` : '没有找到匹配素材'}</strong>
        <span>理解为：{result.understanding}</span>
        {result.warning ? <small>{result.warning}</small> : <small>{result.used_ai ? 'AI 只用于理解这句话，素材仍从本机数据库检索。' : '本次只查询本机数据库。'}</small>}
      </div>
      {result.total ? <details className="assistant-actions">
        <summary><Tags size={15} /><span>批量整理这 {result.total} 条</span><small>不会提供删除操作</small></summary>
        <div className="assistant-action-body">
          <div className="assistant-action-tabs" role="group" aria-label="批量整理动作">
            {ACTIONS.map(option => {
              const Icon = option.icon
              return <button key={option.id} className={action === option.id ? 'active' : ''} type="button" onClick={() => { setAction(option.id); setPlan(null) }} aria-pressed={action === option.id}><Icon size={14} />{option.label}</button>
            })}
          </div>
          {action === 'move_folder' ? <label className="assistant-field"><span>目标文件夹</span><select value={folderId} onChange={event => { setFolderId(event.target.value); setPlan(null) }}>{folders.map(folder => <option key={folder.id} value={folder.id}>{folder.name}</option>)}</select></label>
            : <label className="assistant-field"><span>{action === 'add_tags' ? '要添加的标签' : '要移除的标签'}</span><input value={tagText} onChange={event => { setTagText(event.target.value); setPlan(null) }} placeholder="多个标签用顿号分开" /></label>}
          {!plan && !execution?.undo_available ? <button className="assistant-preview-button" type="button" onClick={buildPlan} disabled={changing}>{changing ? <LoaderCircle size={15} /> : <ShieldCheck size={15} />}生成变更预览</button> : null}
        </div>
      </details> : null}
    </div> : null}

    {plan ? <section className="assistant-plan" aria-label="批量变更预览">
      <div><ShieldCheck size={18} /><span><strong>等待你的确认</strong><small>{plan.message}</small></span></div>
      <p><b>{plan.preview.action_label}</b><span>将影响 {plan.preview.count} 条素材</span></p>
      <ul>{plan.preview.sample.map(item => <li key={item.id}>{item.title}</li>)}</ul>
      <footer><button type="button" className="assistant-plan-cancel" onClick={() => setPlan(null)}>取消</button><button type="button" className="assistant-plan-confirm" onClick={confirmPlan} disabled={changing}>{changing ? <LoaderCircle size={15} /> : <CheckCircle2 size={15} />}确认修改 {plan.preview.count} 条</button></footer>
    </section> : null}

    {execution?.undo_available ? <div className="assistant-executed"><CheckCircle2 size={17} /><span>{execution.message}</span><button type="button" onClick={undo} disabled={changing}>{changing ? <LoaderCircle size={14} /> : <Undo2 size={14} />}撤销本次修改</button></div> : null}
    {execution?.state === 'undone' ? <div className="assistant-executed undone"><Undo2 size={17} /><span>{execution.message}</span></div> : null}
  </section>
}
