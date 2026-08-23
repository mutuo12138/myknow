import { useEffect, useLayoutEffect, useRef } from 'react'
import { ExternalLink, Eye, FolderOpen, Maximize2, RotateCcw, Tags, Trash2 } from 'lucide-react'

export function MaterialContextMenu({ item, position, categories, onClose, onSelect, onPreview, onCategory, onTrash, onRestore, onRevealLocation }) {
  const menuRef = useRef(null)
  const previewUrl = item?.asset_url || item?.thumbnail_asset_url || item?.thumbnail_url

  useLayoutEffect(() => {
    const menu = menuRef.current
    if (!menu) return
    const rect = menu.getBoundingClientRect()
    const left = Math.min(position.x, window.innerWidth - rect.width - 12)
    const top = Math.min(position.y, window.innerHeight - rect.height - 12)
    menu.style.left = `${Math.max(12, left)}px`
    menu.style.top = `${Math.max(12, top)}px`
    menu.querySelector('button, a')?.focus()
  }, [position])

  useEffect(() => {
    const closeIfOutside = event => {
      if (!menuRef.current?.contains(event.target)) onClose()
    }
    const closeOnKey = event => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('pointerdown', closeIfOutside)
    window.addEventListener('keydown', closeOnKey)
    window.addEventListener('resize', onClose)
    window.addEventListener('scroll', onClose, true)
    return () => {
      document.removeEventListener('pointerdown', closeIfOutside)
      window.removeEventListener('keydown', closeOnKey)
      window.removeEventListener('resize', onClose)
      window.removeEventListener('scroll', onClose, true)
    }
  }, [onClose])

  if (!item) return null

  const act = callback => async () => {
    onClose()
    await callback(item)
  }

  const categoryOptions = ['图片', '视频', '文档', '网页'].flatMap(group => [
    { value: `${group}:`, label: group, category: group, subcategory: null },
    ...categories.filter(option => option.category === group).map(option => ({
      value: `${group}:${option.subcategory}`,
      label: `${group} / ${option.subcategory}`,
      category: group,
      subcategory: option.subcategory,
    })),
  ])

  const changeCategory = async event => {
    const option = categoryOptions.find(candidate => candidate.value === event.target.value)
    if (!option) return
    onClose()
    await onCategory(item, option)
  }

  return <div className="material-context-menu" ref={menuRef} role="menu" aria-label={`${item.title} 的操作`} style={{ left: position.x, top: position.y }}>
    <div className="context-menu-heading"><strong>{item.title}</strong><span>{item.subcategory || item.category || '未分类'}</span></div>
    <button type="button" role="menuitem" onClick={act(onSelect)}><Eye size={15} /><span>在详情中查看</span></button>
    {previewUrl ? <button type="button" role="menuitem" onClick={act(onPreview)}><Maximize2 size={15} /><span>查看大图</span></button> : null}
    {onRevealLocation && (item.local_path || item.snapshot_path) ? <button type="button" role="menuitem" onClick={act(onRevealLocation)}><FolderOpen size={15} /><span>定位原始文件</span></button> : null}
    {item.source_url ? <a role="menuitem" href={item.source_url} target="_blank" rel="noreferrer" onClick={onClose}><ExternalLink size={15} /><span>打开原始页面</span></a> : null}
    {!item.is_deleted ? <div className="context-category"><Tags size={15} /><label htmlFor={`context-category-${item.id}`}>归类到</label><select id={`context-category-${item.id}`} defaultValue="" onChange={changeCategory}><option value="" disabled>选择分类</option>{categoryOptions.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select></div> : null}
    <div className="context-menu-separator" role="separator" />
    {item.is_deleted
      ? <button type="button" role="menuitem" onClick={act(onRestore)}><RotateCcw size={15} /><span>恢复到素材库</span></button>
      : <button className="context-danger" type="button" role="menuitem" onClick={act(onTrash)}><Trash2 size={15} /><span>移入回收站</span></button>}
  </div>
}
