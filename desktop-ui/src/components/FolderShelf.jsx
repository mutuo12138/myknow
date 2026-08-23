import { Folder, Inbox } from 'lucide-react'

function previewUrl(item) {
  return item.thumbnail_asset_url || item.asset_url || item.thumbnail_url
}

export function FolderShelf({ folders, materials, onPickFolder }) {
  const populated = folders.filter(folder => folder.count > 0)
  const shelfFolders = (populated.length ? populated : folders).slice(0, 7)
  // A single destination is already visible in the left rail. Repeating it as
  // a full-width shelf only pushes the user's actual material below the fold.
  if (shelfFolders.length < 2) return null

  return <section className="folder-shelf" aria-label="快捷文件夹">
    <header className="folder-shelf-heading">
      <div><strong>快捷文件夹</strong><span>{shelfFolders.length} 个位置</span></div>
      <small>点击进入，拖动素材到左侧可整理</small>
    </header>
    <div className="folder-shelf-grid">
      {shelfFolders.map(folder => {
        const previews = materials.filter(item => item.folder_id === folder.id && previewUrl(item)).slice(0, 3)
        const Icon = folder.id === 'inbox' ? Inbox : Folder
        return <button key={folder.id} className="folder-shelf-item" type="button" onClick={() => onPickFolder(folder.id)} title={`打开 ${folder.name}`}>
          <span className={`folder-shelf-preview preview-count-${previews.length}`}>
            {previews.length
              ? previews.map(item => <img key={item.id} src={previewUrl(item)} alt="" width={item.thumbnail_width || undefined} height={item.thumbnail_height || undefined} loading="lazy" decoding="async" />)
              : <Icon size={24} aria-hidden="true" />}
          </span>
          <span className="folder-shelf-meta"><strong>{folder.name}</strong><em>{folder.count}</em></span>
        </button>
      })}
    </div>
  </section>
}
