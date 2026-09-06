import { useCallback, useDeferredValue, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Archive, ArrowDownUp, ArrowUp, CheckCircle2, CircleHelp, FolderUp, GripVertical, HardDrive, Layers3, LoaderCircle, Moon, PanelRightClose, PanelRightOpen, RefreshCw, RotateCcw, SearchCheck, Sun, Trash2, Undo2, X } from 'lucide-react'
import gsap from 'gsap'
import { AISettings } from './components/AISettings'
import { CaptureGuide } from './components/CaptureGuide'
import { FolderShelf } from './components/FolderShelf'
import { Inspector } from './components/Inspector'
import { ImageLightbox } from './components/ImageLightbox'
import { LocalImport } from './components/LocalImport'
import { MaterialCard } from './components/MaterialCard'
import { MaterialAssistant } from './components/MaterialAssistant'
import { MaterialContextMenu } from './components/MaterialContextMenu'
import { Sidebar } from './components/Sidebar'
import { StorageSettings } from './components/StorageSettings'
import { Toolbar } from './components/Toolbar'
import { BRIGHTNESS_OPTIONS, DEMO_MATERIALS, matchesColor } from './materials'
import emptyVaultIllustration from './assets/empty-vault.jpg'

function preferredTheme() {
  const saved = localStorage.getItem('muse-theme')
  if (saved === 'light' || saved === 'dark') return saved
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

function preferredDensity() {
  return localStorage.getItem('muse-grid-density') === 'compact' ? 'compact' : 'comfortable'
}

const INSPECTOR_PREFERENCE_VERSION = 'detail-visible-2026-08-30'

function buildParams({ query, category, folderId, materialType, brightness, tags, view = 'library' }) {
  const params = new URLSearchParams()
  params.set('view', view)
  if (query) params.set('q', query)
  if (category) params.set('category', category)
  if (folderId) params.set('folder_id', folderId)
  if (materialType) params.set('material_type', materialType)
  tags.forEach(tag => params.append('tag', tag))
  const range = BRIGHTNESS_OPTIONS.find(option => option.id === brightness)
  if (range?.min != null) params.set('min_brightness', range.min)
  if (range?.max != null) params.set('max_brightness', range.max)
  return params
}

async function getJson(url, options) {
  const response = await fetch(url, options)
  if (!response.ok) {
    let detail = ''
    try { detail = (await response.json()).detail || '' } catch { detail = '' }
    throw new Error(detail || `请求失败：${response.status}`)
  }
  return response.json()
}

export default function App() {
  const appRef = useRef(null)
  const dragGhostRef = useRef(null)
  const dragGhostFrameRef = useRef(0)
  const pendingDragGhostRef = useRef(null)
  const cardEntrancePlayedRef = useRef(false)
  const [theme, setTheme] = useState(preferredTheme)
  const [gridDensity, setGridDensity] = useState(preferredDensity)
  const [inspectorOpen, setInspectorOpen] = useState(() => {
    // The previous narrow-window experiment persisted a closed inspector.
    // Migrate that accidental state once so the detail pane is visible again.
    if (localStorage.getItem('muse-inspector-version') !== INSPECTOR_PREFERENCE_VERSION) {
      localStorage.setItem('muse-inspector-version', INSPECTOR_PREFERENCE_VERSION)
      localStorage.setItem('muse-inspector', 'open')
      return true
    }
    return localStorage.getItem('muse-inspector') !== 'closed'
  })
  const [sortOrder, setSortOrder] = useState('newest')
  const [materials, setMaterials] = useState([])
  const [categories, setCategories] = useState([])
  const [folders, setFolders] = useState([])
  const [tags, setTags] = useState([])
  const [stats, setStats] = useState({ total: 0, queued: 0 })
  const [listTotal, setListTotal] = useState(0)
  const [aiStatus, setAIStatus] = useState({ configured: false, base_url: '', model: '' })
  const [query, setQuery] = useState('')
  const deferredQuery = useDeferredValue(query.trim())
  const [category, setCategory] = useState('')
  const [folderId, setFolderId] = useState('')
  const [selectedTags, setSelectedTags] = useState([])
  const [view, setView] = useState('library')
  const selectedTagKey = selectedTags.join('\u0001')
  const [materialType, setMaterialType] = useState('')
  const [brightness, setBrightness] = useState('all')
  const [color, setColor] = useState('')
  const [colorTolerance, setColorTolerance] = useState(28)
  const [selected, setSelected] = useState(null)
  const [loading, setLoading] = useState(true)
  const [connection, setConnection] = useState('checking')
  const [error, setError] = useState('')
  const [actionError, setActionError] = useState('')
  // Only one non-library surface may occupy the workspace at a time. Keeping
  // this as a single state prevents tool panels from stacking down the page.
  const [activeSurface, setActiveSurface] = useState('library')
  const [assistantActive, setAssistantActive] = useState(false)
  const [showDemo, setShowDemo] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const loadMoreSentinelRef = useRef(null)
  const [lightboxItem, setLightboxItem] = useState(null)
  const [contextMenu, setContextMenu] = useState(null)
  const [draggingMaterial, setDraggingMaterial] = useState(null)
  const [activeDropTarget, setActiveDropTarget] = useState('')
  const [toast, setToast] = useState(null)
  const [showBackToTop, setShowBackToTop] = useState(false)
  const [trashBulkAction, setTrashBulkAction] = useState('')
  const [pendingImportFiles, setPendingImportFiles] = useState([])
  const toastTimerRef = useRef(null)
  const lastAIAlertRef = useRef('')
  const aiStatusHydratedRef = useRef(false)
  const statsSignatureRef = useRef('')

  useEffect(() => () => {
    if (dragGhostFrameRef.current) window.cancelAnimationFrame(dragGhostFrameRef.current)
    dragGhostFrameRef.current = 0
    pendingDragGhostRef.current = null
  }, [])

  const dismissToast = useCallback(() => {
    if (toastTimerRef.current) window.clearTimeout(toastTimerRef.current)
    toastTimerRef.current = null
    setToast(null)
  }, [])

  const showToast = useCallback((message, actionLabel, action) => {
    if (toastTimerRef.current) window.clearTimeout(toastTimerRef.current)
    setToast({ message, actionLabel, action })
    toastTimerRef.current = window.setTimeout(() => setToast(null), 5200)
  }, [])

  const announceAIAlert = useCallback((ai, { suppressToast = false } = {}) => {
    const alert = ai?.ai_alert
    // The API intentionally keeps the latest failed batch for diagnosis. Prime that
    // historical alert on the first metadata load, otherwise every app launch would
    // incorrectly present it as a new failure. Polling still announces new alerts.
    if (suppressToast) {
      lastAIAlertRef.current = alert?.id || ''
      return
    }
    if (!alert?.id || lastAIAlertRef.current === alert.id) return
    lastAIAlertRef.current = alert.id
    showToast(alert.message, '打开 AI 设置', () => setActiveSurface('organize'))
  }, [showToast])

  useEffect(() => () => {
    if (toastTimerRef.current) window.clearTimeout(toastTimerRef.current)
  }, [])

  useEffect(() => {
    const updateBackToTop = () => setShowBackToTop(window.scrollY > 520)
    updateBackToTop()
    window.addEventListener('scroll', updateBackToTop, { passive: true })
    return () => window.removeEventListener('scroll', updateBackToTop)
  }, [])

  const backToTop = useCallback(() => {
    window.scrollTo({
      top: 0,
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
    })
  }, [])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    document.documentElement.style.colorScheme = theme
    localStorage.setItem('muse-theme', theme)
  }, [theme])

  const toggleTheme = useCallback(() => {
    const switchTheme = () => setTheme(value => value === 'dark' ? 'light' : 'dark')
    if (!document.startViewTransition || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      switchTheme()
      return
    }
    document.startViewTransition(switchTheme)
  }, [])

  useEffect(() => {
    localStorage.setItem('muse-grid-density', gridDensity)
  }, [gridDensity])

  useEffect(() => {
    localStorage.setItem('muse-inspector', inspectorOpen ? 'open' : 'closed')
  }, [inspectorOpen])

  useEffect(() => setContextMenu(null), [view, category, folderId])

  useLayoutEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return undefined
    const context = gsap.context(() => {
      const timeline = gsap.timeline({ defaults: { ease: 'power3.out', clearProps: 'transform,opacity,visibility' } })
      timeline
        .fromTo('.app-titlebar', { y: -8, autoAlpha: 0.72 }, { y: 0, autoAlpha: 1, duration: 0.28 })
        .fromTo('.library-header > *', { y: 9, autoAlpha: 0.5 }, { y: 0, autoAlpha: 1, duration: 0.3, stagger: 0.035 }, 0.06)
        .fromTo('.library-controls', { y: 8, autoAlpha: 0.6 }, { y: 0, autoAlpha: 1, duration: 0.26 }, 0.11)
    }, appRef)
    return () => context.revert()
  }, [])

  useLayoutEffect(() => {
    if (!inspectorOpen || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return undefined
    const context = gsap.context(() => {
      const inspector = appRef.current?.querySelector('.inspector')
      if (!inspector) return
      gsap.fromTo(inspector, { x: 16, autoAlpha: 0.35 }, {
        x: 0,
        autoAlpha: 1,
        duration: 0.28,
        ease: 'power3.out',
        clearProps: 'transform,opacity,visibility',
      })
    }, appRef)
    return () => context.revert()
  }, [inspectorOpen])

  useEffect(() => {
    let cancelled = false
    const timer = window.setTimeout(async () => {
      setLoading(true)
      setError('')
      const params = buildParams({ query: deferredQuery, category, folderId, materialType, brightness, tags: selectedTags, view })
      params.set('limit', '200')
      params.set('offset', '0')
      try {
        const items = await getJson(`/api/materials?${params}`)
        if (cancelled) return
        setMaterials(items.items)
        setListTotal(items.total)
        setHasMore(Boolean(items.has_more))
        setConnection('online')
        setSelected(current => items.items.find(item => item.id === current?.id) || items.items[0] || null)
      } catch (requestError) {
        if (cancelled) return
        setConnection('offline')
        setError(requestError.message || '无法读取本机素材列表。')
      } finally {
        if (!cancelled) { setLoading(false); setRefreshing(false) }
      }
    }, deferredQuery ? 180 : 0)
    return () => { cancelled = true; window.clearTimeout(timer) }
  }, [deferredQuery, category, folderId, materialType, brightness, selectedTagKey, view, reloadKey])

  useEffect(() => {
    let cancelled = false
    const loadMetadata = async () => {
      try {
        const [cats, folderData, tagData, overview, ai] = await Promise.all([
          getJson('/api/categories'),
          getJson('/api/folders'),
          getJson('/api/tags'),
          getJson('/api/stats'),
          getJson('/api/ai/status'),
        ])
        if (cancelled) return
        setCategories(cats.items)
        setFolders(folderData.items)
        setTags(tagData.items)
        statsSignatureRef.current = JSON.stringify({ total: overview.total, trash: overview.trash, queued: overview.queued, types: overview.types })
        setStats(overview)
        setAIStatus(ai)
        const suppressInitialToast = !aiStatusHydratedRef.current
        announceAIAlert(ai, { suppressToast: suppressInitialToast })
        aiStatusHydratedRef.current = true
        setConnection('online')
        setActiveSurface(current => current === 'library' && overview.total === 0 && localStorage.getItem('muse-guide-dismissed') !== '1' ? 'capture' : current)
      } catch (requestError) {
        if (!cancelled) setConnection('offline')
      }
    }
    loadMetadata()
    const interval = window.setInterval(async () => {
      try {
        const [overview, ai] = await Promise.all([getJson('/api/stats'), getJson('/api/ai/status')])
        if (!cancelled) {
          const signature = JSON.stringify({ total: overview.total, trash: overview.trash, queued: overview.queued, types: overview.types })
          if (statsSignatureRef.current && signature !== statsSignatureRef.current) {
            setRefreshing(true)
            setReloadKey(value => value + 1)
          }
          statsSignatureRef.current = signature
          setStats(overview)
          setAIStatus(ai)
          announceAIAlert(ai)
        }
      } catch {
        // The material request owns the visible connection error.
      }
    }, 5000)
    return () => { cancelled = true; window.clearInterval(interval) }
  }, [reloadKey])

  useEffect(() => {
    const interval = window.setInterval(() => {
      setRefreshing(true)
      setReloadKey(value => value + 1)
    }, 60_000)
    return () => window.clearInterval(interval)
  }, [])

  const loadMore = async () => {
    if (loadingMore || !hasMore) return
    setLoadingMore(true)
    try {
      const params = buildParams({ query: deferredQuery, category, folderId, materialType, brightness, tags: selectedTags, view })
      params.set('limit', '200')
      params.set('offset', String(materials.length))
      const items = await getJson(`/api/materials?${params}`)
      setMaterials(current => {
        const known = new Set(current.map(item => item.id))
        return [...current, ...items.items.filter(item => !known.has(item.id))]
      })
      setHasMore(Boolean(items.has_more))
      setListTotal(items.total)
      setConnection('online')
    } catch (requestError) {
      setActionError(requestError.message || '加载更多素材失败。')
    } finally {
      setLoadingMore(false)
    }
  }

  useEffect(() => {
    const sentinel = loadMoreSentinelRef.current
    if (!sentinel || !hasMore || loadingMore || demoMode || typeof IntersectionObserver === 'undefined') return undefined
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) loadMore()
    }, { rootMargin: '720px 0px' })
    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [hasMore, loadingMore, materials.length, deferredQuery, category, folderId, materialType, brightness, selectedTagKey, view, showDemo, stats.total])

  const visibleMaterials = useMemo(() => {
    const demoMode = showDemo && stats.total === 0
    const source = demoMode ? DEMO_MATERIALS : materials
    const range = BRIGHTNESS_OPTIONS.find(option => option.id === brightness)
    const normalizedQuery = deferredQuery.toLowerCase()
    return source.filter(item => {
      if (!matchesColor(item, color, colorTolerance)) return false
      if (!demoMode) return true
      if (folderId && item.folder_id !== folderId) return false
      if (materialType && item.material_type !== materialType) return false
      if (category && item.category !== category && item.subcategory !== category) return false
      if (selectedTags.some(tag => !(item.tags || []).includes(tag))) return false
      if (range?.min != null && item.mean_brightness < range.min) return false
      if (range?.max != null && item.mean_brightness > range.max) return false
      if (normalizedQuery) {
        const haystack = [item.title, item.ai_summary, ...(item.tags || [])].join(' ').toLowerCase()
        if (!haystack.includes(normalizedQuery)) return false
      }
      return true
    })
  }, [materials, stats.total, color, colorTolerance, showDemo, folderId, materialType, category, brightness, deferredQuery, selectedTagKey])
  const orderedMaterials = useMemo(() => {
    const next = [...visibleMaterials]
    const itemTitle = item => item.title || ''
    if (sortOrder === 'oldest') return next.sort((a, b) => (a.captured_at || 0) - (b.captured_at || 0))
    if (sortOrder === 'type') return next.sort((a, b) => (a.material_type || '').localeCompare(b.material_type || '', 'zh-CN') || (b.captured_at || 0) - (a.captured_at || 0))
    if (sortOrder === 'title') return next.sort((a, b) => itemTitle(a).localeCompare(itemTitle(b), 'zh-CN', { numeric: true, sensitivity: 'base' }))
    if (sortOrder === 'brightest') return next.sort((a, b) => (b.mean_brightness ?? -1) - (a.mean_brightness ?? -1))
    return next.sort((a, b) => (b.captured_at || 0) - (a.captured_at || 0))
  }, [visibleMaterials, sortOrder])
  useLayoutEffect(() => {
    if (cardEntrancePlayedRef.current || !visibleMaterials.length || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return undefined
    cardEntrancePlayedRef.current = true
    const context = gsap.context(() => {
      const cards = gsap.utils.toArray('.material-card', appRef.current).slice(0, 8)
      gsap.fromTo(cards, { y: 8, autoAlpha: 0.82 }, {
        y: 0, autoAlpha: 1, duration: 0.22, stagger: 0.014, ease: 'power3.out', clearProps: 'transform,opacity,visibility',
      })
      const resultCount = appRef.current?.querySelector('.result-count strong')
      if (resultCount) gsap.fromTo(resultCount, { scale: 0.88, color: 'var(--accent)' }, { scale: 1, color: 'var(--text)', duration: 0.24, ease: 'power2.out', clearProps: 'transform,color' })
    }, appRef)
    return () => context.revert()
  }, [visibleMaterials.length])

  useEffect(() => {
    setSelected(current => visibleMaterials.find(item => item.id === current?.id) || visibleMaterials[0] || null)
  }, [visibleMaterials])

  useEffect(() => {
    if (!selected?.id || selected.is_demo) return undefined
    let cancelled = false
    getJson(`/api/materials/${selected.id}`).then(detail => {
      if (!cancelled) setSelected(current => current?.id === detail.id ? detail : current)
    }).catch(() => { /* The list remains usable when detail refresh fails. */ })
    return () => { cancelled = true }
  }, [selected?.id, reloadKey])

  useEffect(() => {
    if (!selected?.id || selected.is_demo) return undefined
    const pendingMaterial = ['capturing', 'queued', 'analyzing'].includes(selected.status)
    const pendingExport = ['queued', 'running'].includes(selected.export_state)
    if (!pendingMaterial && !pendingExport) return undefined
    let cancelled = false
    const interval = window.setInterval(async () => {
      try {
        const detail = await getJson(`/api/materials/${selected.id}`)
        if (cancelled) return
        setSelected(current => current?.id === detail.id ? detail : current)
        const detailPending = ['capturing', 'queued', 'analyzing'].includes(detail.status)
          || ['queued', 'running'].includes(detail.export_state)
        if (!detailPending) setReloadKey(value => value + 1)
      } catch {
        // The regular list and connection checks own visible errors.
      }
    }, 1200)
    return () => { cancelled = true; window.clearInterval(interval) }
  }, [selected?.id, selected?.status, selected?.export_state])

  const reload = useCallback(() => setReloadKey(value => value + 1), [])
  const refreshLibrary = useCallback(() => {
    if (refreshing) return
    setRefreshing(true)
    reload()
  }, [refreshing, reload])
  const runAction = useCallback(async action => {
    setActionError('')
    try { return await action() } catch (requestError) { setActionError(requestError.message); throw requestError }
  }, [])
  const closeGuide = () => {
    setActiveSurface('library')
    localStorage.setItem('muse-guide-dismissed', '1')
  }
  const patchMaterial = async (materialId, patch) => runAction(async () => {
    await getJson(`/api/materials/${materialId}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch),
    })
    reload()
  })
  const revealOriginalLocation = useCallback(item => runAction(async () => {
    const result = await getJson(`/api/materials/${item.id}/reveal-location`, { method: 'POST' })
    showToast(`已在文件夹中定位原始文件：${result.path}`)
  }), [runAction, showToast])
  const copyMaterialToClipboard = useCallback(item => runAction(async () => {
    if (!item?.local_path) throw new Error('这条素材还没有可复制的本地文件')
    const bridge = window.pywebview?.api
    if (bridge?.copy_file_to_clipboard) {
      const result = await bridge.copy_file_to_clipboard(item.local_path)
      if (!result?.ok) throw new Error(result?.error || '复制失败')
      showToast(result.formats?.some(format => ['image', 'png'].includes(format)) ? '图片和文件已复制，可在目标位置按 Ctrl+V' : '文件已复制，可在目标位置按 Ctrl+V')
      return result
    }
    if (!navigator.clipboard?.writeText) throw new Error('当前运行环境不支持文件剪贴板，请使用桌面版')
    await navigator.clipboard.writeText(item.local_path)
    showToast('已复制本地路径；桌面版可直接复制文件')
    return { ok: true, formats: ['text'] }
  }), [runAction, showToast])

  useEffect(() => {
    const copySelectedMaterial = event => {
      if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'c') return
      if (activeSurface !== 'library' || !selected?.has_local_copy || selected.is_deleted) return
      const activeElement = document.activeElement
      const tagName = activeElement?.tagName
      const isEditing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(tagName) || activeElement?.isContentEditable
      const selection = window.getSelection?.()
      if (isEditing || (selection && !selection.isCollapsed)) return
      event.preventDefault()
      copyMaterialToClipboard(selected).catch(() => {})
    }
    window.addEventListener('keydown', copySelectedMaterial)
    return () => window.removeEventListener('keydown', copySelectedMaterial)
  }, [activeSurface, copyMaterialToClipboard, selected])
  const createFolder = name => runAction(async () => {
    const folder = await getJson('/api/folders', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }),
    })
    setFolderId(folder.id)
    setCategory('')
    reload()
  })
  const saveAIConfig = payload => runAction(async () => {
    await getJson('/api/ai/config', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    })
    const status = await getJson('/api/ai/status')
    setAIStatus(status)
  })
  const saveProcessingSettings = payload => runAction(async () => {
    await getJson('/api/processing/settings', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    })
    const status = await getJson('/api/ai/status')
    setAIStatus(status)
    reload()
  })
  const startAIBatch = payload => runAction(async () => {
    await getJson('/api/ai/batches', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    })
    setAIStatus(await getJson('/api/ai/status'))
    reload()
  })
  const pauseAIBatch = batchId => runAction(async () => {
    await getJson(`/api/ai/batches/${batchId}/pause`, { method: 'POST' })
    setAIStatus(await getJson('/api/ai/status'))
  })
  const resumeAIBatch = batchId => runAction(async () => {
    await getJson(`/api/ai/batches/${batchId}/resume`, { method: 'POST' })
    setAIStatus(await getJson('/api/ai/status'))
  })
  const retryAIBatch = batchId => runAction(async () => {
    const result = await getJson(`/api/ai/batches/${batchId}/retry-failed`, { method: 'POST' })
    setAIStatus(await getJson('/api/ai/status'))
    showToast(`已重新排队 ${result.retried || 0} 个失败项`)
    reload()
  })
  const analyzeMaterial = materialId => runAction(async () => {
    await getJson(`/api/materials/${materialId}/ai-analyze`, { method: 'POST' })
    reload()
  })
  const retryMaterial = materialId => runAction(async () => {
    await getJson(`/api/materials/${materialId}/retry`, { method: 'POST' })
    reload()
  })
  const rebuildThumbnail = materialId => runAction(async () => {
    await getJson(`/api/materials/${materialId}/thumbnail/rebuild`, { method: 'POST' })
    reload()
  })
  const requestOfflineExport = (materialId, format) => runAction(async () => {
    await getJson(`/api/materials/${materialId}/offline/${format}`, { method: 'POST' })
    reload()
  })
  const moveToTrash = materialId => runAction(async () => {
    await getJson(`/api/materials/${materialId}`, { method: 'DELETE' })
    setSelected(current => current?.id === materialId ? null : current)
    reload()
  })
  const restoreMaterial = materialId => runAction(async () => {
    await getJson(`/api/materials/${materialId}/restore`, { method: 'POST' })
    setSelected(current => current?.id === materialId ? null : current)
    reload()
  })
  const permanentlyDeleteMaterial = materialId => runAction(async () => {
    await getJson(`/api/materials/${materialId}?permanent=true`, { method: 'DELETE' })
    setSelected(current => current?.id === materialId ? null : current)
    reload()
  })
  const restoreAllTrash = async () => {
    if (trashBulkAction || !stats.trash) return
    if (!window.confirm(`确定恢复回收站中的 ${stats.trash} 项素材吗？`)) return
    setTrashBulkAction('restore')
    try {
      const result = await runAction(() => getJson('/api/trash/restore-all', { method: 'POST' }))
      setSelected(null)
      clearFilters()
      showToast(result.failed?.length ? `已恢复 ${result.restored} 项，${result.failed.length} 项失败` : `已恢复 ${result.restored} 项素材`)
      reload()
    } catch {
      // runAction exposes the request error in the action banner.
    } finally {
      setTrashBulkAction('')
    }
  }
  const permanentlyDeleteAllTrash = async () => {
    if (trashBulkAction || !stats.trash) return
    if (!window.confirm(`永久删除回收站中的 ${stats.trash} 项素材？此操作无法恢复。`)) return
    setTrashBulkAction('permanent')
    try {
      const result = await runAction(() => getJson('/api/trash/permanent-delete-all', { method: 'POST' }))
      setSelected(null)
      clearFilters()
      showToast(result.failed?.length ? `已永久删除 ${result.deleted} 项，${result.failed.length} 项失败` : `已永久删除 ${result.deleted} 项素材`)
      reload()
    } catch {
      // runAction exposes the request error in the action banner.
    } finally {
      setTrashBulkAction('')
    }
  }
  const quickTrash = async item => {
    if (!item || item.is_demo || item.is_deleted) return
    await moveToTrash(item.id)
    showToast('已移入回收站', '撤销', async () => {
      await restoreMaterial(item.id)
      showToast('素材已恢复')
    })
  }
  const quickCategory = async (item, target) => {
    if (!item || item.is_demo || item.is_deleted) return
    await patchMaterial(item.id, { category: target.category, subcategory: target.subcategory })
    showToast(`已归类为「${target.subcategory || target.category}」`)
  }
  const handleDropMaterial = async (materialId, target) => {
    const item = materials.find(material => material.id === materialId) || (selected?.id === materialId ? selected : null)
    setDraggingMaterial(null)
    if (!item || item.is_demo || item.is_deleted) return
    try {
      if (target.kind === 'trash') {
        await quickTrash(item)
        return
      }
      if (target.kind === 'folder') {
        await patchMaterial(materialId, { folder_id: target.folderId })
        showToast(`已放到「${target.label}」`)
        return
      }
      if (target.kind === 'category') {
        await patchMaterial(materialId, { category: target.category, subcategory: target.subcategory })
        showToast(`已归类为「${target.label}」`)
      }
    } catch {
      // runAction owns the visible error message.
    }
  }
  const dropTargetFromKey = key => {
    if (!key) return null
    if (key === 'trash') return { kind: 'trash', label: '回收站' }
    const [kind, first, ...rest] = key.split(':')
    if (kind === 'folder') {
      const folder = folders.find(candidate => candidate.id === first)
      return folder ? { kind: 'folder', folderId: folder.id, label: folder.name } : null
    }
    if (kind === 'category') return { kind: 'category', category: first, subcategory: rest.length ? rest.join(':') : null, label: rest.length ? rest.join(':') : first }
    return null
  }
  const moveDragGhost = ({ x, y, targetKey }) => {
    setActiveDropTarget(current => current === targetKey ? current : targetKey)
    pendingDragGhostRef.current = { x: x + 14, y: y + 14 }
    if (dragGhostFrameRef.current) return
    dragGhostFrameRef.current = window.requestAnimationFrame(() => {
      dragGhostFrameRef.current = 0
      const next = pendingDragGhostRef.current
      pendingDragGhostRef.current = null
      const ghost = dragGhostRef.current
      if (!ghost || !next) return
      ghost.style.transform = `translate3d(${next.x}px, ${next.y}px, 0)`
      ghost.style.opacity = '1'
    })
  }
  const hideDragGhost = () => {
    if (dragGhostFrameRef.current) window.cancelAnimationFrame(dragGhostFrameRef.current)
    dragGhostFrameRef.current = 0
    pendingDragGhostRef.current = null
    if (dragGhostRef.current) dragGhostRef.current.style.opacity = '0'
  }
  const finishPointerDrop = (materialId, targetKey) => {
    const target = dropTargetFromKey(targetKey)
    setActiveDropTarget('')
    hideDragGhost()
    setDraggingMaterial(null)
    if (target) handleDropMaterial(materialId, target)
  }
  const endDragSession = () => {
    setDraggingMaterial(null)
    setActiveDropTarget('')
    hideDragGhost()
  }
  const hasExternalFiles = event => {
    const types = Array.from(event.dataTransfer?.types || [])
    return types.includes('Files') && !types.includes('application/x-muse-material')
  }
  const handleFileDragOver = event => {
    if (!hasExternalFiles(event)) return
    event.preventDefault()
    event.dataTransfer.dropEffect = 'copy'
  }
  const handleFileDrop = event => {
    if (!hasExternalFiles(event)) return
    event.preventDefault()
    event.stopPropagation()
    const files = Array.from(event.dataTransfer.files || [])
    if (!files.length) return
    setPendingImportFiles(files)
    setActiveSurface('import')
    showToast(`已接收 ${files.length} 个本机文件，请确认导入位置`)
  }
  const exitAssistantResults = () => {
    if (!assistantActive) return
    setAssistantActive(false)
    setActiveSurface('library')
    setReloadKey(value => value + 1)
  }
  const toggleTag = tag => {
    exitAssistantResults()
    setSelectedTags(current => current.includes(tag) ? current.filter(item => item !== tag) : [...current, tag])
  }
  const clearFilters = () => {
    exitAssistantResults()
    setQuery(''); setCategory(''); setFolderId(''); setSelectedTags([]); setMaterialType(''); setBrightness('all'); setColor('')
  }
  const pickView = nextView => {
    setView(nextView)
    clearFilters()
    setShowDemo(false)
    setActiveSurface('library')
  }

  const openModule = module => {
    if (module === 'library') {
      pickView('library')
      return
    }
    if (module === 'capture') {
      setActiveSurface('capture')
      return
    }
    setActiveSurface('organize')
  }

  const openAssistant = () => {
    setView('library')
    clearFilters()
    setShowDemo(false)
    setActiveSurface('assistant')
  }

  const closeAssistant = () => {
    setActiveSurface('library')
    if (assistantActive) {
      setAssistantActive(false)
      reload()
    }
  }

  const showAssistantResults = data => {
    setMaterials(data.items || [])
    setListTotal(data.total || 0)
    setHasMore(false)
    setLoading(false)
    setAssistantActive(true)
    setSelected(data.items?.[0] || null)
  }

  const navigateLightbox = useCallback(nextItem => {
    setLightboxItem(nextItem)
    setSelected(nextItem)
  }, [])

  const mergeAssistantItems = updatedItems => {
    if (!updatedItems?.length) return
    const updates = new Map(updatedItems.map(item => [item.id, item]))
    setMaterials(current => current.map(item => updates.get(item.id) || item))
    setSelected(current => current && (updates.get(current.id) || current))
  }

  const activeFolder = folders.find(folder => folder.id === folderId)
  const libraryTitle = view === 'trash' ? '回收站' : activeFolder?.name || category || '全部素材'
  const surfaceTitles = { capture: '网页采集', organize: '整理中心', import: '导入本机素材', storage: '存放位置', assistant: '素材助手' }
  const title = activeSurface === 'library' ? libraryTitle : surfaceTitles[activeSurface]
  const isFiltering = Boolean(assistantActive || deferredQuery || category || folderId || selectedTags.length || materialType || brightness !== 'all' || color)
  const isEmpty = !loading && !error && (view === 'trash' ? listTotal === 0 : stats.total === 0) && !showDemo
  const demoMode = showDemo && stats.total === 0
  const displayCount = demoMode ? visibleMaterials.length : listTotal
  const headerDescription = activeSurface === 'library'
    ? (assistantActive ? '素材助手正在展示自然语言检索结果' : demoMode ? '预览示例，不会写入你的素材库' : view === 'trash' ? '误删素材会暂时保留在这里，可恢复或永久删除' : stats.queued ? `${stats.queued} 项正在整理` : activeFolder ? `当前保存位置：${activeFolder.name}` : '浏览、整理和重新找到你保存的内容')
    : activeSurface === 'capture' ? '用最少的步骤把网页内容收进本机素材库'
      : activeSurface === 'organize' ? '查看每次 AI 请求的用量，并控制整理策略'
        : activeSurface === 'import' ? '把本机图片安全导入到指定文件夹，支持直接拖入'
          : activeSurface === 'storage' ? '查看素材、数据库和运行日志的实际存放位置'
            : '用自然语言查找并批量整理本机素材'
  const aiModeLabel = !aiStatus.configured ? '配置 AI' : aiStatus.ai_mode === 'auto' ? 'AI 自动' : aiStatus.ai_mode === 'manual' ? 'AI 待命' : 'AI 已关闭'

  return <div className={`muse-app designer-board ${inspectorOpen && activeSurface === 'library' ? '' : 'inspector-hidden'}`} ref={appRef} onDragOver={handleFileDragOver} onDrop={handleFileDrop}>
    <div className="app-titlebar">
      <div className="titlebar-brand"><img className="brand-icon" src="/favicon.png" alt="" /><b>myknow</b></div>
      <nav className="module-tabs" aria-label="工作区模块">
        <button className={activeSurface === 'library' ? 'active' : ''} type="button" onClick={() => openModule('library')}>素材库</button>
        <button className={activeSurface === 'capture' ? 'active' : ''} type="button" onClick={() => openModule('capture')}>网页采集</button>
        <button className={activeSurface === 'organize' ? 'active' : ''} type="button" onClick={() => openModule('organize')}>整理中心</button>
      </nav>
      <div className="titlebar-library-state"><HardDrive size={13} /><span>本机库</span><em>{displayCount}</em></div>
    </div>
    <Sidebar categories={categories} folders={folders} activeCategory={category} activeFolder={folderId} view={view} trashCount={stats.trash || 0} aiStatus={aiStatus} draggingMaterial={draggingMaterial} activeDropTarget={activeDropTarget} onPickView={pickView} onPickCategory={value => { pickView('library'); setCategory(value) }} onPickFolder={value => { pickView('library'); setFolderId(value) }} onCreateFolder={createFolder} onDropMaterial={handleDropMaterial} onOpenAI={() => setActiveSurface('organize')} />
    <main className="workspace">
      <header className="library-header">
        <div className="header-copy"><h1>{title}<span>{displayCount}</span></h1><p>{headerDescription}</p></div>
        <div className="command-bar" aria-label="素材库工具">
          <div className="command-group command-primary">
            <button className={`primary-command ${activeSurface === 'import' ? 'active' : ''}`} type="button" onClick={() => setActiveSurface(value => value === 'import' ? 'library' : 'import')}><FolderUp size={16} />导入</button>
            <button className={`ai-command ${aiStatus.ai_mode === 'auto' ? 'ai-online' : ''} ${activeSurface === 'organize' ? 'active' : ''}`} type="button" onClick={() => setActiveSurface(value => value === 'organize' ? 'library' : 'organize')} title={aiModeLabel} aria-label={aiModeLabel}><Layers3 size={16} />整理</button>
            <button className={`assistant-command ${activeSurface === 'assistant' ? 'active' : ''}`} type="button" onClick={activeSurface === 'assistant' ? closeAssistant : openAssistant} aria-pressed={activeSurface === 'assistant'}><SearchCheck size={16} />助手</button>
          </div>
          <div className="command-divider" />
          <div className="command-group command-utilities">
            <button className="command-icon inspector-toggle" type="button" onClick={() => setInspectorOpen(value => !value)} title={inspectorOpen ? '隐藏素材详情' : '显示素材详情'} aria-label={inspectorOpen ? '隐藏素材详情' : '显示素材详情'} aria-pressed={inspectorOpen}>{inspectorOpen ? <PanelRightClose size={16} /> : <PanelRightOpen size={16} />}<span>详情</span></button>
            <button className={`command-icon ${activeSurface === 'storage' ? 'active' : ''}`} type="button" onClick={() => setActiveSurface(value => value === 'storage' ? 'library' : 'storage')} title="存放位置" aria-label="存放位置"><HardDrive size={16} /></button>
            <button className={`command-icon ${refreshing ? 'is-loading' : ''}`} type="button" onClick={refreshLibrary} disabled={refreshing} title="刷新素材库（自动同步中）" aria-label="刷新素材库，素材库每分钟自动同步"><RefreshCw size={16} /></button>
            <button className={`command-icon ${activeSurface === 'capture' ? 'active' : ''}`} type="button" onClick={() => setActiveSurface(value => value === 'capture' ? 'library' : 'capture')} title="采集方法" aria-label="采集方法"><CircleHelp size={16} /></button>
            <button className="command-icon theme-toggle" type="button" onClick={toggleTheme} title={theme === 'dark' ? '切换到白天模式' : '切换到黑夜模式'} aria-label={theme === 'dark' ? '切换到白天模式' : '切换到黑夜模式'}>{theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}</button>
          </div>
          <span className={`host-status ${connection}`}><i />{connection === 'online' ? '本机在线' : connection === 'offline' ? '未连接' : '连接中'}</span>
        </div>
      </header>

      {actionError ? <div className="action-error" role="alert">{actionError}<button type="button" onClick={() => setActionError('')}>关闭</button></div> : null}
      {activeSurface !== 'library' ? <section className={`workspace-surface surface-${activeSurface}`} aria-label={title}>
        {activeSurface === 'import' ? <LocalImport folders={folders} defaultFolderId={folderId || 'inbox'} initialFiles={pendingImportFiles} onInitialFilesConsumed={() => setPendingImportFiles([])} onComplete={() => { setPendingImportFiles([]); reload() }} onOpenStorageSettings={() => setActiveSurface('storage')} onClose={() => { setPendingImportFiles([]); setActiveSurface('library') }} /> : null}
        {activeSurface === 'storage' ? <StorageSettings onClose={() => setActiveSurface('library')} /> : null}
        {activeSurface === 'organize' ? <AISettings status={aiStatus} folders={folders} activeFolderId={folderId} onSave={saveAIConfig} onSaveProcessing={saveProcessingSettings} onStartBatch={startAIBatch} onPauseBatch={pauseAIBatch} onResumeBatch={resumeAIBatch} onRetryBatch={retryAIBatch} onClose={() => setActiveSurface('library')} /> : null}
        {activeSurface === 'capture' ? <CaptureGuide connection={connection} onClose={closeGuide} onPreview={() => { setShowDemo(true); closeGuide() }} /> : null}
        {activeSurface === 'assistant' ? <MaterialAssistant folders={folders} aiStatus={aiStatus} onClose={closeAssistant} onResults={showAssistantResults} onItemsUpdated={mergeAssistantItems} onToast={message => showToast(message)} /> : null}
      </section> : <>
        <Toolbar query={query} onQuery={value => { exitAssistantResults(); setQuery(value) }} materialType={materialType} onType={value => { exitAssistantResults(); setMaterialType(value) }} brightness={brightness} onBrightness={value => { exitAssistantResults(); setBrightness(value) }} color={color} onColor={value => { exitAssistantResults(); setColor(value) }} colorTolerance={colorTolerance} onColorTolerance={setColorTolerance} totalCount={demoMode ? visibleMaterials.length : listTotal} visibleCount={visibleMaterials.length} tags={tags} selectedTags={selectedTags} onToggleTag={toggleTag} onRemoveTag={tag => { exitAssistantResults(); setSelectedTags(current => current.filter(item => item !== tag)) }} scopeLabel={activeFolder?.name || category} onClearScope={() => { exitAssistantResults(); setCategory(''); setFolderId('') }} onClearFilters={clearFilters} isFiltering={isFiltering} trashMode={view === 'trash'} gridDensity={gridDensity} onDensity={setGridDensity} />

        {error ? <section className="error-state"><Archive size={28} /><h2>素材库暂时没有连接</h2><p>{error}</p><button type="button" onClick={reload}><RefreshCw size={15} />重新连接</button></section>
          : loading ? <div className="loading"><LoaderCircle />正在读取本机素材库</div>
            : visibleMaterials.length ? <>
            {view === 'library' && !isFiltering ? <FolderShelf folders={folders} materials={visibleMaterials} onPickFolder={value => { pickView('library'); setFolderId(value) }} /> : null}
            <div className="collection-heading"><div><strong>{view === 'trash' ? '已删除素材' : title === '全部素材' ? '素材' : title}</strong><span>({displayCount})</span></div><div className="collection-tools"><small>{gridDensity === 'compact' ? '密集索引' : '看图优先'}</small>{view !== 'trash' ? <label className="sort-control"><ArrowDownUp size={13} /><span>排序</span><select value={sortOrder} onChange={event => setSortOrder(event.target.value)} aria-label="素材排序"><option value="newest">最近导入</option><option value="oldest">最早导入</option><option value="type">素材类型</option><option value="title">标题名称</option><option value="brightest">整体亮度</option></select></label> : <div className="trash-bulk-actions" aria-label="回收站批量操作"><button type="button" onClick={restoreAllTrash} disabled={Boolean(trashBulkAction)}><RotateCcw size={14} />{trashBulkAction === 'restore' ? '恢复中…' : '一键恢复'}</button><button className="danger" type="button" onClick={permanentlyDeleteAllTrash} disabled={Boolean(trashBulkAction)}><Trash2 size={14} />{trashBulkAction === 'permanent' ? '删除中…' : '一键永久删除'}</button></div>}</div></div>
            <section className={`masonry density-${gridDensity}`} aria-label="素材列表">{orderedMaterials.map(item => <MaterialCard key={item.id} item={item} selected={selected?.id === item.id} dragging={draggingMaterial?.id === item.id} onSelect={setSelected} onPreview={setLightboxItem} onOpenMenu={(menuItem, position) => setContextMenu({ item: menuItem, position })} onCopy={copyMaterialToClipboard} onDragStart={setDraggingMaterial} onDragMove={moveDragGhost} onPointerDrop={finishPointerDrop} onDragEnd={endDragSession} />)}</section>
          </>
            : isEmpty && view === 'trash' ? <section className="empty-library compact"><Archive size={28} /><h2>回收站为空</h2><p>移入回收站的素材会暂时保留在这里。</p></section>
             : isEmpty ? <section className="empty-library">
                <div className="empty-vault-illustration-frame" aria-hidden="true">
                  <img src={emptyVaultIllustration} alt="素材库工作台插画" />
                </div>
                <Archive size={32} />
                <h2>先保存一条真正会用到的素材</h2>
                <p>从浏览器采集，或直接导入已有的本机图片文件夹。</p>
                <div>
                  <button type="button" onClick={() => setActiveSurface('import')}><FolderUp size={15} />导入图片文件夹</button>
                  <button className="secondary-button" type="button" onClick={() => setActiveSurface('capture')}>查看采集方法</button>
                  <button className="secondary-button" type="button" onClick={() => setShowDemo(true)}>预览示例素材</button>
                </div>
              </section>
              : <section className="empty-library"><Archive size={30} /><h2>没有同时满足这些条件的素材</h2><p>叠加标签采用“并且”关系；可以减少标签，或清除其他筛选。</p><button type="button" onClick={clearFilters}>清除筛选</button></section>}
        {hasMore && !demoMode ? <div className="load-more" ref={loadMoreSentinelRef}><button type="button" onClick={loadMore} disabled={loadingMore}>{loadingMore ? <LoaderCircle size={15} /> : <RefreshCw size={15} />}{loadingMore ? '正在加载' : '继续加载'}</button><span>已载入 {visibleMaterials.length} / {listTotal}，滚动到底部会自动继续</span></div> : null}
      </>}
    </main>
    {inspectorOpen && activeSurface === 'library' ? <Inspector item={selected} folders={folders} aiStatus={aiStatus} view={view} onPreview={setLightboxItem} onCopyMaterial={copyMaterialToClipboard} onRevealLocation={revealOriginalLocation} onSaveTags={(id, nextTags) => patchMaterial(id, { tags: nextTags })} onMoveFolder={(id, nextFolder) => patchMaterial(id, { folder_id: nextFolder })} onAnalyze={analyzeMaterial} onRetry={retryMaterial} onRebuildThumbnail={rebuildThumbnail} onRequestExport={requestOfflineExport} onMoveToTrash={moveToTrash} onRestore={restoreMaterial} onPermanentDelete={permanentlyDeleteMaterial} /> : null}
    {contextMenu ? <MaterialContextMenu item={contextMenu.item} position={contextMenu.position} categories={categories} onClose={() => setContextMenu(null)} onSelect={setSelected} onPreview={setLightboxItem} onCopyMaterial={copyMaterialToClipboard} onCategory={quickCategory} onTrash={quickTrash} onRestore={item => restoreMaterial(item.id)} onRevealLocation={revealOriginalLocation} /> : null}
    {lightboxItem ? <ImageLightbox item={lightboxItem} items={orderedMaterials} onNavigate={navigateLightbox} onClose={() => setLightboxItem(null)} /> : null}
    {draggingMaterial ? <div className="material-drag-ghost" ref={dragGhostRef} aria-hidden="true"><GripVertical size={14} /><span>{draggingMaterial.title}</span></div> : null}
    {toast ? <div className="action-toast" role="status"><CheckCircle2 size={17} /><span>{toast.message}</span>{toast.action ? <button type="button" onClick={async () => { const action = toast.action; dismissToast(); await action() }}><Undo2 size={14} />{toast.actionLabel}</button> : null}<button className="toast-close" type="button" onClick={dismissToast} aria-label="关闭提示"><X size={15} /></button></div> : null}
    {showBackToTop ? <button className="back-to-top" type="button" onClick={backToTop} aria-label="返回顶部" title="返回顶部"><ArrowUp size={16} /><span>顶部</span></button> : null}
  </div>
}
