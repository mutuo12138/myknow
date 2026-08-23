const extensionApi = globalThis.chrome?.runtime ? globalThis.chrome : {
  runtime: {
    lastError: null,
    sendMessage(message, callback) {
      if (message.type === 'muse-list-folders') callback?.({ items: [{ id: 'inbox', name: '收件箱', count: 24 }], defaultFolder: 'inbox' })
      else if (message.type === 'muse-get-quick-capture-visibility') callback?.({ visible: true })
      else if (message.type === 'muse-set-quick-capture-visible') callback?.({ ok: true, visible: message.visible !== false })
      else callback?.({})
    },
  },
  commands: {
    getAll(callback) {
      callback([
        { name: 'capture-hovered-asset', shortcut: 'Alt+Shift+I' },
        { name: 'capture-current-page', shortcut: 'Alt+Shift+S' },
      ])
    },
  },
  tabs: { create() {} },
}

const connection = document.querySelector('#connection')
const connectionText = connection.querySelector('span')
const result = document.querySelector('#result')
const captureButton = document.querySelector('#capture')
const folderSelect = document.querySelector('#folder')
const shortcutAsset = document.querySelector('#shortcut-asset')
const shortcutPage = document.querySelector('#shortcut-page')
const quickCaptureToggle = document.querySelector('#quick-capture-enabled')
const quickCaptureHint = document.querySelector('#quick-capture-hint')

function renderQuickCapturePreference(visible) {
  quickCaptureToggle.checked = visible
  quickCaptureHint.textContent = visible ? '显示在普通网页右侧' : '已关闭，需要时可重新开启'
}

async function loadQuickCapturePreference() {
  return new Promise(resolve => {
    extensionApi.runtime.sendMessage({ type: 'muse-get-quick-capture-visibility' }, response => {
      renderQuickCapturePreference(response?.visible !== false)
      resolve(true)
    })
  })
}

async function loadFolders() {
  return new Promise(resolve => {
    extensionApi.runtime.sendMessage({ type: 'muse-list-folders' }, data => {
      if (!data?.items?.length) { resolve(false); return }
      folderSelect.replaceChildren(...data.items.map(folder => {
        const option = document.createElement('option')
        option.value = folder.id
        option.textContent = `${folder.name}${folder.count ? ` · ${folder.count}` : ''}`
        option.selected = folder.id === data.defaultFolder
        return option
      }))
      resolve(true)
    })
  })
}

async function checkHost() {
  connection.className = ''
  connectionText.textContent = '正在检查本机服务'
  try {
    const response = await fetch('http://127.0.0.1:8765/api/health')
    const data = await response.json()
    if (!response.ok || !data.ok) throw new Error('host unavailable')
    connection.className = 'online'
    connectionText.textContent = '本机素材库已连接'
    return true
  } catch {
    connection.className = 'offline'
    connectionText.textContent = '请先启动 myknow'
    return false
  }
}

function loadShortcuts() {
  extensionApi.commands.getAll(commands => {
    const byName = Object.fromEntries(commands.map(command => [command.name, command.shortcut || '未分配']))
    shortcutAsset.textContent = byName['capture-hovered-asset'] || '未分配'
    shortcutPage.textContent = byName['capture-current-page'] || '未分配'
  })
}

document.querySelector('#check').addEventListener('click', checkHost)
document.querySelector('#open-library').addEventListener('click', () => extensionApi.tabs.create({ url: 'http://127.0.0.1:8765/' }))
document.querySelector('#edit-shortcuts').addEventListener('click', () => {
  const url = navigator.userAgent.includes('Edg/') ? 'edge://extensions/shortcuts' : 'chrome://extensions/shortcuts'
  extensionApi.tabs.create({ url })
})
folderSelect.addEventListener('change', () => extensionApi.runtime.sendMessage({ type: 'muse-set-default-folder', folderId: folderSelect.value }))
quickCaptureToggle.addEventListener('change', () => {
  const requested = quickCaptureToggle.checked
  quickCaptureToggle.disabled = true
  quickCaptureHint.textContent = requested ? '正在显示悬浮窗' : '正在关闭悬浮窗'
  extensionApi.runtime.sendMessage({ type: 'muse-set-quick-capture-visible', visible: requested }, response => {
    quickCaptureToggle.disabled = false
    if (extensionApi.runtime.lastError || response?.error) {
      renderQuickCapturePreference(!requested)
      quickCaptureHint.textContent = '修改失败，请重新加载扩展后再试'
      return
    }
    renderQuickCapturePreference(response?.visible !== false)
  })
})

captureButton.addEventListener('click', async () => {
  result.textContent = ''
  if (!await checkHost()) { result.textContent = '本机服务未启动，暂时无法保存。'; return }
  captureButton.disabled = true
  extensionApi.runtime.sendMessage({ type: 'muse-capture-active-page', folderId: folderSelect.value }, response => {
    captureButton.disabled = false
    if (extensionApi.runtime.lastError || response?.error) { result.textContent = '当前页面不允许扩展读取，请使用右键保存。'; return }
    result.textContent = response?.deduplicated ? '这条页面已经在素材库中。' : '已保存，正在自动整理。'
  })
})

Promise.all([checkHost(), loadFolders(), loadQuickCapturePreference()])
loadShortcuts()
