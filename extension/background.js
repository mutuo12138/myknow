const HOST = 'http://127.0.0.1:8765'
const MAX_BROWSER_IMAGE_BYTES = 8 * 1024 * 1024
const MAX_BROWSER_VIDEO_BYTES = 120 * 1024 * 1024
const MAX_CAPTURE_URL_CHARS = 4000
const CONTENT_VERSION = '0.7.7-stable-r6'
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

function sameOriginMedia(payload) {
  try {
    return new URL(payload.source_url || '').origin === new URL(payload.media_url || '').origin
  } catch {
    return false
  }
}

function imageMimeFromBytes(bytes, declaredMime) {
  const mime = (declaredMime || '').split(';')[0].trim().toLowerCase()
  if (mime.startsWith('image/')) return mime
  if (bytes.length >= 8 && bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47 && bytes[4] === 0x0d && bytes[5] === 0x0a && bytes[6] === 0x1a && bytes[7] === 0x0a) return 'image/png'
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) return 'image/jpeg'
  if (bytes.length >= 6 && String.fromCharCode(...bytes.subarray(0, 6)) === 'GIF89a') return 'image/gif'
  if (bytes.length >= 12 && String.fromCharCode(...bytes.subarray(0, 4)) === 'RIFF' && String.fromCharCode(...bytes.subarray(8, 12)) === 'WEBP') return 'image/webp'
  if (bytes.length >= 2 && bytes[0] === 0x42 && bytes[1] === 0x4d) return 'image/bmp'
  if (bytes.length >= 4 && ((bytes[0] === 0x49 && bytes[1] === 0x49 && bytes[2] === 0x2a && bytes[3] === 0x00) || (bytes[0] === 0x4d && bytes[1] === 0x4d && bytes[2] === 0x00 && bytes[3] === 0x2a))) return 'image/tiff'
  return null
}

function videoMimeFromBytes(bytes, declaredMime) {
  const mime = (declaredMime || '').split(';')[0].trim().toLowerCase()
  if (mime.startsWith('video/')) return mime
  if (bytes.length >= 12 && String.fromCharCode(...bytes.subarray(4, 8)) === 'ftyp') return 'video/mp4'
  if (bytes.length >= 4 && bytes[0] === 0x1a && bytes[1] === 0x45 && bytes[2] === 0xdf && bytes[3] === 0xa3) return 'video/webm'
  if (bytes.length >= 4 && String.fromCharCode(...bytes.subarray(0, 4)) === 'OggS') return 'video/ogg'
  return null
}

async function browserImageDataUrl(url, { allowSession = false } = {}) {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 15000)
  const credentialModes = allowSession ? ['omit', 'include'] : ['omit']
  let lastError = null
  try {
    for (const credentials of credentialModes) {
      try {
        const response = await fetch(url, { credentials, cache: 'no-store', signal: controller.signal })
        if (!response.ok) throw new Error(`图片请求返回 ${response.status}`)
        const declaredSize = Number(response.headers.get('content-length') || 0)
        if (declaredSize > MAX_BROWSER_IMAGE_BYTES) throw new Error('图片超过 8MB')
        const bytes = new Uint8Array(await response.arrayBuffer())
        if (bytes.byteLength > MAX_BROWSER_IMAGE_BYTES) throw new Error('图片超过 8MB')
        const mime = imageMimeFromBytes(bytes, response.headers.get('content-type'))
        if (!mime) throw new Error('目标内容不是可识别的图片')
        return `data:${mime};base64,${bytesToBase64(bytes)}`
      } catch (error) {
        lastError = error
      }
    }
    throw lastError || new Error('无法读取图片')
  } finally {
    clearTimeout(timeout)
  }
}

