const HOST = 'http://127.0.0.1:8765'
const MAX_BROWSER_IMAGE_BYTES = 8 * 1024 * 1024
const CONTENT_VERSION = '0.7.2'
const QUICK_CAPTURE_VISIBILITY_KEY = 'muse-quick-capture-visible'

function isExcludedUrl(value) {
  try {
    const url = new URL(value || '')
    const host = url.hostname.toLowerCase()
    return host === 'localhost' || host === '127.0.0.1' || host === '0.0.0.0' || host === '::1' || host === '[::1]'
  } catch {
    return true
  }
}

async function ensureCaptureInjected(tabId) {
  try {
    const [probe] = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => globalThis.__museVaultCaptureVersion || '',
    })
    if (probe?.result === CONTENT_VERSION) return true
    await chrome.scripting.insertCSS({ target: { tabId }, files: ['capture.css'] })
    await chrome.scripting.executeScript({ target: { tabId }, files: ['content.js'] })
    return true
  } catch {
    return false
  }
}

async function refreshOpenTabs() {
  const tabs = await chrome.tabs.query({ url: ['http://*/*', 'https://*/*'] })
  await Promise.allSettled(tabs.filter(tab => tab.id && !isExcludedUrl(tab.url)).map(tab => ensureCaptureInjected(tab.id)))
}

async function setQuickCaptureVisibility(visible) {
  const nextVisible = visible !== false
  await chrome.storage.local.set({ [QUICK_CAPTURE_VISIBILITY_KEY]: nextVisible })
  const tabs = await chrome.tabs.query({ url: ['http://*/*', 'https://*/*'] })
  await Promise.allSettled(tabs.filter(tab => tab.id).map(async tab => {
    if (isExcludedUrl(tab.url)) return
    await ensureCaptureInjected(tab.id)
    return chrome.tabs.sendMessage(tab.id, { type: 'muse-quick-capture-visibility', visible: nextVisible })
  }))
  return { ok: true, visible: nextVisible }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({ id: 'muse-page', title: '保存当前页面到 myknow', contexts: ['page'] })
    chrome.contextMenus.create({ id: 'muse-selection', title: '保存选中文字到 myknow', contexts: ['selection'] })
    chrome.contextMenus.create({ id: 'muse-image', title: '保存图片到 myknow', contexts: ['image'] })
    chrome.contextMenus.create({ id: 'muse-video', title: '保存视频引用到 myknow', contexts: ['video'] })
    chrome.contextMenus.create({ id: 'muse-link', title: '保存链接到 myknow', contexts: ['link'] })
  })
})

chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  const tab = await chrome.tabs.get(tabId).catch(() => null)
  if (tab?.status === 'complete' && /^https?:/i.test(tab.url || '') && !isExcludedUrl(tab.url)) ensureCaptureInjected(tabId)
})

function materialType(info) {
  if (info.mediaType === 'image') return 'image'
  if (info.mediaType === 'video') return 'video'
  if (info.selectionText) return 'document'
  if (info.linkUrl) return 'link'
  return /blog|article|知乎|博客/i.test(info.pageUrl || '') ? 'blog' : 'page'
}

function bytesToBase64(bytes) {
  let binary = ''
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000))
  }
  return btoa(binary)
}

async function browserImageDataUrl(url) {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 15000)
  try {
    // Never persist authenticated page cookies by default. Private assets can
    // be enabled explicitly later through a user-permission control.
    const response = await fetch(url, { credentials: 'omit', cache: 'force-cache', signal: controller.signal })
    if (!response.ok) throw new Error(`图片请求返回 ${response.status}`)
    const mime = response.headers.get('content-type')?.split(';')[0] || ''
    if (!mime.startsWith('image/')) throw new Error('目标内容不是图片')
    const declaredSize = Number(response.headers.get('content-length') || 0)
    if (declaredSize > MAX_BROWSER_IMAGE_BYTES) throw new Error('图片超过 8MB')
    const bytes = new Uint8Array(await response.arrayBuffer())
    if (bytes.byteLength > MAX_BROWSER_IMAGE_BYTES) throw new Error('图片超过 8MB')
    return `data:${mime};base64,${bytesToBase64(bytes)}`
  } finally {
    clearTimeout(timeout)
  }
}

async function prepareCapture(payload) {
  if (payload.material_type !== 'image' || payload.data_url || !payload.media_url) return payload
  try {
    return { ...payload, data_url: await browserImageDataUrl(payload.media_url) }
  } catch {
    return payload
  }
}

async function saveCapture(payload) {
  const prepared = await prepareCapture(payload)
  const response = await fetch(`${HOST}/api/captures`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(prepared) })
  if (!response.ok) throw new Error(`myknow host returned ${response.status}`)
  return response.json()
}

