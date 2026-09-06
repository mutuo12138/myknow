(() => {
const CONTENT_VERSION = '0.7.7-stable-r6'
if (globalThis.__museVaultCaptureVersion === CONTENT_VERSION) return
globalThis.__museVaultCaptureVersion = CONTENT_VERSION

// The local myknow UI is also a web page, but it is not a capture target.
// Do not install the floating tray or drag/hold listeners on local development
// and desktop-app pages. This also prevents dragging cards inside the library
// from opening the browser extension overlay.
function isExcludedPage() {
  const host = location.hostname.toLowerCase()
  return host === 'localhost'
    || host === '127.0.0.1'
    || host === '0.0.0.0'
    || host === '::1'
    || host === '[::1]'
}

if (isExcludedPage()) {
  document.querySelector('#muse-capture-panel')?.remove()
  document.querySelector('#muse-quick-capture')?.remove()
  document.querySelector('#muse-toast')?.remove()
  return
}

let holdTimer
let holdStartPoint
let activeAsset
let hoveredAsset
let lastPointerTarget
let lastPointerPoint = { x: 0, y: 0 }
let panel
let outsideHandler
let panelPositionFrame
let panelRequestId = 0
let quickCapture
let quickCaptureMenu
let quickCaptureButton
let quickMenuToggle
let quickAssetButton
let quickCaptureStatus
let quickFolderSelect
let quickOutsideHandler
let dragSession = 0
let dragEndTimer

const QUICK_CAPTURE_VISIBILITY_KEY = 'muse-quick-capture-visible'

const CARD_SELECTOR = 'a[href], picture, figure, [role="link"], article, li, [class*="card" i], [class*="cover" i]'
const MEDIA_SELECTOR = 'img, video'

function absoluteUrl(value) {
  if (!value) return null
  try { return new URL(value, location.href).href } catch { return value }
}

function mediaUrl(element) {
  const lazyUrl = ['data-original', 'data-src', 'data-lazy-src', 'data-actualsrc']
    .map(name => element.getAttribute?.(name))
    .find(Boolean)
  const directUrl = element.currentSrc || element.src || element.getAttribute?.('src')
  const chosen = directUrl?.startsWith('data:image/gif') && lazyUrl ? lazyUrl : directUrl || lazyUrl
  return absoluteUrl(chosen)
}

function backgroundUrl(element) {
  const value = getComputedStyle(element).backgroundImage
  if (!value || value === 'none') return null
  const match = value.match(/url\((['"]?)(.*?)\1\)/)
  return absoluteUrl(match?.[2])
}

function containsPoint(element, x, y) {
  if (!x && !y) return false
  const rect = element.getBoundingClientRect()
  return rect.width >= 16 && rect.height >= 16 && x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom
}

function mediaAsset(element, forcedUrl) {
  const type = element.tagName === 'VIDEO' ? 'video' : 'image'
  const url = forcedUrl || mediaUrl(element)
  return url ? { target: element, type, mediaUrl: url } : null
}

function bestMediaInside(container, x, y) {
  const candidates = [...container.querySelectorAll(MEDIA_SELECTOR)]
    .map(element => ({ element, url: mediaUrl(element), rect: element.getBoundingClientRect() }))
    .filter(item => item.url && item.rect.width >= 16 && item.rect.height >= 16)
  if (!candidates.length) return null
  const underPointer = candidates.filter(item => containsPoint(item.element, x, y))
  const pool = underPointer.length ? underPointer : candidates
  pool.sort((a, b) => (b.rect.width * b.rect.height) - (a.rect.width * a.rect.height))
  return mediaAsset(pool[0].element, pool[0].url)
}

function resolveAsset(target, point = lastPointerPoint, eventPath = []) {
  if (!(target instanceof Element)) return null
  const x = point?.x || 0
  const y = point?.y || 0

  for (const node of eventPath) {
    if (node instanceof Element && node.matches(MEDIA_SELECTOR)) {
      const asset = mediaAsset(node)
      if (asset) return asset
    }
  }

  const directMedia = target.closest(MEDIA_SELECTOR)
  if (directMedia) {
    const asset = mediaAsset(directMedia)
    if (asset) return asset
  }

  const containers = []
  const nearestCard = target.closest(CARD_SELECTOR)
  if (nearestCard) containers.push(nearestCard)
  let parent = target.parentElement
  for (let depth = 0; parent && depth < 3; depth += 1, parent = parent.parentElement) {
    if (!containers.includes(parent)) containers.push(parent)
  }
  for (const container of containers) {
    const asset = bestMediaInside(container, x, y)
    if (asset && (containsPoint(asset.target, x, y) || container === nearestCard)) return asset
  }

  let backgroundTarget = target
  for (let depth = 0; backgroundTarget && depth < 4; depth += 1, backgroundTarget = backgroundTarget.parentElement) {
    const url = backgroundUrl(backgroundTarget)
    if (url && containsPoint(backgroundTarget, x, y)) return { target: backgroundTarget, type: 'image', mediaUrl: url }
  }

  const anchor = target.closest('a[href]')
  if (anchor) return { target: anchor, type: 'link', mediaUrl: absoluteUrl(anchor.href) }
  return { target, type: /blog|article|post|知乎|博客/i.test(location.href) ? 'blog' : 'page', mediaUrl: null }
}

function readableTitle(asset) {
  const target = asset.target
  if (asset.type === 'image') {
    return target.alt?.trim() || target.getAttribute?.('aria-label')?.trim() || target.title?.trim() || target.closest('figure')?.querySelector('figcaption')?.textContent?.trim() || document.title || '未命名图片'
  }
  if (asset.type === 'video') return target.title?.trim() || target.getAttribute?.('aria-label')?.trim() || document.title || '未命名视频'
  if (asset.type === 'link') return target.textContent?.trim().slice(0, 180) || target.title?.trim() || document.title || '未命名链接'
  return document.title || '未命名素材'
}

function assetText(asset, selection) {
  if (asset.type === 'image') {
    return [asset.target.alt, asset.target.title, asset.target.getAttribute?.('aria-label'), asset.target.closest('figure')?.querySelector('figcaption')?.textContent]
      .filter(Boolean).join('\n').slice(0, 4000)
  }
  if (asset.type === 'video') return [asset.target.title, asset.target.getAttribute?.('aria-label')].filter(Boolean).join('\n').slice(0, 4000)
  if (asset.type === 'link') return (selection || asset.target.textContent || '').trim().slice(0, 30000)
  return (selection || asset.target.innerText || document.body.innerText).slice(0, 250000)
}

function sanitizedSnapshot() {
  const clone = document.documentElement.cloneNode(true)
  clone.querySelectorAll('script, noscript, iframe, object, embed, form, dialog').forEach(node => node.remove())
  clone.querySelectorAll('*').forEach(node => {
    for (const attribute of [...node.attributes]) {
      if (attribute.name.startsWith('on') || attribute.name === 'srcdoc') node.removeAttribute(attribute.name)
    }
  })
  const head = clone.querySelector('head')
  if (head && !head.querySelector('base')) {
    const base = document.createElement('base')
    base.href = location.href
    head.prepend(base)
  }
  return `<!doctype html>\n${clone.outerHTML}`.slice(0, 4_000_000)
}

async function localDataUrl(asset) {
  if (asset.type !== 'image' || !asset.mediaUrl) return null
  if (asset.mediaUrl.startsWith('data:')) return asset.mediaUrl
  // GPT's generated images can be visible in the logged-in page while their
  // signed download request rejects a content-script fetch. Read the already
  // rendered pixels in page context before falling back to network fetches.
  const target = asset.target
  if (target instanceof HTMLImageElement && target.complete && target.naturalWidth > 0) {
    try {
      const maxEdge = 4096
      const scale = Math.min(1, maxEdge / target.naturalWidth, maxEdge / target.naturalHeight)
      const canvas = document.createElement('canvas')
      canvas.width = Math.max(1, Math.round(target.naturalWidth * scale))
      canvas.height = Math.max(1, Math.round(target.naturalHeight * scale))
      canvas.getContext('2d').drawImage(target, 0, 0, canvas.width, canvas.height)
      const rendered = canvas.toDataURL('image/png')
      if (rendered.length <= 11_000_000) return rendered
      const compressed = canvas.toDataURL('image/jpeg', 0.9)
      if (compressed.length <= 11_000_000) return compressed
    } catch {
      // A cross-origin image without CORS taints the canvas; try fetch below.
    }
  }
  let blob
  try {
    if (asset.mediaUrl.startsWith('blob:')) {
      const response = await fetch(asset.mediaUrl)
      if (!response.ok) return null
      blob = await response.blob()
    } else {
      const media = new URL(asset.mediaUrl, location.href)
      // A GPT conversation serves protected images from the same origin. Read
      // those in the page session first so cookies never leave the page.
      if (media.origin !== location.origin) return null
      const response = await fetch(media.href, { credentials: 'same-origin', cache: 'no-store' })
      if (!response.ok) return null
      blob = await response.blob()
    }
  } catch {
    return null
  }
  if (blob.size > 8 * 1024 * 1024) throw new Error('图片超过 8MB，无法从当前网页直接读取')
  if (!blob.type || !blob.type.toLowerCase().startsWith('image/')) return null
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result)
    reader.onerror = () => reject(new Error('无法读取网页中的图片数据'))
    reader.readAsDataURL(blob)
  })
}

function pageLeadImage() {
  const value = document.querySelector('meta[property="og:image"], meta[name="twitter:image"], link[rel="image_src"]')?.content
    || document.querySelector('link[rel="image_src"]')?.href
  return absoluteUrl(value)
}

async function payloadFromAsset(asset, folderId = 'inbox', pagePreviewDataUrl = null) {
  const selection = window.getSelection()?.toString().trim() || ''
  const content = assetText(asset, selection)
  const capturePage = ['page', 'blog'].includes(asset.type)
  const localAssetData = await localDataUrl(asset)
  return {
    source_url: location.href,
    title: readableTitle(asset),
    material_type: asset.type,
    source_name: location.hostname,
    text_content: content,
    selection: selection.slice(0, 30000),
    media_url: asset.mediaUrl,
    thumbnail_url: asset.type === 'image' ? asset.mediaUrl : asset.type === 'video' ? absoluteUrl(asset.target.poster) : capturePage ? pageLeadImage() : null,
    data_url: localAssetData || (capturePage ? pagePreviewDataUrl : null),
    html_content: capturePage ? sanitizedSnapshot() : null,
    folder_id: folderId,
    // This flag is not a background permission grant. It only records that
    // the user explicitly selected this image, allowing a same-origin
    // browser-session fallback if page-context reading is blocked.
    browser_session_capture: asset.type === 'image',
    user_permitted_media: asset.type === 'video',
  }
}

function removePanel({ invalidate = true } = {}) {
  if (invalidate) panelRequestId += 1
  if (dragEndTimer) window.clearTimeout(dragEndTimer)
  dragEndTimer = null
  if (panelPositionFrame) cancelAnimationFrame(panelPositionFrame)
  panelPositionFrame = null
  if (outsideHandler) document.removeEventListener('pointerdown', outsideHandler, true)
  outsideHandler = null
  panel?.remove()
  panel = null
}

function cancelHoldCapture() {
  if (holdTimer) window.clearTimeout(holdTimer)
  holdTimer = null
  holdStartPoint = null
}

function fallbackFolderState() {
  return { items: [{ id: 'inbox', name: '收件箱', count: 0 }], defaultFolder: 'inbox' }
}

function getFolderState() {
  const fallback = fallbackFolderState()
  return new Promise(resolve => {
    let settled = false
    const finish = value => {
      if (settled) return
      settled = true
      clearTimeout(timeout)
      resolve(value)
    }
    const timeout = window.setTimeout(() => finish(fallback), 600)
    try {
      chrome.runtime.sendMessage({ type: 'muse-list-folders' }, result => {
        if (chrome.runtime.lastError) { finish(fallback); return }
        finish(result?.items?.length ? result : fallback)
      })
    } catch { finish(fallback) }
  })
}

function createElement(tag, className, text) {
  const element = document.createElement(tag)
  if (className) element.className = className
  if (text) element.textContent = text
  return element
}

function assetTypeName(asset) {
  return { image: '图片', video: '视频', link: '链接', blog: '博客', page: '网页' }[asset?.type] || '素材'
}

function fillFolderSelect(select, folderState) {
  select.replaceChildren()
  folderState.items.forEach(folder => {
    const option = createElement('option', '', `${folder.name}${folder.count ? ` · ${folder.count}` : ''}`)
    option.value = folder.id
    option.selected = folder.id === folderState.defaultFolder
    select.append(option)
  })
}

function setQuickCaptureStatus(text, state = '') {
  if (!quickCaptureStatus) return
  quickCaptureStatus.textContent = text
  quickCaptureStatus.dataset.state = state
}

function updateQuickAssetButton() {
  if (!quickAssetButton) return
  const available = hoveredAsset && ['image', 'video', 'link'].includes(hoveredAsset.type)
  quickAssetButton.disabled = !available
  const label = quickAssetButton.querySelector('span')
  const hint = quickAssetButton.querySelector('small')
  if (available) {
    label.textContent = `保存鼠标所指${assetTypeName(hoveredAsset)}`
    hint.textContent = readableTitle(hoveredAsset).slice(0, 38)
  } else {
    label.textContent = '保存鼠标所指素材'
    hint.textContent = '先把鼠标放在图片、视频或链接上'
  }
}

function setQuickCaptureOpen(open) {
  if (!quickCapture || !quickMenuToggle) return
  quickCapture.dataset.open = open ? 'true' : 'false'
  quickMenuToggle.setAttribute('aria-expanded', String(open))
  if (quickOutsideHandler) document.removeEventListener('pointerdown', quickOutsideHandler, true)
  quickOutsideHandler = null
  if (!open) return
  updateQuickAssetButton()
  window.setTimeout(() => {
    if (!quickCapture || quickCapture.dataset.open !== 'true') return
    quickOutsideHandler = event => {
      if (quickCapture && !quickCapture.contains(event.target)) setQuickCaptureOpen(false)
    }
    document.addEventListener('pointerdown', quickOutsideHandler, true)
  }, 0)
}

function runtimeMessage(message) {
  return new Promise(resolve => {
    try {
      chrome.runtime.sendMessage(message, result => {
        if (chrome.runtime.lastError) resolve({ error: chrome.runtime.lastError.message })
        else resolve(result || { error: '操作失败' })
      })
    } catch (error) {
      resolve({ error: error.message || '操作失败' })
    }
  })
}

function getQuickCaptureVisibility() {
  return new Promise(resolve => {
    try {
      chrome.storage.local.get(QUICK_CAPTURE_VISIBILITY_KEY, stored => {
        if (chrome.runtime.lastError) resolve(true)
        else resolve(stored?.[QUICK_CAPTURE_VISIBILITY_KEY] !== false)
      })
    } catch {
      resolve(true)
    }
  })
}

function removeQuickCapture() {
  setQuickCaptureOpen(false)
  quickCapture?.remove()
  quickCapture = null
  quickCaptureMenu = null
  quickCaptureButton = null
  quickMenuToggle = null
  quickAssetButton = null
  quickCaptureStatus = null
  quickFolderSelect = null
}

async function closeQuickCapture() {
  removeQuickCapture()
  showToast('悬浮采集窗已关闭，可在扩展弹窗中重新开启')
  await runtimeMessage({ type: 'muse-set-quick-capture-visible', visible: false })
}

async function quickCapturePage(button) {
  button.disabled = true
  setQuickCaptureStatus('正在保存当前网页', 'working')
  const result = await runtimeMessage({ type: 'muse-capture-active-page', folderId: quickFolderSelect?.value || 'inbox' })
  button.disabled = false
  if (result?.error) {
    const message = result.error.includes('未启动') ? '请先启动本机素材库' : result.error
    setQuickCaptureStatus(message, 'error')
    showToast(message)
    return
  }
  const message = result?.deduplicated ? '网页已在素材库中' : '网页已保存，正在整理'
  setQuickCaptureStatus(message, 'success')
  showToast(message)
}

async function quickCaptureHovered(button) {
  if (!hoveredAsset || !['image', 'video', 'link'].includes(hoveredAsset.type)) {
    setQuickCaptureStatus('没有识别到鼠标所指素材', 'error')
    updateQuickAssetButton()
    return
  }
  button.disabled = true
  const asset = hoveredAsset
  setQuickCaptureStatus(`正在保存${assetTypeName(asset)}`, 'working')
  let result
  try {
    result = await sendCapture(asset, quickFolderSelect?.value || 'inbox')
  } catch (error) {
    result = { error: error.message || '保存失败' }
  }
  button.disabled = false
  if (result?.error) {
    setQuickCaptureStatus(result.error.includes('未启动') ? '请先启动本机素材库' : result.error, 'error')
    return
  }
  const message = result?.deduplicated ? '素材已存在，已更新保存位置' : `${assetTypeName(asset)}已保存，正在整理`
  setQuickCaptureStatus(message, 'success')
  showToast(message)
}

async function ensureQuickCapture() {
  if (quickCapture?.isConnected) return
  if (!await getQuickCaptureVisibility()) return
  document.querySelector('#muse-quick-capture')?.remove()
  quickCapture = createElement('aside')
  quickCapture.id = 'muse-quick-capture'
  quickCapture.dataset.open = 'false'

  quickCaptureButton = createElement('button', 'muse-quick-trigger')
  quickCaptureButton.type = 'button'
  quickCaptureButton.setAttribute('aria-label', '一键保存当前网页到 myknow')
  quickCaptureButton.append(createElement('span', 'muse-quick-trigger-mark'), createElement('small', '', '采集'))
  quickCaptureButton.addEventListener('click', () => quickCapturePage(quickCaptureButton))
  quickMenuToggle = createElement('button', 'muse-quick-menu-trigger')
  quickMenuToggle.type = 'button'
  quickMenuToggle.setAttribute('aria-label', '展开快速采集选项')
  quickMenuToggle.setAttribute('aria-expanded', 'false')
  quickMenuToggle.addEventListener('click', () => setQuickCaptureOpen(quickCapture.dataset.open !== 'true'))
  const triggerGroup = createElement('div', 'muse-quick-trigger-group')
  triggerGroup.append(quickCaptureButton, quickMenuToggle)
  const dismissButton = createElement('button', 'muse-quick-dismiss')
  dismissButton.type = 'button'
  dismissButton.setAttribute('aria-label', '关闭悬浮采集窗')
  dismissButton.title = '关闭悬浮采集窗'
  dismissButton.addEventListener('click', closeQuickCapture)

  quickCaptureMenu = createElement('section', 'muse-quick-menu')
  quickCaptureMenu.setAttribute('aria-label', 'myknow 快速采集')
  const header = createElement('header', 'muse-quick-header')
  const headerCopy = createElement('div')
  headerCopy.append(createElement('strong', '', '快速采集'), createElement('span', '', '保存此刻真正想留下的内容'))
  const collapse = createElement('button', 'muse-quick-collapse')
  collapse.type = 'button'
  collapse.setAttribute('aria-label', '收起快速采集')
  collapse.addEventListener('click', () => setQuickCaptureOpen(false))
  header.append(headerCopy, collapse)

  const folderLabel = createElement('label', 'muse-quick-folder')
  folderLabel.append(createElement('span', '', '保存到'))
  quickFolderSelect = createElement('select')
  quickFolderSelect.setAttribute('aria-label', '快速采集目标文件夹')
  quickFolderSelect.append(createElement('option', '', '收件箱'))
  quickFolderSelect.firstElementChild.value = 'inbox'
  quickFolderSelect.addEventListener('change', () => chrome.runtime.sendMessage({ type: 'muse-set-default-folder', folderId: quickFolderSelect.value }))
  folderLabel.append(quickFolderSelect)

  const actions = createElement('div', 'muse-quick-actions')
  const pageButton = createElement('button', 'muse-quick-action muse-quick-primary')
  pageButton.type = 'button'
  pageButton.append(createElement('i', 'muse-action-page'), createElement('span', '', '保存当前网页'), createElement('small', '', '保留页面画面和可搜索正文'))
  pageButton.addEventListener('click', () => quickCapturePage(pageButton))
  quickAssetButton = createElement('button', 'muse-quick-action muse-quick-secondary')
  quickAssetButton.type = 'button'
  quickAssetButton.append(createElement('i', 'muse-action-focus'), createElement('span', '', '保存鼠标所指素材'), createElement('small', '', '先把鼠标放在图片、视频或链接上'))
  quickAssetButton.addEventListener('click', () => quickCaptureHovered(quickAssetButton))
  actions.append(pageButton, quickAssetButton)

  const footer = createElement('footer', 'muse-quick-footer')
  quickCaptureStatus = createElement('span', 'muse-quick-status', '单次保存，不会批量采集')
  const openLibrary = createElement('button', 'muse-quick-library', '打开素材库')
  openLibrary.type = 'button'
  openLibrary.addEventListener('click', () => chrome.runtime.sendMessage({ type: 'muse-open-library' }))
  footer.append(quickCaptureStatus, openLibrary)

  quickCaptureMenu.append(header, folderLabel, actions, footer)
  quickCapture.append(quickCaptureMenu, triggerGroup, dismissButton)
  document.body.append(quickCapture)
  updateQuickAssetButton()

  const folderState = await getFolderState()
  if (!quickFolderSelect?.isConnected) return
  fillFolderSelect(quickFolderSelect, folderState)
}

function clamp(value, min, max) { return Math.max(min, Math.min(max, value)) }

function positionPanel(anchor = {}) {
  if (!panel) return
  if (window.innerWidth <= 560) {
    panel.dataset.positioned = 'true'
    return
  }
  const panelRect = panel.getBoundingClientRect()
  const width = panelRect.width || 360
  const height = panelRect.height || 260
  const margin = 16
  const gap = 14
  const targetRect = anchor.rect || (anchor.target instanceof Element ? anchor.target.getBoundingClientRect() : null)
  const point = anchor.x != null && anchor.y != null
    ? { left: anchor.x, right: anchor.x, top: anchor.y, bottom: anchor.y }
    : targetRect || { left: window.innerWidth / 2, right: window.innerWidth / 2, top: window.innerHeight / 2, bottom: window.innerHeight / 2 }
  const candidates = [
    { left: point.right + gap, top: point.top },
    { left: point.left - width - gap, top: point.top },
    { left: point.left, top: point.bottom + gap },
    { left: point.left, top: point.top - height - gap },
  ]
  const valid = candidates.find(candidate => candidate.left >= margin && candidate.left + width <= window.innerWidth - margin && candidate.top >= margin && candidate.top + height <= window.innerHeight - margin)
  const candidate = valid || candidates[0]
  const left = clamp(candidate.left, margin, Math.max(margin, window.innerWidth - width - margin))
  const top = clamp(candidate.top, margin, Math.max(margin, window.innerHeight - height - margin))
  panel.style.setProperty('--muse-panel-left', `${Math.round(left)}px`)
  panel.style.setProperty('--muse-panel-top', `${Math.round(top)}px`)
  panel.dataset.positioned = 'true'
}

function schedulePanelPosition(anchor) {
  if (panelPositionFrame) cancelAnimationFrame(panelPositionFrame)
  panelPositionFrame = requestAnimationFrame(() => {
    panelPositionFrame = null
    positionPanel(anchor)
  })
}

function showPanel(asset, mode = 'hold', anchor = null) {
  const requestId = ++panelRequestId
  removePanel({ invalidate: false })
  activeAsset = asset
  const typeName = assetTypeName(asset)
  const folderState = fallbackFolderState()

  panel = createElement('section')
  panel.id = 'muse-capture-panel'
  panel.dataset.mode = mode
  panel.dataset.assetType = asset.type
  panel.dataset.positioned = 'false'
  panel.style.pointerEvents = 'auto'

  const header = createElement('header', 'muse-panel-header')
  const mark = createElement('span', 'muse-mark')
  mark.append(createElement('i'), createElement('i'), createElement('i'))
  const heading = createElement('div')
  heading.append(createElement('b', '', `保存${typeName}到素材库`), createElement('span', '', mode === 'drag' ? '拖到面板中央并松手' : '选择文件夹后点击保存'))
  const close = createElement('button', 'muse-close')
  close.type = 'button'
  close.setAttribute('aria-label', '关闭')
  close.addEventListener('click', removePanel)
  header.append(mark, heading, close)

  const dropZone = createElement('div', 'muse-drop-zone')
  dropZone.append(createElement('span', 'muse-drop-icon'), createElement('strong', '', '放到这里'), createElement('small', '', '单次保存，不会批量采集'))
  if (asset.type === 'image' && asset.mediaUrl) {
    const preview = createElement('img', 'muse-preview')
    preview.src = asset.mediaUrl
    preview.alt = ''
    dropZone.prepend(preview)
  }

  const footer = createElement('footer', 'muse-panel-footer')
  const folderLabel = createElement('label')
  folderLabel.append(createElement('span', '', '保存到'))
  const select = createElement('select')
  select.setAttribute('aria-label', '目标文件夹')
  folderState.items.forEach(folder => {
    const option = createElement('option', '', `${folder.name}${folder.count ? ` · ${folder.count}` : ''}`)
    option.value = folder.id
    option.selected = folder.id === folderState.defaultFolder
    select.append(option)
  })
  select.addEventListener('change', () => chrome.runtime.sendMessage({ type: 'muse-set-default-folder', folderId: select.value }))
  folderLabel.append(select)
  const saveButton = createElement('button', 'muse-save', '保存')
  saveButton.type = 'button'
  saveButton.addEventListener('click', () => submit(activeAsset, select.value))
  footer.append(folderLabel, saveButton)

  dropZone.addEventListener('dragenter', event => { event.preventDefault(); dropZone.classList.add('dragging') })
  dropZone.addEventListener('dragover', event => { event.preventDefault(); event.dataTransfer.dropEffect = 'copy' })
  dropZone.addEventListener('dragleave', event => { if (!dropZone.contains(event.relatedTarget)) dropZone.classList.remove('dragging') })
  dropZone.addEventListener('drop', event => { event.preventDefault(); event.stopPropagation(); submit(activeAsset, select.value) })

  panel.append(header, dropZone, footer)
  const panelAnchor = anchor || { target: asset.target }
  document.body.append(panel)
  // Chrome 原生拖拽期间 requestAnimationFrame 可能被延后；先同步定位并显示，
  // 确保 dropZone 在拖拽经过时已经存在且可接收 dragover/drop。
  positionPanel(panelAnchor)
  schedulePanelPosition(panelAnchor)
  getFolderState().then(nextFolderState => {
    if (requestId !== panelRequestId || !panel || !select.isConnected) return
    const currentFolder = select.value
    fillFolderSelect(select, nextFolderState)
    if (nextFolderState.items.some(folder => folder.id === currentFolder)) select.value = currentFolder
  })
  window.setTimeout(() => {
    if (requestId !== panelRequestId || !panel) return
    outsideHandler = event => { if (panel && !panel.contains(event.target)) removePanel() }
    document.addEventListener('pointerdown', outsideHandler, true)
  }, 0)
}

async function sendCapture(asset, folderId, pagePreviewDataUrl = null) {
  const payload = await payloadFromAsset(asset, folderId, pagePreviewDataUrl)
  return new Promise(resolve => {
    chrome.runtime.sendMessage({ type: 'muse-capture', payload }, result => {
      if (chrome.runtime.lastError) resolve({ error: chrome.runtime.lastError.message })
      else resolve(result || { error: '保存失败' })
    })
  })
}

async function submit(asset, folderId = 'inbox', sendResponse, pagePreviewDataUrl = null) {
  removePanel()
  try {
    const result = await sendCapture(asset, folderId, pagePreviewDataUrl)
    if (result?.error) showToast(result.error.includes('未启动') ? '本机素材库未启动' : result.error)
    else showToast(result?.deduplicated ? '素材已存在，已移动到所选文件夹' : `${asset.type === 'image' ? '图片' : asset.type === 'video' ? '视频' : asset.type === 'link' ? '链接' : '网页'}已保存，正在整理`)
    sendResponse?.(result)
    return result
  } catch (error) {
    const result = { error: error.message || '保存失败' }
    showToast(result.error)
    sendResponse?.(result)
    return result
  }
}

function submitCurrentPage(folderId, sendResponse, pagePreviewDataUrl = null) {
  const target = document.querySelector('article, main') || document.body
  const asset = { target, type: /blog|article|post|知乎|博客/i.test(location.href) ? 'blog' : 'page', mediaUrl: null }
  submit(asset, folderId || 'inbox', sendResponse, pagePreviewDataUrl)
}

function showToast(text) {
  document.querySelector('#muse-toast')?.remove()
  const toast = createElement('div', '', text)
  toast.id = 'muse-toast'
  document.body.append(toast)
  window.setTimeout(() => toast.remove(), 2500)
}

document.addEventListener('dragstart', event => {
  // Native drag may suppress pointermove; cancel the long-press path explicitly
  // so it cannot replace the drag drop panel after 650ms.
  cancelHoldCapture()
  dragSession += 1
  dragEndTimer && window.clearTimeout(dragEndTimer)
  dragEndTimer = null
  const asset = resolveAsset(event.target, { x: event.clientX, y: event.clientY }, event.composedPath())
  if (!asset || !['image', 'video', 'link'].includes(asset.type)) return
  activeAsset = asset
  lastPointerPoint = { x: event.clientX, y: event.clientY }
  const rect = asset.target?.getBoundingClientRect?.()
  showPanel(asset, 'drag', rect ? { rect: { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom } } : { x: event.clientX, y: event.clientY })
}, true)

document.addEventListener('dragend', () => {
  cancelHoldCapture()
  if (!panel || panel.dataset.mode !== 'drag') return
  const session = dragSession
  dragEndTimer = window.setTimeout(() => {
    if (session === dragSession) removePanel()
    dragEndTimer = null
  }, 180)
}, true)

// Keep a capture-phase fallback for pages that put another element over the
// drop zone or stop bubbling drag events. The panel itself is the only scope
// where these listeners cancel the browser default and accept the drop.
document.addEventListener('dragover', event => {
  if (!panel || panel.dataset.mode !== 'drag' || !panel.contains(event.target)) return
  event.preventDefault()
  event.stopPropagation()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'
  panel.querySelector('.muse-drop-zone')?.classList.add('dragging')
}, true)

document.addEventListener('drop', event => {
  if (!panel || panel.dataset.mode !== 'drag' || !panel.contains(event.target)) return
  event.preventDefault()
  event.stopPropagation()
  const currentPanel = panel
  const folderId = currentPanel.querySelector('select')?.value || 'inbox'
  currentPanel.querySelector('.muse-drop-zone')?.classList.remove('dragging')
  submit(activeAsset, folderId)
}, true)

document.addEventListener('pointerdown', event => {
  if (event.button !== 0 || event.target.closest('#muse-capture-panel, #muse-quick-capture')) return
  const asset = resolveAsset(event.target, { x: event.clientX, y: event.clientY }, event.composedPath())
  if (!asset || !['image', 'video', 'link'].includes(asset.type)) return
  activeAsset = asset
  holdStartPoint = { x: event.clientX, y: event.clientY }
  holdTimer = window.setTimeout(() => {
    holdTimer = null
    const rect = activeAsset.target?.getBoundingClientRect?.()
    showPanel(activeAsset, 'hold', rect ? { rect: { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom } } : { x: holdStartPoint?.x || lastPointerPoint.x, y: holdStartPoint?.y || lastPointerPoint.y })
  }, 650)
}, true)
document.addEventListener('pointerup', cancelHoldCapture, true)
document.addEventListener('pointermove', event => {
  if (holdTimer && holdStartPoint && Math.hypot(event.clientX - holdStartPoint.x, event.clientY - holdStartPoint.y) > 10) {
    window.clearTimeout(holdTimer)
    holdTimer = null
  }
  lastPointerPoint = { x: event.clientX, y: event.clientY }
  if (event.target !== lastPointerTarget && !event.target.closest('#muse-capture-panel, #muse-quick-capture')) {
    lastPointerTarget = event.target
    hoveredAsset = resolveAsset(event.target, lastPointerPoint, event.composedPath())
    updateQuickAssetButton()
  }
}, { passive: true })
document.addEventListener('pointerover', event => {
  if (event.target.closest('#muse-capture-panel, #muse-quick-capture')) return
  lastPointerTarget = event.target
  hoveredAsset = resolveAsset(event.target, { x: event.clientX, y: event.clientY }, event.composedPath())
  updateQuickAssetButton()
}, { passive: true })

document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && quickCapture?.dataset.open === 'true') setQuickCaptureOpen(false)
})

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'muse-status') { showToast(message.text); return }
  if (message.type === 'muse-quick-capture-visibility') {
    Promise.resolve(message.visible ? ensureQuickCapture() : removeQuickCapture()).then(() => sendResponse({ ok: true }))
    return true
  }
  if (message.type === 'muse-capture-page') { submitCurrentPage(message.folderId, sendResponse, message.pagePreviewDataUrl); return true }
  if (message.type === 'muse-capture-hovered') {
    if (!hoveredAsset || !['image', 'video', 'link'].includes(hoveredAsset.type)) {
      const result = { error: '请先把鼠标放在图片、视频或链接上' }
      showToast(result.error)
      sendResponse(result)
      return
    }
    submit(hoveredAsset, message.folderId || 'inbox', sendResponse)
    return true
  }
})

ensureQuickCapture()
})()
