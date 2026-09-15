import { AlertTriangle, BarChart3, BookOpen, Bot, Check, CheckCheck, ClipboardCopy, Clock3, Copy, ExternalLink, FileDown, FileText, FolderInput, FolderOpen, HardDrive, Image, ImageOff, Library, Link2, LoaderCircle, Maximize2, MonitorDown, Palette, RotateCcw, ShieldAlert, SunDim, Tag, Trash2, Video } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { pasteHint } from '../materials'

const typeIcon = { image: Image, video: Video, document: FileText, presentation: MonitorDown, blog: BookOpen, page: Library, link: Library }
const typeLabel = { image: '图片', video: '视频', document: '文档', presentation: '演示文稿', blog: '博客', page: '网页', link: '链接' }
const statusLabel = { capturing: '正在保存', queued: '等待处理', analyzing: '整理中', ready: '整理完成', partial: '部分完成', failed: '处理失败' }
const stageLabel = { download: '下载文件', classify: '规则分类', thumbnail: '生成缩略图', visual: '视觉分析', ai_enrich: 'AI 整理', export: '离线文档', index: '搜索索引', transcribe: '视频转写' }
const jobStateLabel = { queued: '等待', running: '处理中', done: '完成', dead: '失败', paused: '已暂停' }

const clampUnit = value => Math.max(0, Math.min(1, Number(value) || 0))

function histogramPoints(values, width = 256, height = 112) {
  if (!Array.isArray(values) || values.length < 2) return ''
  const bottom = height - 7
  return values.map((value, index) => {
    const x = (index / (values.length - 1)) * width
    const y = bottom - clampUnit(value) * (height - 16)
    return `${x.toFixed(2)},${y.toFixed(2)}`
  }).join(' ')
}

function RgbHistogram({ histogram }) {
  const series = [
    { key: 'r', label: 'R', color: '#e15b5b', fill: 'rgba(225,91,91,.16)' },
    { key: 'g', label: 'G', color: '#4ba879', fill: 'rgba(75,168,121,.13)' },
    { key: 'b', label: 'B', color: '#5a8cde', fill: 'rgba(90,140,222,.16)' },
  ]
  const hasCurves = series.some(channel => Array.isArray(histogram?.[channel.key]) && histogram[channel.key].length > 1)
  if (!hasCurves) return <p className="visual-insights-empty">尚未生成 RGB 直方图</p>
  return <div className="rgb-histogram" role="img" aria-label="图片 RGB 通道直方图">
    <svg viewBox="0 0 256 112" preserveAspectRatio="none" aria-hidden="true">
      <g className="histogram-grid"><line x1="0" y1="12" x2="256" y2="12" /><line x1="0" y1="56" x2="256" y2="56" /><line x1="0" y1="105" x2="256" y2="105" /></g>
      {series.map(channel => {
        const points = histogramPoints(histogram[channel.key])
        return <g key={channel.key}><polygon points={`0,105 ${points} 256,105`} fill={channel.fill} /><polyline points={points} fill="none" stroke={channel.color} strokeWidth="1.3" vectorEffect="non-scaling-stroke" /></g>
      })}
    </svg>
    <div className="histogram-axis"><span>0</span><span>中间调</span><span>255</span></div>
    <div className="histogram-legend" aria-hidden="true">{series.map(channel => <span key={channel.key} className={`histogram-legend-item histogram-${channel.key}`}><i />{channel.label}</span>)}</div>
  </div>
}

function VideoPreview({ item }) {
  const videoUrl = item?.asset_url || item?.media_url || ''
  const [failed, setFailed] = useState(false)
  useEffect(() => setFailed(false), [item?.id, videoUrl])

  if (!videoUrl) {
    return <div className="video-preview-state"><Video size={26} /><strong>暂无可播放视频</strong><span>这条记录只保存了来源信息，请保持原网页登录后重新拖入视频。</span></div>
  }

  return <>
    {!failed ? <video className="inspector-video" controls preload="metadata" src={videoUrl} aria-label={`检视视频：${item.title}`} onError={() => setFailed(true)} /> : null}
    {failed ? <div className="video-preview-state error" role="alert"><AlertTriangle size={24} /><strong>视频暂时无法播放</strong><span>原网页可能要求登录、链接已过期，或当前格式不受支持。请回到来源页面重新拖入。</span></div> : null}
  </>
}