async function listFolders() {
  const response = await fetch(`${HOST}/api/folders`)
  if (!response.ok) throw new Error('无法读取素材文件夹')
  const data = await response.json()
  const stored = await chrome.storage.local.get('muse-default-folder')
  const defaultFolder = data.items.some(folder => folder.id === stored['muse-default-folder']) ? stored['muse-default-folder'] : 'inbox'
  return { items: data.items, defaultFolder }
}

async function pagePreview(tab) {
  try {
    return await chrome.tabs.captureVisibleTab(tab.windowId, { format: 'jpeg', quality: 72 })
  } catch {
    return null
  }
}

async function sendPageCapture(tab, folderId) {
  await ensureCaptureInjected(tab.id)
  const pagePreviewDataUrl = await pagePreview(tab)
  return chrome.tabs.sendMessage(tab.id, { type: 'muse-capture-page', folderId, pagePreviewDataUrl })
}

async function captureActiveTab(messageType) {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
  if (!tab?.id || !/^https?:/i.test(tab.url || '')) throw new Error('当前页面不允许采集')
  if (isExcludedUrl(tab.url)) throw new Error('myknow 本机页面不启用浏览器采集')
  await ensureCaptureInjected(tab.id)
  const { defaultFolder } = await listFolders()
  const result = messageType === 'muse-capture-page'
    ? await sendPageCapture(tab, defaultFolder)
    : await chrome.tabs.sendMessage(tab.id, { type: messageType, folderId: defaultFolder })
  if (result?.error) throw new Error(result.error)
  return result
}

function showCommandFailure() {
  chrome.action.setBadgeBackgroundColor({ color: '#d86d59' })
  chrome.action.setBadgeText({ text: '!' })
  setTimeout(() => chrome.action.setBadgeText({ text: '' }), 2500)
}

chrome.commands.onCommand.addListener(command => {
  const messageType = command === 'capture-hovered-asset' ? 'muse-capture-hovered' : command === 'capture-current-page' ? 'muse-capture-page' : null
  if (messageType) captureActiveTab(messageType).catch(showCommandFailure)
})

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  try {
    if (isExcludedUrl(tab?.url || info.pageUrl)) return
    const { defaultFolder } = await listFolders()
    if (info.menuItemId === 'muse-page') {
      await sendPageCapture(tab, defaultFolder)
      return
    }
    const data = await saveCapture({
      source_url: info.pageUrl || info.linkUrl || tab.url,
      title: info.selectionText?.slice(0, 90) || tab.title || '未命名素材',
      material_type: materialType(info),
      source_name: new URL(info.pageUrl || tab.url).hostname,
      text_content: info.selectionText || '',
      selection: info.selectionText || '',
      media_url: info.srcUrl || info.linkUrl || null,
      thumbnail_url: info.srcUrl || null,
      folder_id: defaultFolder,
      user_permitted_media: false,
    })
    chrome.tabs.sendMessage(tab.id, { type: 'muse-status', text: data.deduplicated ? '素材已在本机库中' : '已保存到本机素材库' })
  } catch {
    chrome.tabs.sendMessage(tab.id, { type: 'muse-status', text: '本机素材库未启动，请先运行 myknow' })
  }
})

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'muse-open-library') {
    chrome.tabs.create({ url: 'http://127.0.0.1:8765/' }).then(() => sendResponse({ ok: true })).catch(error => sendResponse({ error: error.message }))
    return true
  }
  if (message.type === 'muse-capture-active-page') {
    Promise.resolve(sender.tab?.id ? sender.tab : null).then(async senderTab => {
      const tab = senderTab || (await chrome.tabs.query({ active: true, currentWindow: true }))[0]
      if (!tab?.id || !/^https?:/i.test(tab.url || '')) throw new Error('当前页面不允许采集')
      if (isExcludedUrl(tab.url)) throw new Error('myknow 本机页面不启用浏览器采集')
      return sendPageCapture(tab, message.folderId || 'inbox')
    }).then(sendResponse).catch(error => sendResponse({ error: error.message }))
    return true
  }
  if (message.type === 'muse-capture') {
    saveCapture(message.payload).then(sendResponse).catch(error => sendResponse({ error: error.message }))
    return true
  }
  if (message.type === 'muse-list-folders') {
    listFolders().then(sendResponse).catch(error => sendResponse({ error: error.message }))
    return true
  }
  if (message.type === 'muse-set-default-folder') {
    chrome.storage.local.set({ 'muse-default-folder': message.folderId }).then(() => sendResponse({ ok: true }))
    return true
  }
  if (message.type === 'muse-get-quick-capture-visibility') {
    chrome.storage.local.get(QUICK_CAPTURE_VISIBILITY_KEY).then(stored => sendResponse({ visible: stored[QUICK_CAPTURE_VISIBILITY_KEY] !== false }))
    return true
  }
  if (message.type === 'muse-set-quick-capture-visible') {
    setQuickCaptureVisibility(message.visible).then(sendResponse).catch(error => sendResponse({ error: error.message }))
    return true
  }
})

refreshOpenTabs().catch(() => {})
