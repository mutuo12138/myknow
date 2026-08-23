import { AlertTriangle, CheckCircle2, FolderOpen, FolderUp, Image, LoaderCircle, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

const SUPPORTED_IMAGE = /\.(jpe?g|png|webp|gif|avif)$/i
const BATCH_SIZE = 20

async function postBatch(files, folderId, signal) {
  const form = new FormData()
  form.append('folder_id', folderId)
  files.forEach(file => {
    form.append('files', file, file.name)
    form.append('relative_paths', file.webkitRelativePath || file.name)
  })
  const response = await fetch('/api/import/images', { method: 'POST', body: form, signal })
  if (!response.ok) {
    let detail = ''
    try { detail = (await response.json()).detail || '' } catch { detail = '' }
    throw new Error(detail || `导入请求失败：${response.status}`)
  }
  return response.json()
}

async function postLinkedFolder(sourceDir, folderId, signal) {
  const response = await fetch('/api/import/link-folder', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source_dir: sourceDir, folder_id: folderId, link_mode: 'auto' }),
    signal,
  })
  if (!response.ok) {
    let detail = ''
    try { detail = (await response.json()).detail || '' } catch { detail = '' }
    throw new Error(detail || `引用请求失败：${response.status}`)
  }
  return response.json()
}

export function LocalImport({ folders, defaultFolderId, onComplete, onClose, onOpenStorageSettings }) {
  const [folderId, setFolderId] = useState(defaultFolderId || 'inbox')
  const [importMode, setImportMode] = useState('copy')
  const [linkedSource, setLinkedSource] = useState('')
  const [storagePath, setStoragePath] = useState('')
  const [selection, setSelection] = useState({ files: [], total: 0, unsupported: 0, folderName: '' })
  const [progress, setProgress] = useState(0)
  const [summary, setSummary] = useState(null)
  const [error, setError] = useState('')
  const [importing, setImporting] = useState(false)
  const controllerRef = useRef(null)

  useEffect(() => {
    let cancelled = false
    fetch('/api/settings/paths').then(response => response.json()).then(value => {
      if (!cancelled) setStoragePath(value.assets || value.data_root || '')
    }).catch(() => {})
    return () => { cancelled = true }
  }, [])

  const selectedFolder = folders.find(folder => folder.id === folderId)
  const percent = selection.files.length ? Math.round(progress / selection.files.length * 100) : 0
  const sizeLabel = useMemo(() => {
    const bytes = selection.files.reduce((total, file) => total + file.size, 0)
    if (!bytes) return '0 MB'
    return `${(bytes / 1024 / 1024).toFixed(bytes > 100 * 1024 * 1024 ? 0 : 1)} MB`
  }, [selection.files])

  const pickFiles = event => {
    const allFiles = Array.from(event.target.files || [])
    const images = allFiles.filter(file => SUPPORTED_IMAGE.test(file.name))
    const firstPath = allFiles[0]?.webkitRelativePath || ''
    setSelection({
      files: images,
      total: allFiles.length,
      unsupported: allFiles.length - images.length,
      folderName: firstPath.split('/')[0] || '',
    })
    setProgress(0)
    setSummary(null)
    setError(images.length ? '' : '这个文件夹里没有当前支持的图片。')
    event.target.value = ''
  }

  const startImport = async () => {
    if ((importMode === 'copy' && !selection.files.length) || (importMode === 'link' && !linkedSource) || importing) return
    setImporting(true)
    setProgress(0)
    setSummary(null)
    setError('')
    const controller = new AbortController()
    controllerRef.current = controller
    const totals = { imported: 0, deduplicated: 0, skipped: selection.unsupported, failed: 0, failedItems: [] }
    let processed = 0
    try {
      if (importMode === 'link') {
        const result = await postLinkedFolder(linkedSource, folderId, controller.signal)
        setProgress(result.imported + result.deduplicated + result.failed)
        setSummary({
          imported: result.imported || 0,
          deduplicated: result.deduplicated || 0,
          skipped: 0,
          failed: result.failed || 0,
          failedItems: result.failed_items || [],
        })
        onComplete()
        return
      }
      for (let index = 0; index < selection.files.length; index += BATCH_SIZE) {
        const batch = selection.files.slice(index, index + BATCH_SIZE)
        try {
          const result = await postBatch(batch, folderId, controller.signal)
          totals.imported += result.imported || 0
          totals.deduplicated += result.deduplicated || 0
          totals.skipped += result.skipped || 0
          totals.failed += result.failed || 0
          totals.failedItems.push(...(result.failed_items || []))
        } catch (requestError) {
          if (requestError.name === 'AbortError') throw requestError
          totals.failed += batch.length
          totals.failedItems.push({ path: batch[0]?.webkitRelativePath || batch[0]?.name, reason: requestError.message })
        }
        processed = Math.min(index + batch.length, selection.files.length)
        setProgress(processed)
      }
      setSummary(totals)
      onComplete()
    } catch (requestError) {
      if (requestError.name === 'AbortError') {
        setError('导入已停止；已经完成的批次会保留在素材库。')
        if (processed) onComplete()
      } else {
        setError(requestError.message || '导入失败。')
      }
    } finally {
      controllerRef.current = null
      setImporting(false)
    }
  }

  const closeOrCancel = () => {
    if (importing) {
      controllerRef.current?.abort()
      return
    }
    onClose()
  }

  const chooseLinkedSource = async () => {
    const nativeApi = window.pywebview?.api
    if (!nativeApi?.choose_import_folder) {
      setError('原位置引用需要使用正式桌面版；浏览器开发模式只能使用复制导入。')
      return
    }
    setError('')
    const result = await nativeApi.choose_import_folder()
    if (result?.ok) setLinkedSource(result.path)
    else if (!result?.cancelled) setError(result?.error || '没有选择源文件夹')
  }

  return <section className="local-import" aria-labelledby="local-import-title">
    <div className="local-import-heading">
      <div><h2 id="local-import-title"><FolderUp size={18} />导入本机图片库</h2><p>{importMode === 'link' ? '只建立原位置引用，不复制图片；原文件移动或磁盘断开后引用会失效。' : '复制到素材库，原文件不会移动；相同内容只保留一份。'}</p></div>
      <button className="icon-button" type="button" onClick={closeOrCancel} title={importing ? '停止导入' : '关闭'} aria-label={importing ? '停止导入' : '关闭'}><X size={17} /></button>
    </div>

    <div className="import-mode-row">
      <label><span>导入方式</span><select value={importMode} onChange={event => { setImportMode(event.target.value); setError(''); setSummary(null) }} disabled={importing}><option value="copy">复制到素材库（占用新空间）</option><option value="link">原位置引用（不复制文件）</option></select></label>
      <div className="import-storage-path"><span>素材库存储</span><code title={storagePath}>{storagePath || '正在读取路径…'}</code>{onOpenStorageSettings ? <button type="button" onClick={onOpenStorageSettings}>调整位置</button> : null}</div>
    </div>
    <div className="local-import-controls">
      {importMode === 'link' ? <button className="directory-picker link-source-picker" type="button" onClick={chooseLinkedSource} disabled={importing}><FolderOpen size={17} /><span>{linkedSource || '选择要引用的本机素材文件夹'}</span></button> : <label className="directory-picker">
        <input type="file" accept="image/jpeg,image/png,image/webp,image/gif,image/avif" webkitdirectory="" directory="" multiple onChange={pickFiles} disabled={importing} />
        <FolderOpen size={17} />
        <span>{selection.folderName || '选择图片文件夹'}</span>
      </label>}
      <label className="import-destination"><span>保存到</span><select value={folderId} onChange={event => setFolderId(event.target.value)} disabled={importing}>{folders.map(folder => <option key={folder.id} value={folder.id}>{folder.name}</option>)}</select></label>
      <button className="import-start" type="button" onClick={startImport} disabled={(importMode === 'copy' ? !selection.files.length : !linkedSource) || importing}>{importing ? <LoaderCircle size={16} /> : <FolderUp size={16} />}{importing ? '正在导入' : importMode === 'link' ? '建立引用' : '开始导入'}</button>
    </div>

    {selection.total ? <div className="import-selection"><Image size={15} /><strong>{selection.files.length} 张图片</strong><span>{sizeLabel}</span><span>目标：{selectedFolder?.name || '收件箱'}</span>{selection.unsupported ? <em>{selection.unsupported} 个非图片文件将跳过</em> : null}</div> : null}
    {importing || progress ? <div className="import-progress" aria-live="polite"><div><span style={{ transform: `scaleX(${percent / 100})` }} /></div><p>{importing ? importMode === 'link' ? '正在建立原位置引用' : `正在复制并建档 ${progress} / ${selection.files.length}` : importMode === 'link' ? '引用处理完成' : `已处理 ${progress} / ${selection.files.length}`}</p></div> : null}
    {summary ? <div className={`import-result ${summary.failed ? 'has-error' : ''}`}><CheckCircle2 size={16} /><span>新增 {summary.imported} 张</span><span>重复 {summary.deduplicated} 张</span><span>跳过 {summary.skipped} 张</span>{summary.failed ? <strong>失败 {summary.failed} 张</strong> : null}</div> : null}
    {error ? <div className="import-message" role="alert"><AlertTriangle size={15} />{error}</div> : null}
    {summary?.failedItems?.length ? <details className="import-failures"><summary>查看失败详情</summary>{summary.failedItems.slice(0, 20).map((item, index) => <p key={`${item.path}-${index}`}>{item.path || '未命名图片'}：{item.reason}</p>)}</details> : null}
  </section>
}