async function browserVideoDataUrl(url, { allowSession = false } = {}) {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 120000)
  const credentialModes = allowSession ? ['omit', 'include'] : ['omit']
  let lastError = null
  try {
    for (const credentials of credentialModes) {
      try {
        const response = await fetch(url, { credentials, cache: 'no-store', signal: controller.signal })
        if (!response.ok) throw new Error(`视频请求返回 ${response.status}`)
        const declaredSize = Number(response.headers.get('content-length') || 0)
        if (declaredSize > MAX_BROWSER_VIDEO_BYTES) throw new Error('视频超过 120MB')
        const bytes = new Uint8Array(await response.arrayBuffer())
        if (bytes.byteLength > MAX_BROWSER_VIDEO_BYTES) throw new Error('视频超过 120MB')
        const mime = videoMimeFromBytes(bytes, response.headers.get('content-type'))
        if (!mime) throw new Error('目标内容不是可识别的视频')
        return `data:${mime};base64,${bytesToBase64(bytes)}`
      } catch (error) {
        lastError = error
      }
    }
    throw lastError || new Error('无法读取视频')
  } finally {
    clearTimeout(timeout)
  }
}

async function prepareCapture(payload) {
  let prepared = payload
  if (payload.material_type === 'video') {
    if (!payload.data_url && payload.media_url) {
      try {
        prepared = {
          ...payload,
          data_url: await browserVideoDataUrl(payload.media_url, {
            allowSession: payload.user_permitted_media === true && sameOriginMedia(payload),
          }),
        }
      } catch (error) {
        const reason = error?.message ? `：${error.message}` : ''
        throw new Error(`无法从当前浏览器下载视频${reason}。请保持原网页登录后重新拖入`)
      }
    }
  } else if (payload.material_type === 'image' && !payload.data_url && payload.media_url) {
    try {
      prepared = {
        ...payload,
        data_url: await browserImageDataUrl(payload.media_url, {
          // Session credentials are only considered after an anonymous read
          // fails, and only for an explicit same-origin image selection.
          allowSession: payload.browser_session_capture === true && sameOriginMedia(payload),
        }),
      }
    } catch (error) {
      const reason = error?.message ? `：${error.message}` : ''
      throw new Error(`无法从当前浏览器读取这张图片${reason}。请保持 GPT 页面登录后重新拖入`)
    }
  }
  return normalizeCapturePayload(prepared)
}

function normalizeCapturePayload(payload) {
  const next = { ...payload }
  // A rendered image/video is already in data_url; discard only oversized
  // remote references that would otherwise fail API validation.
  if (typeof next.media_url === 'string' && next.media_url.length > MAX_CAPTURE_URL_CHARS && next.data_url) next.media_url = null
  if (typeof next.thumbnail_url === 'string' && next.thumbnail_url.length > MAX_CAPTURE_URL_CHARS && next.data_url) next.thumbnail_url = null
  if (typeof next.title === 'string') next.title = next.title.slice(0, 500)
  if (typeof next.text_content === 'string') next.text_content = next.text_content.slice(0, 250000)
  if (typeof next.selection === 'string') next.selection = next.selection.slice(0, 30000)
  return next
}

async function responseErrorMessage(response) {
  let body = null
  try { body = await response.json() } catch { body = null }
  const detail = body?.detail
  if (Array.isArray(detail)) {
    return detail.map(item => {
      const location = Array.isArray(item?.loc) ? item.loc.filter(Boolean).join('.') : ''
      return location ? `${location}：${item.msg || '字段无效'}` : (item.msg || '提交字段无效')
    }).join('；')
  }
  return typeof detail === 'string' ? detail : ''
}

async function saveCapture(payload) {
  const prepared = await prepareCapture(payload)
  const response = await fetch(`${HOST}/api/captures`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(prepared) })
  if (!response.ok) {
    const detail = await responseErrorMessage(response)
    throw new Error(detail ? `素材库拒绝了这次采集：${detail}` : `素材库请求失败：${response.status}`)
  }
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
      browser_session_capture: info.mediaType === 'image' && sameOriginMedia({ source_url: info.pageUrl || tab.url, media_url: info.srcUrl }),
      user_permitted_media: info.mediaType === 'video',
    })
    chrome.tabs.sendMessage(tab.id, { type: 'muse-status', text: data.deduplicated ? '素材已在本机库中' : '已保存到本机素材库' })
  } catch (error) {
    const message = error?.message?.startsWith('无法从当前浏览器读取这张图片') || error?.message?.startsWith('无法从当前浏览器下载视频')
      ? error.message
      : '本机素材库未启动，请先运行 myknow'
    chrome.tabs.sendMessage(tab.id, { type: 'muse-status', text: message })
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
