import { ChevronDown, ChevronRight, Clapperboard, FileText, Folder, FolderPlus, Image, Inbox, Library, ShieldCheck, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'

const groups = ['图片', '视频', '文档', '网页']
const groupIcon = { 图片: Image, 视频: Clapperboard, 文档: FileText, 网页: Library }

const batchStateLabel = { queued: '等待开始', running: '正在整理', stopping: '即将暂停', paused: '已暂停', completed: '已完成', partial: '部分完成', failed: '处理失败' }
const activeBatchStates = new Set(['queued', 'running', 'stopping', 'paused'])

function formatRemaining(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return '正在计算…'
  const rounded = Math.max(1, Math.ceil(seconds / 60))
  if (rounded < 60) return `约 ${rounded} 分钟`
  const hours = Math.floor(rounded / 60)
  const minutes = rounded % 60
  return minutes ? `约 ${hours} 小时 ${minutes} 分钟` : `约 ${hours} 小时`
}

export function Sidebar({ categories, folders, activeCategory, activeFolder, view, trashCount, aiStatus, draggingMaterial, activeDropTarget, onPickView, onPickCategory, onPickFolder, onCreateFolder, onDropMaterial, onOpenAI }) {
  const [creating, setCreating] = useState(false)
  const [folderName, setFolderName] = useState('')
  const [dropTarget, setDropTarget] = useState('')
  const [clock, setClock] = useState(() => Date.now())
  const [collapsedGroups, setCollapsedGroups] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem('myknow-collapsed-category-groups') || 'null')
      return new Set(Array.isArray(saved) ? saved : groups)
    } catch {
      return new Set(groups)
    }
  })
  const visibleDropTarget = activeDropTarget || dropTarget
  const recentBatches = aiStatus?.recent_batches || []
  const batch = recentBatches.find(item => activeBatchStates.has(item.state)) || recentBatches[0]
  const batchIsLive = Boolean(batch && activeBatchStates.has(batch.state))

  useEffect(() => {
    if (!batchIsLive) return undefined
    const timer = window.setInterval(() => setClock(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [batchIsLive, batch?.id])

  const processedItems = Math.max(0, Number(batch?.processed_items) || 0)
  const totalItems = Math.max(0, Number(batch?.total_items) || 0)
  const batchPercent = totalItems ? Math.min(100, Math.round(processedItems / totalItems * 100)) : 0
  const elapsedSeconds = batch?.started_at ? Math.max(0, clock / 1000 - Number(batch.started_at)) : 0
  const rate = elapsedSeconds > 0 ? processedItems / elapsedSeconds : 0
  const eta = batch?.state === 'completed' || batch?.state === 'partial' || batch?.state === 'failed'
    ? '本批已结束'
    : batch?.state === 'paused' ? '暂停中，可到整理中心继续'
      : formatRemaining(rate > 0 ? (totalItems - processedItems) / rate : Number.NaN)

  useEffect(() => {
    if (!activeCategory) return
    const activeGroup = groups.find(group => activeCategory === group || categories.some(item => item.category === group && item.subcategory === activeCategory))
    if (activeGroup && collapsedGroups.has(activeGroup)) {
      setCollapsedGroups(current => {
        const next = new Set(current)
        next.delete(activeGroup)
        localStorage.setItem('myknow-collapsed-category-groups', JSON.stringify([...next]))
        return next
      })
    }
  }, [activeCategory, categories])

  const toggleGroup = group => setCollapsedGroups(current => {
    const next = new Set(current)
    if (next.has(group)) next.delete(group)
    else next.add(group)
    localStorage.setItem('myknow-collapsed-category-groups', JSON.stringify([...next]))
    return next
  })

  const createFolder = async event => {
    event.preventDefault()
    const name = folderName.trim()
    if (!name) return
    try {
      await onCreateFolder(name)
      setFolderName('')
      setCreating(false)
    } catch { /* App displays the API error. */ }
  }

  const dropProps = (key, target) => ({
    onDragEnter: event => {
      if (!draggingMaterial) return
      event.preventDefault()
      setDropTarget(key)
    },
    onDragOver: event => {
      if (!draggingMaterial) return
      event.preventDefault()
      event.dataTransfer.dropEffect = 'move'
      if (dropTarget !== key) setDropTarget(key)
    },
    onDragLeave: event => {
      if (!event.currentTarget.contains(event.relatedTarget)) setDropTarget(current => current === key ? '' : current)
    },
    onDrop: event => {
      if (!draggingMaterial) return
      event.preventDefault()
      const materialId = event.dataTransfer.getData('application/x-muse-material')
      setDropTarget('')
      if (materialId) onDropMaterial(materialId, target)
    },
  })

  const pickAll = () => onPickView('library')

  return <aside className={`category-rail ${draggingMaterial ? 'drag-session' : ''}`} onDragEnd={() => setDropTarget('')}>
    <div className="rail-logo"><img className="brand-icon" src="/favicon.png" alt="" /><div><b>myknow</b><small>本机知识与素材库</small></div></div>
    <button className={`library-root ${view === 'library' && !activeCategory && !activeFolder ? 'selected-tree' : ''}`} onClick={pickAll} type="button"><Library size={17} />全部素材</button>

    <div className="rail-section-heading"><p className="rail-label">文件夹</p><button type="button" onClick={() => setCreating(value => !value)} title="新建文件夹" aria-label="新建文件夹"><FolderPlus size={15} /></button></div>
    {creating ? <form className="folder-create" onSubmit={createFolder}><input value={folderName} onChange={event => setFolderName(event.target.value)} placeholder="文件夹名称" autoFocus /><button type="submit">创建</button></form> : null}
    <div className="folder-list">
      {folders.map(folder => {
        const Icon = folder.id === 'inbox' ? Inbox : Folder
        const key = `folder-${folder.id}`
        return <button key={folder.id} type="button" data-drop-target={`folder:${folder.id}`} {...dropProps(key, { kind: 'folder', folderId: folder.id, label: folder.name })} className={`${activeFolder === folder.id ? 'selected-tree' : ''} ${visibleDropTarget === `folder:${folder.id}` || dropTarget === key ? 'drop-hover' : ''}`} onClick={() => onPickFolder(folder.id)}><Icon size={15} /><span>{visibleDropTarget === `folder:${folder.id}` || dropTarget === key ? `放到 ${folder.name}` : folder.name}</span><em>{folder.count}</em></button>
      })}
    </div>
    <button className={`trash-root ${view === 'trash' ? 'selected-tree' : ''} ${visibleDropTarget === 'trash' ? 'drop-hover' : ''}`} data-drop-target="trash" {...dropProps('trash', { kind: 'trash', label: '回收站' })} onClick={() => onPickView('trash')} type="button">
      <span className="trash-visual"><Trash2 size={18} /><span>{visibleDropTarget === 'trash' ? '松开放入回收站' : '回收站'}</span></span><em>{trashCount}</em>
    </button>

    <p className="rail-label smart-category-label">智能分类</p>
    <div className="smart-category-list">
    {groups.map(group => {
      const Icon = groupIcon[group]
      const children = categories.filter(item => item.category === group)
      const groupCount = children.reduce((total, item) => total + (item.count || 0), 0)
      const groupKey = `category-${group}`
      return <div className="tree-group" key={group}>
        <div className="tree-group-head">
          <button className={`tree-group-button ${activeCategory === group ? 'selected-tree' : ''} ${visibleDropTarget === `category:${group}` || dropTarget === groupKey ? 'drop-hover' : ''}`} data-drop-target={`category:${group}`} {...dropProps(groupKey, { kind: 'category', category: group, subcategory: null, label: group })} onClick={() => onPickCategory(group)} type="button"><Icon size={16} /><span>{visibleDropTarget === `category:${group}` || dropTarget === groupKey ? `归类为 ${group}` : group}</span><em>{groupCount}</em></button>
          <button className="tree-group-toggle" type="button" onClick={() => toggleGroup(group)} aria-expanded={!collapsedGroups.has(group)} aria-controls={`category-children-${group}`} title={collapsedGroups.has(group) ? `展开${group}标签` : `收起${group}标签`} aria-label={collapsedGroups.has(group) ? `展开${group}标签` : `收起${group}标签`}>{collapsedGroups.has(group) ? <ChevronRight size={14} /> : <ChevronDown size={14} />}</button>
        </div>
        {!collapsedGroups.has(group) ? <div id={`category-children-${group}`} className="tree-group-children">{children.map(child => {
          const childKey = `category-${group}-${child.subcategory}`
          return <button key={`${group}-${child.subcategory}`} data-drop-target={`category:${group}:${child.subcategory}`} {...dropProps(childKey, { kind: 'category', category: group, subcategory: child.subcategory, label: child.subcategory })} onClick={() => onPickCategory(child.subcategory)} className={`tree-child ${activeCategory === child.subcategory ? 'selected-tree' : ''} ${visibleDropTarget === `category:${group}:${child.subcategory}` || dropTarget === childKey ? 'drop-hover' : ''}`} type="button"><span>{visibleDropTarget === `category:${group}:${child.subcategory}` || dropTarget === childKey ? `归类为 ${child.subcategory}` : child.subcategory}</span><em>{child.count}</em></button>
        })}</div> : null}
      </div>
    })}
    </div>
    {batch ? <section className={`ai-progress-card ${batchIsLive ? 'is-live' : 'is-done'}`} aria-label="AI 批量解析进度">
      <div className="ai-progress-heading"><div><span>AI 批量进度</span><strong>{batchStateLabel[batch.state] || batch.state}</strong></div><button type="button" onClick={onOpenAI} title="打开整理中心" aria-label="打开整理中心"><ChevronRight size={14} /></button></div>
      <div className="ai-progress-meta"><span>{processedItems} / {totalItems} 条</span><b>{batchPercent}%</b></div>
      <div className="ai-progress-track" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow={batchPercent} aria-label="AI 批量解析进度"><i style={{ transform: `scaleX(${batchPercent / 100})` }} /></div>
      <div className="ai-progress-foot"><span>{batch?.failed_items ? `失败 ${batch.failed_items} 条` : batchIsLive ? '已完成的项目会即时计入' : '处理结果已保存'}</span><span>{batchIsLive ? `预计剩余 ${eta}` : eta}</span></div>
    </section> : null}
    <div className="rail-bottom"><span><ShieldCheck size={15} />数据保存在本机</span><small>拖动素材即可整理，删除可恢复</small></div>
  </aside>
}