export function Inspector({ item, folders, aiStatus, view, onPreview, onCopyMaterial, onRevealLocation, onSaveTags, onMoveFolder, onAnalyze, onRetry, onRebuildThumbnail, onRequestExport, onMoveToTrash, onRestore, onPermanentDelete }) {
  const inspectorRef = useRef(null)
  const [tagText, setTagText] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [moving, setMoving] = useState(false)
  const [analyzing, setAnalyzing] = useState(false)
  const [retrying, setRetrying] = useState(false)
  const [rebuildingThumbnail, setRebuildingThumbnail] = useState(false)
  const [exportingFormat, setExportingFormat] = useState('')
  const [previewFailed, setPreviewFailed] = useState(false)
  const [promptCopied, setPromptCopied] = useState(false)
  const [copyingMaterial, setCopyingMaterial] = useState(false)
  const [materialCopied, setMaterialCopied] = useState(false)
  const [confirmAction, setConfirmAction] = useState('')
  const isVideo = item?.material_type === 'video'
  const previewUrl = item?.asset_url || item?.thumbnail_asset_url || item?.thumbnail_url
  const hasPreview = isVideo ? Boolean(item?.asset_url || item?.media_url) : Boolean(previewUrl)
  const recognizedText = item?.text_content?.trim() || ''
  const histogram = item?.histogram && typeof item.histogram === 'object' && !Array.isArray(item.histogram) ? item.histogram : {}
  const palette = Array.isArray(item?.palette) ? item.palette : []
  useEffect(() => { setTagText(item?.tags?.join('，') || ''); setSaved(false); setPreviewFailed(false); setPromptCopied(false); setMaterialCopied(false); setConfirmAction('') }, [item?.id, previewUrl, item?.is_deleted])

  if (!item) return <aside className="inspector" ref={inspectorRef}><div className="inspector-title"><span>素材详情</span></div><div className="empty-inspector"><Library size={25} /><p>选择一条素材后，这里会显示摘要、标签和视觉信息。</p></div></aside>
  const Icon = typeIcon[item.material_type] || FileText

  const saveTags = async event => {
    event.preventDefault()
    if (item.is_demo) return
    setSaving(true)
    const tags = tagText.split(/[，,]/).map(tag => tag.trim()).filter(Boolean)
    try { await onSaveTags(item.id, tags); setSaved(true); window.setTimeout(() => setSaved(false), 1600) } catch { /* App displays the API error. */ } finally { setSaving(false) }
  }

  const moveFolder = async event => {
    setMoving(true)
    try { await onMoveFolder(item.id, event.target.value) } catch { /* App displays the API error. */ } finally { setMoving(false) }
  }

  const runAI = async () => {
    setAnalyzing(true)
    try { await onAnalyze(item.id) } catch { /* App displays the API error. */ } finally { setAnalyzing(false) }
  }

  const retryFailed = async () => {
    setRetrying(true)
    try { await onRetry(item.id) } catch { /* App displays the API error. */ } finally { setRetrying(false) }
  }

  const rebuildThumbnail = async () => {
    setRebuildingThumbnail(true)
    try { await onRebuildThumbnail(item.id) } catch { /* App displays the API error. */ } finally { setRebuildingThumbnail(false) }
  }

  const requestExport = async format => {
    setExportingFormat(format)
    try { await onRequestExport(item.id, format) } catch { /* App displays the API error. */ } finally { setExportingFormat('') }
  }

  const moveToTrash = async () => {
    setMoving(true)
    try { await onMoveToTrash(item.id) } catch { /* App displays the API error. */ } finally { setMoving(false); setConfirmAction('') }
  }

  const restore = async () => {
    setMoving(true)
    try { await onRestore(item.id) } catch { /* App displays the API error. */ } finally { setMoving(false) }
  }

  const permanentlyDelete = async () => {
    setMoving(true)
    try { await onPermanentDelete(item.id) } catch { /* App displays the API error. */ } finally { setMoving(false); setConfirmAction('') }
  }

  const copyPrompt = async () => {
    const promptText = [
      item.prompt_positive ? `Positive Prompt: ${item.prompt_positive}` : '',
      item.prompt_negative ? `Negative Prompt: ${item.prompt_negative}` : '',
      item.verification_checklist ? `Verification: ${item.verification_checklist}` : '',
    ].filter(Boolean).join('\n')
    if (!promptText) return
    const fallbackCopy = () => {
      const textarea = document.createElement('textarea')
      textarea.value = promptText
      textarea.setAttribute('readonly', '')
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      const copied = document.execCommand('copy')
      textarea.remove()
      if (!copied) throw new Error('copy command was rejected')
    }
    try {
      if (navigator.clipboard?.writeText) {
        try { await navigator.clipboard.writeText(promptText) } catch { fallbackCopy() }
      } else {
        fallbackCopy()
      }
      setPromptCopied(true)
      window.setTimeout(() => setPromptCopied(false), 1800)
    } catch {
      setPromptCopied(false)
    }
  }

  const copyMaterial = async () => {
    if (!onCopyMaterial || copyingMaterial) return
    setCopyingMaterial(true)
    try {
      await onCopyMaterial(item)
      setMaterialCopied(true)
      window.setTimeout(() => setMaterialCopied(false), 1800)
    } catch {
      setMaterialCopied(false)
    } finally {
      setCopyingMaterial(false)
    }
  }

  const jobs = item.jobs || []
  const failedJobs = jobs.filter(job => job.state === 'dead')
  const canExport = ['page', 'blog'].includes(item.material_type) && item.snapshot_path
  const canBuildThumbnail = ['image', 'page', 'blog'].includes(item.material_type) && item.has_local_copy
  const promptPositive = item.prompt_positive?.trim() || ''
  const promptNegative = item.prompt_negative?.trim() || ''
  const verificationChecklist = item.verification_checklist?.trim() || ''

  return <aside className="inspector" ref={inspectorRef}>
    <div className="inspector-title"><span>素材详情</span><span className={`item-state ${item.is_deleted ? 'deleted' : item.status}`}>{item.is_demo ? '预览示例' : item.is_deleted ? '回收站' : statusLabel[item.status] || '状态未知'}</span></div>
    <div className="inspector-type"><Icon size={17} /><span>{typeLabel[item.material_type] || '素材'} · {item.source_name || '本机采集'}</span></div>
    <h2 className="ai-readable-title">{item.title}</h2>

    <figure className={`inspector-preview ${hasPreview && !previewFailed ? '' : 'empty'} ${isVideo ? 'video-preview' : ''}`} onDoubleClick={() => { if (!isVideo && previewUrl && !previewFailed) onPreview(item) }} title={!isVideo && previewUrl && !previewFailed ? '双击查看大图' : undefined}>
      {isVideo
        ? <VideoPreview item={item} />
        : previewUrl && !previewFailed
          ? <img src={previewUrl} alt={item.title} width={item.thumbnail_width || undefined} height={item.thumbnail_height || undefined} onError={() => setPreviewFailed(true)} />
          : <div><ImageOff size={24} /><span>暂无可用预览</span></div>}
      {!isVideo && previewUrl && !previewFailed ? <button className="inspector-zoom" type="button" onClick={() => onPreview(item)}><Maximize2 size={14} />查看大图</button> : null}
      <figcaption>{item.material_type === 'image' ? '保存的图片' : item.material_type === 'video' ? '视频检视 · 点击播放' : ['page', 'blog'].includes(item.material_type) ? '网页采集时的页面画面' : '素材预览'}</figcaption>
    </figure>

    <section className="inspector-section ai-readable-section"><span>内容摘要</span><p className="ai-readable-text">{item.ai_summary || '素材已经保存，后台正在整理内容。'}</p>{item.visual_description ? <p className="visual-description ai-readable-text">{item.visual_description}</p> : null}</section>

    {item.material_type === 'image' && (promptPositive || promptNegative || verificationChecklist) ? <section className="inspector-section prompt-section"><div className="prompt-heading"><span>解析提示词</span><button type="button" onClick={copyPrompt} className="prompt-copy-button" title="复制全部解析提示词" aria-label="复制全部解析提示词">{promptCopied ? <CheckCheck size={13} /> : <Copy size={13} />}{promptCopied ? '已复制' : '复制全部'}</button></div>{promptPositive ? <div className="prompt-block"><small>正向提示词</small><p>{promptPositive}</p></div> : null}{promptNegative ? <div className="prompt-block negative"><small>反向提示词</small><p>{promptNegative}</p></div> : null}{verificationChecklist ? <div className="prompt-block verification"><small>核验提示</small><p>{verificationChecklist}</p></div> : null}</section> : null}

    {recognizedText ? <details className="recognized-text-panel"><summary><span>识别文本</span><small>可选中并复制</small></summary><pre className="recognized-text">{recognizedText}</pre></details> : null}

    {item.material_type === 'image' ? <section className="inspector-section visual-insights"><div className="visual-insights-heading"><span><BarChart3 size={14} />色彩与明暗</span><small>本地分析 · RGB 通道</small></div><RgbHistogram histogram={histogram} /><div className="palette-heading"><span>主要颜色</span><small>按占比列出前 5 组</small></div>{palette.length ? <div className="palette-records" aria-label="图片主要颜色及占比">{palette.map((entry, index) => { const ratio = clampUnit(entry.ratio); const fallback = Array.isArray(entry.rgb) ? `rgb(${entry.rgb.join(',')})` : 'transparent'; return <div key={`${entry.hex || entry.rgb || index}`}><span className="palette-swatch" style={{ backgroundColor: entry.hex || fallback }} /><div className="palette-record-main"><div className="palette-record-meta"><code>{entry.hex || '—'}</code><small>{Math.round(ratio * 100)}%</small></div><span className="palette-ratio"><i style={{ width: `${Math.max(2, ratio * 100)}%` }} /></span></div></div> })}</div> : <p className="visual-insights-empty">尚未生成颜色记录</p>}</section> : null}

    {!item.is_demo && (item.status_reason || jobs.length) ? <section className={`inspector-section job-status ${failedJobs.length ? 'has-error' : ''}`}>
      <span>处理状态</span>
      {item.status_reason ? <p className="status-reason"><AlertTriangle size={14} />{item.status_reason}</p> : null}
      {jobs.length ? <div className="job-list">{jobs.map(job => <div key={job.stage} className={job.state}><span>{stageLabel[job.stage] || job.stage}</span><i>{jobStateLabel[job.state] || job.state}</i>{job.last_error ? <small>{job.last_error}</small> : null}</div>)}</div> : null}
      {failedJobs.length ? <button className="retry-jobs" type="button" onClick={retryFailed} disabled={retrying}>{retrying ? <LoaderCircle size={14} /> : <RotateCcw size={14} />}{retrying ? '正在重试' : '重试失败步骤'}</button> : null}
    </section> : null}

    <section className="inspector-section folder-control"><label htmlFor="material-folder"><FolderInput size={14} />保存位置</label><select id="material-folder" value={item.folder_id || 'inbox'} onChange={moveFolder} disabled={item.is_demo || item.is_deleted || moving}>{folders.map(folder => <option key={folder.id} value={folder.id}>{folder.name}</option>)}</select></section>

    <section className="inspector-section"><span>分类</span><div className="tags"><b>{item.category || '未分类'}</b>{item.subcategory ? <b>{item.subcategory}</b> : null}</div></section>

    <form className="tag-editor" onSubmit={saveTags}>
      <label htmlFor="material-tags"><Tag size={14} />标签</label>
      <div><input id="material-tags" value={tagText} onChange={event => setTagText(event.target.value)} placeholder="用逗号分隔多个标签" disabled={item.is_demo || item.is_deleted} /><button type="submit" disabled={item.is_demo || item.is_deleted || saving}>{saving ? <LoaderCircle size={14} /> : saved ? <Check size={14} /> : '保存'}</button></div>
    </form>

    <section className="feature-list">
      <div>{item.is_linked ? <Link2 size={15} /> : <HardDrive size={15} />}<span>{item.is_linked ? '原位置引用' : '本地副本'}</span><i>{item.has_local_copy ? item.is_linked ? '不占副本空间' : '可用' : '仅保留来源'}</i></div>
      <div><Image size={15} /><span>列表缩略图</span><i>{item.thumbnail_state === 'ready' ? `${item.thumbnail_width || '?'} × ${item.thumbnail_height || '?'}` : item.thumbnail_state === 'error' ? '生成失败，可重建' : canBuildThumbnail ? '正在生成' : '不适用'}</i></div>
      <div><Palette size={15} /><span>主色</span><i>{item.palette?.length ? `${item.palette.length} 组` : '尚未分析'}</i></div>
      <div><SunDim size={15} /><span>亮度 / 细节</span><i>{item.mean_brightness != null ? `${Math.round(item.mean_brightness * 100)}% / ${Math.round((item.detail_score || 0) * 100)}%` : '尚未分析'}</i></div>
      <div><Clock3 size={15} /><span>保存时间</span><i>{new Date(item.captured_at * 1000).toLocaleString('zh-CN')}</i></div>
    </section>

    {!item.is_demo ? <section className="inspector-actions">
      {!item.is_deleted && item.has_local_copy ? <button type="button" onClick={copyMaterial} disabled={copyingMaterial}>{copyingMaterial ? <LoaderCircle size={15} /> : materialCopied ? <CheckCheck size={15} /> : <ClipboardCopy size={15} />}{copyingMaterial ? '正在复制' : materialCopied ? `已复制，可按 ${pasteHint()}` : '复制到剪贴板'}</button> : null}
      {!item.is_deleted && item.has_local_copy && onRevealLocation ? <button type="button" onClick={() => onRevealLocation(item)} title="在资源管理器中选中后，可安全拖入其他程序"><FolderOpen size={15} />在文件夹中选中（可拖出）</button> : null}
      {!item.is_deleted ? <button type="button" onClick={runAI} disabled={!aiStatus.configured || analyzing} title="只授权 AI 分析当前这一条素材">{analyzing ? <LoaderCircle size={15} /> : <Bot size={15} />}{aiStatus.configured ? analyzing ? '已加入单条队列' : 'AI 分析本条' : 'AI 尚未配置'}</button> : null}
      {!item.is_deleted && canBuildThumbnail ? <button type="button" onClick={rebuildThumbnail} disabled={rebuildingThumbnail || ['queued', 'running'].includes(item.thumbnail_state)}>{rebuildingThumbnail || ['queued', 'running'].includes(item.thumbnail_state) ? <LoaderCircle size={15} /> : <RotateCcw size={15} />}{rebuildingThumbnail || ['queued', 'running'].includes(item.thumbnail_state) ? '缩略图生成中' : '重建列表缩略图'}</button> : null}
      {canExport ? <div className="offline-actions"><span>离线阅读</span><div>{item.pdf_path ? <a href={`/api/materials/${item.id}/offline/pdf`}><FileDown size={14} />下载 PDF</a> : <button type="button" onClick={() => requestExport('pdf')} disabled={Boolean(exportingFormat)}>{exportingFormat === 'pdf' ? <LoaderCircle size={14} /> : <FileDown size={14} />}生成 PDF</button>}{item.docx_path ? <a href={`/api/materials/${item.id}/offline/docx`}><FileDown size={14} />下载 Word</a> : <button type="button" onClick={() => requestExport('docx')} disabled={Boolean(exportingFormat)}>{exportingFormat === 'docx' ? <LoaderCircle size={14} /> : <FileDown size={14} />}生成 Word</button>}</div>{item.export_state && !['not_requested', 'ready'].includes(item.export_state) ? <span className="export-state"><LoaderCircle size={13} />离线文档生成中</span> : null}</div> : null}
      {item.is_deleted
        ? <div className="trash-actions"><button type="button" onClick={restore} disabled={moving}><RotateCcw size={15} />恢复到素材库</button>{confirmAction === 'permanent' ? <div className="danger-confirm"><ShieldAlert size={14} /><span>永久删除后无法恢复</span><button type="button" onClick={permanentlyDelete} disabled={moving}>{moving ? <LoaderCircle size={14} /> : '确认删除'}</button><button type="button" onClick={() => setConfirmAction('')}>取消</button></div> : <button className="danger-button" type="button" onClick={() => setConfirmAction('permanent')} disabled={moving}><Trash2 size={15} />永久删除</button>}</div>
        : confirmAction === 'trash' ? <div className="danger-confirm"><Trash2 size={14} /><span>素材会进入回收站，可随时恢复</span><button type="button" onClick={moveToTrash} disabled={moving}>{moving ? <LoaderCircle size={14} /> : '确认移入'}</button><button type="button" onClick={() => setConfirmAction('')}>取消</button></div> : <button className="danger-button" type="button" onClick={() => setConfirmAction('trash')} disabled={moving}><Trash2 size={15} />移入回收站</button>}
    </section> : null}

    {item.is_demo ? <p className="demo-note">这是界面预览，不会写入你的素材库。</p> : item.source_url ? <a className="source-link" href={item.source_url} target="_blank" rel="noreferrer"><ExternalLink size={13} />打开原始页面</a> : null}
  </aside>
}
