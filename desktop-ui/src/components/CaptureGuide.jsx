import { Check, Download, FolderInput, LoaderCircle, MousePointer2, Puzzle, X } from 'lucide-react'
import { useState } from 'react'

export function CaptureGuide({ connection, onClose, onPreview }) {
  const [downloadState, setDownloadState] = useState('idle')
  const [downloadMessage, setDownloadMessage] = useState('')

  const downloadExtension = async () => {
    if (downloadState === 'saving') return
    setDownloadState('saving')
    setDownloadMessage('')
    try {
      const nativeApi = window.pywebview?.api
      if (nativeApi?.save_extension) {
        const result = await nativeApi.save_extension()
        if (result?.cancelled) {
          setDownloadState('idle')
          return
        }
        if (!result?.ok) throw new Error(result?.error || '浏览器扩展保存失败')
        setDownloadState('saved')
        setDownloadMessage(`已保存到：${result.path}`)
        return
      }

      const response = await fetch('/api/extension/download')
      if (!response.ok) throw new Error(`下载失败（${response.status}）`)
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = 'myknow-extension.zip'
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
      setDownloadState('downloaded')
      setDownloadMessage('已下载到浏览器默认下载目录。')
    } catch (error) {
      setDownloadState('error')
      setDownloadMessage(error.message || '浏览器扩展下载失败')
    }
  }

  return <section className="capture-guide" aria-labelledby="capture-guide-title">
    <div className="guide-heading">
      <div><h2 id="capture-guide-title">把网页内容变成可找回的素材</h2><p>先选择存放位置，再让本机在后台整理；每次采集都由你主动触发。</p></div>
      <button className="icon-button" onClick={onClose} title="收起采集方法" aria-label="收起采集方法" type="button"><X size={17} /></button>
    </div>
    <div className="guide-steps">
      <div><span><Puzzle size={18} /></span><strong>下载并加载浏览器扩展</strong><p>点击后，安装版会弹出系统保存窗口；选择位置保存 ZIP，解压后在 Chrome/Edge 的开发者模式中加载文件夹。</p><div className="guide-actions"><button className="text-action" type="button" onClick={downloadExtension} disabled={downloadState === 'saving'}>{downloadState === 'saving' ? <LoaderCircle size={14} className="spin" /> : downloadState === 'saved' || downloadState === 'downloaded' ? <Check size={14} /> : <Download size={14} />}{downloadState === 'saving' ? '正在准备扩展…' : downloadState === 'saved' ? '已保存浏览器插件' : downloadState === 'downloaded' ? '已下载浏览器插件' : '下载浏览器插件'}</button></div>{downloadMessage ? <p className={`download-result ${downloadState === 'error' ? 'error' : ''}`} role={downloadState === 'error' ? 'alert' : 'status'}>{downloadMessage}</p> : null}</div>
      <div><span><MousePointer2 size={18} /></span><strong>拖动或使用快捷键</strong><p>拖动媒体会出现投递面板；也可把鼠标停在图片上按素材快捷键，网页另有独立快捷键。</p></div>
      <div><span><FolderInput size={18} /></span><strong>选择位置后再找回</strong><p>在投递面板选文件夹。网页整理完成后可下载离线 PDF/Word；标签可叠加筛选。</p></div>
    </div>
    <div className="guide-footer"><span className={`connection-label ${connection}`}><i />{connection === 'online' ? '本机服务已就绪' : connection === 'offline' ? '本机服务未连接' : '正在检查本机服务'}</span><button className="secondary-button" onClick={onPreview} type="button">先预览示例</button></div>
  </section>
}
