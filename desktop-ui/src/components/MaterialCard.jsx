import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, BookOpen, FileText, Globe2, GripVertical, HardDrive, Image, Library, Link2, LoaderCircle, MonitorDown, MoreHorizontal, Video } from 'lucide-react'
import { colorFrom } from '../materials'

const typeIcon = { image: Image, video: Video, document: FileText, presentation: MonitorDown, blog: BookOpen, page: Library, link: Library }
const typeLabel = { image: '图片', video: '视频', document: '文档', presentation: '演示文稿', blog: '博客', page: '网页', link: '链接' }
const processingLabel = { capturing: '正在保存', queued: '等待处理', analyzing: '整理中', partial: '部分完成', failed: '处理失败' }

export function MaterialCard({ item, selected, dragging, onSelect, onPreview, onOpenMenu, onDragStart, onDragMove, onPointerDrop, onDragEnd, onNativeFileDrag }) {
  const cardRef = useRef(null)
  const pointerDragRef = useRef(null)
  const mouseCleanupRef = useRef(null)
  const externalDragCleanupRef = useRef(null)
  const previewUrl = item.thumbnail_asset_url || item.asset_url || item.thumbnail_url
  const [imageFailed, setImageFailed] = useState(false)
  const Icon = typeIcon[item.material_type] || FileText
  const showImage = previewUrl && !imageFailed
  const tags = (item.tags || []).slice(0, 2)
  const stateLabel = processingLabel[item.status]
  const StateIcon = ['partial', 'failed'].includes(item.status) ? AlertTriangle : LoaderCircle
  const canMove = !item.is_demo && !item.is_deleted
  const rawRatio = item.thumbnail_width && item.thumbnail_height ? item.thumbnail_width / item.thumbnail_height : item.material_type === 'page' ? 1.6 : 1.25
  // Keep common phone portraits and wide page captures faithful to the
  // source. The old 0.72–1.75 clamp created visible gutters around 9:16
  // images and squeezed wide page screenshots into an arbitrary frame.
  const mediaRatio = Math.min(2.05, Math.max(0.55, rawRatio))
  useEffect(() => setImageFailed(false), [previewUrl])
  useEffect(() => () => {
    mouseCleanupRef.current?.()
    externalDragCleanupRef.current?.()
  }, [])

  const openAtPointer = event => {
    event.preventDefault()
    event.stopPropagation()
    onSelect(item)
    onOpenMenu(item, { x: event.clientX, y: event.clientY })
  }

  const openAtButton = event => {
    event.stopPropagation()
    const rect = event.currentTarget.getBoundingClientRect()
    onSelect(item)
    onOpenMenu(item, { x: rect.right, y: rect.bottom + 6 })
  }

  const openFromKeyboard = event => {
    if (event.key !== 'ContextMenu' && !(event.shiftKey && event.key === 'F10')) return
    event.preventDefault()
    const rect = cardRef.current.getBoundingClientRect()
    onSelect(item)
    onOpenMenu(item, { x: rect.left + 24, y: rect.top + 42 })
  }

  const beginDrag = event => {
    if (event.target.closest?.('.material-preview')) {
      beginExternalDrag(event)
      return
    }
    if (!canMove) {
      event.preventDefault()
      return
    }
    event.stopPropagation()
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('application/x-muse-material', item.id)
    event.dataTransfer.setData('text/plain', item.id)
    if (cardRef.current) event.dataTransfer.setDragImage(cardRef.current, 28, 28)
    onDragStart(item)
  }

  const beginExternalDrag = event => {
    if (window.pywebview?.api?.start_file_drag) {
      event.preventDefault()
      return
    }
    if (!item.local_path) {
      event.preventDefault()
      return
    }
    event.stopPropagation()
    event.dataTransfer.effectAllowed = 'copy'
    const normalizedPath = String(item.local_path).replaceAll('\\', '/')
    const fileUrl = `file://${encodeURI(normalizedPath.startsWith('/') ? normalizedPath : `/${normalizedPath}`)}`
    const mime = item.mime_type || 'application/octet-stream'
    event.dataTransfer.setData('DownloadURL', `${mime}:${item.title || '素材'}:${fileUrl}`)
    event.dataTransfer.setData('text/uri-list', fileUrl)
    event.dataTransfer.setData('text/plain', item.local_path)
  }

  const beginNativeExternalDrag = event => {
    if (event.pointerType !== 'mouse' || event.button !== 0 || !item.local_path || !window.pywebview?.api?.start_file_drag) return
    const session = { startX: event.clientX, startY: event.clientY, started: false }
    const cleanup = () => {
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mouseup', end)
      externalDragCleanupRef.current = null
    }
    const move = moveEvent => {
      if (session.started) return
      if (Math.hypot(moveEvent.clientX - session.startX, moveEvent.clientY - session.startY) < 6) return
      session.started = true
      cleanup()
      moveEvent.preventDefault()
      moveEvent.stopPropagation()
      onNativeFileDrag(item)
    }
    const end = () => cleanup()
    externalDragCleanupRef.current?.()
    externalDragCleanupRef.current = cleanup
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', end, { once: true })
  }

  const targetAt = (x, y) => document.elementFromPoint(x, y)?.closest?.('[data-drop-target]')?.dataset.dropTarget || ''

  const beginPointerDrag = event => {
    if (event.pointerType === 'mouse') return
    if (!canMove) return
    event.preventDefault()
    event.stopPropagation()
    event.currentTarget.setPointerCapture(event.pointerId)
    pointerDragRef.current = { pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, started: false, targetKey: '' }
  }

  const movePointerDrag = event => {
    const session = pointerDragRef.current
    if (!session || session.pointerId !== event.pointerId) return
    const distance = Math.hypot(event.clientX - session.startX, event.clientY - session.startY)
    if (!session.started && distance < 4) return
    if (!session.started) {
      session.started = true
      onDragStart(item)
    }
    session.targetKey = targetAt(event.clientX, event.clientY)
    onDragMove({ x: event.clientX, y: event.clientY, targetKey: session.targetKey })
  }

  const endPointerDrag = event => {
    const session = pointerDragRef.current
    if (!session || session.pointerId !== event.pointerId) return
    pointerDragRef.current = null
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
    if (session.started) onPointerDrop(item.id, session.targetKey || targetAt(event.clientX, event.clientY))
    onDragEnd()
  }

  const beginMouseDrag = event => {
    if (!canMove || event.button !== 0) return
    event.preventDefault()
    event.stopPropagation()
    const session = { startX: event.clientX, startY: event.clientY, started: false, targetKey: '' }
    const move = moveEvent => {
      const distance = Math.hypot(moveEvent.clientX - session.startX, moveEvent.clientY - session.startY)
      if (!session.started && distance < 4) return
      if (!session.started) {
        session.started = true
        onDragStart(item)
      }
      session.targetKey = targetAt(moveEvent.clientX, moveEvent.clientY)
      onDragMove({ x: moveEvent.clientX, y: moveEvent.clientY, targetKey: session.targetKey })
    }
    const cleanup = () => {
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mouseup', end)
      mouseCleanupRef.current = null
    }
    const end = upEvent => {
      cleanup()
      const finalTarget = session.targetKey || targetAt(upEvent.clientX, upEvent.clientY)
      if (session.started) onPointerDrop(item.id, finalTarget)
      onDragEnd()
    }
    mouseCleanupRef.current?.()
    mouseCleanupRef.current = cleanup
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', end)
  }

  return <article ref={cardRef} className={`material-card ${selected ? 'selected' : ''} ${dragging ? 'is-dragging' : ''}`} data-material-id={item.id} data-material-type={item.material_type} style={{ '--material-color': colorFrom(item), '--media-ratio': mediaRatio }} draggable={canMove} onDragStart={beginDrag} onDragEnd={onDragEnd} onContextMenu={openAtPointer}>
    <button className="material-card-select" onClick={() => onSelect(item)} onKeyDown={openFromKeyboard} type="button">
      <div className="card-media" onPointerDown={beginNativeExternalDrag} onDoubleClick={event => { event.stopPropagation(); if (showImage) onPreview(item) }}>
        {showImage
          ? <img className={`material-preview preview-${item.material_type}`} src={previewUrl} alt={item.title} width={item.thumbnail_width || undefined} height={item.thumbnail_height || undefined} loading="lazy" decoding="async" draggable={Boolean(item.local_path)} onDragStart={beginExternalDrag} onError={() => setImageFailed(true)} />
          : <div className="media-empty"><Icon className="media-placeholder" size={30} aria-hidden="true" /><span>{item.source_name || '暂无本地预览'}</span></div>}
        <span className="type-mark"><Icon size={13} />{typeLabel[item.material_type] || '素材'}</span>
        {item.has_local_copy ? <span className="local-copy-mark" title={item.is_linked ? '原位置引用，不复制文件' : '本地副本可用'}>{item.is_linked ? <Link2 size={12} /> : <HardDrive size={12} />}{item.is_linked ? '引用' : '本地'}</span> : null}
        {item.is_demo ? <span className="demo-mark">示例</span> : stateLabel ? <span className={`analysis ${item.status}`}><StateIcon size={12} />{stateLabel}</span> : null}
      </div>
      <div className="card-content">
        <span className="card-source"><Globe2 size={11} />{item.source_name || '本机采集'}</span>
        <strong>{item.title}</strong>
        <p>{item.ai_summary || item.text_content?.slice(0, 120) || '已保存，等待生成内容摘要。'}</p>
        {tags.length ? <div className="card-tags">{tags.map(tag => <span key={tag}>{tag}</span>)}</div> : null}
        <div className="card-footer"><span className="card-classification"><i className="card-color-dot" title="素材主色" />{item.subcategory || item.category || '未分类'}</span><time>{new Date(item.captured_at * 1000).toLocaleDateString('zh-CN')}</time></div>
      </div>
    </button>
    <div className="card-direct-actions">
      {canMove ? <button className="card-drag-handle" type="button" onMouseDown={beginMouseDrag} onPointerDown={beginPointerDrag} onPointerMove={movePointerDrag} onPointerUp={endPointerDrag} onPointerCancel={endPointerDrag} onClick={event => event.stopPropagation()} title="拖动整理" aria-label={`拖动整理：${item.title}`} aria-pressed={dragging}><GripVertical size={15} /></button> : null}
      <button className="card-more" type="button" onClick={openAtButton} title="更多操作" aria-label={`更多操作：${item.title}`}><MoreHorizontal size={16} /></button>
    </div>
  </article>
}
