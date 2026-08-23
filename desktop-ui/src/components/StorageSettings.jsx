import { Check, Clipboard, Database, FolderOpen, HardDrive, LoaderCircle, ScrollText, X } from 'lucide-react'
import { useEffect, useState } from 'react'

const configureScript = 'E:\\ai\\codex文件\\muse-vault\\配置素材中枢路径.ps1'

export function StorageSettings({ onClose }) {
  const [paths, setPaths] = useState(null)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)
  const [changing, setChanging] = useState(false)
  const [pendingPaths, setPendingPaths] = useState(null)
  const [notice, setNotice] = useState('')

  useEffect(() => {
    let cancelled = false
    fetch('/api/settings/paths').then(async response => {
      if (!response.ok) throw new Error(`请求失败：${response.status}`)
      return response.json()
    }).then(value => { if (!cancelled) setPaths(value) })
      .catch(requestError => { if (!cancelled) setError(requestError.message || '无法读取存放路径。') })
    return () => { cancelled = true }
  }, [])

  const copyConfigurePath = async () => {
    await navigator.clipboard.writeText(configureScript)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1600)
  }

  const choosePaths = async () => {
    setChanging(true)
    setNotice('')
    try {
      const nativeApi = window.pywebview?.api
      if (!nativeApi?.configure_paths) {
        await copyConfigurePath()
        setNotice('浏览器模式已复制配置入口；运行该脚本即可打开系统目录选择器。')
        return
      }
      const result = await nativeApi.configure_paths()
      if (result?.ok) {
        setPendingPaths(result)
        setNotice('新位置已保存，重启 myknow 后生效。')
      } else if (!result?.cancelled) {
        setNotice(result?.error || '路径没有修改。')
      }
    } catch (requestError) {
      setNotice(requestError.message || '无法打开目录选择器。')
    } finally {
      setChanging(false)
    }
  }

  return <section className="storage-settings" aria-labelledby="storage-settings-title">
    <div className="storage-settings-heading">
      <div><h2 id="storage-settings-title"><HardDrive size={18} />存放位置与日志</h2><p>当前进程使用以下位置；新路径会在下次启动后生效。</p></div>
      <button className="icon-button" type="button" onClick={onClose} title="关闭" aria-label="关闭"><X size={17} /></button>
    </div>
    {paths ? <div className="storage-path-list">
      <div><FolderOpen size={16} /><span>素材与数据</span><code>{paths.data_root}</code></div>
      <div><Database size={16} /><span>数据库</span><code>{paths.database}</code></div>
      <div><ScrollText size={16} /><span>运行日志</span><code>{paths.logs}</code></div>
    </div> : error ? <p className="storage-error">{error}</p> : <p className="storage-loading">正在读取路径</p>}
    {pendingPaths ? <div className="pending-storage-path"><strong>下次启动</strong><span>{pendingPaths.data_root}</span><span>{pendingPaths.log_root}</span></div> : null}
    {notice ? <p className="storage-notice">{notice}</p> : null}
    <div className="storage-settings-footer"><span>原生窗口可直接选择；浏览器开发模式使用配置脚本。</span><div><button className="storage-primary" type="button" onClick={choosePaths} disabled={changing}>{changing ? <LoaderCircle size={14} /> : <HardDrive size={14} />}{changing ? '正在选择' : '选择新路径'}</button><button type="button" onClick={copyConfigurePath}>{copied ? <Check size={14} /> : <Clipboard size={14} />}{copied ? '路径已复制' : '复制脚本入口'}</button></div></div>
  </section>
}
