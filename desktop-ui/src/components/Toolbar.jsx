import { ChevronDown, Grid2X2, Grid3X3, Search, Tags, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import { BRIGHTNESS_OPTIONS, COLOR_OPTIONS, TYPE_OPTIONS } from '../materials'
import { ColorWheelFilter } from './ColorWheelFilter'

export function Toolbar({ query, onQuery, materialType, onType, brightness, onBrightness, color, onColor, colorTolerance, onColorTolerance, totalCount, visibleCount, tags, selectedTags, onToggleTag, onRemoveTag, scopeLabel, onClearScope, onClearFilters, isFiltering, trashMode = false, gridDensity, onDensity }) {
  const [showAllTags, setShowAllTags] = useState(false)
  const visibleTags = useMemo(() => {
    if (showAllTags || tags.length <= 12) return tags
    const selected = tags.filter(tag => selectedTags.includes(tag.name))
    const rest = tags.filter(tag => !selectedTags.includes(tag.name))
    return [...selected, ...rest].slice(0, 12)
  }, [showAllTags, tags, selectedTags])

  const typeLabel = TYPE_OPTIONS.find(option => option.id === materialType)?.label
  const brightnessLabel = BRIGHTNESS_OPTIONS.find(option => option.id === brightness)?.label
  const colorLabel = color?.startsWith('#') ? color.toUpperCase() : COLOR_OPTIONS.find(option => option.id === color)?.label
  const activeFilters = [
    query.trim() ? { id: 'query', kind: '搜索', label: query.trim(), remove: () => onQuery('') } : null,
    scopeLabel ? { id: 'scope', kind: '位置', label: scopeLabel, remove: onClearScope } : null,
    materialType ? { id: 'type', kind: '类型', label: typeLabel, remove: () => onType('') } : null,
    brightness !== 'all' ? { id: 'brightness', kind: '亮度', label: brightnessLabel, remove: () => onBrightness('all') } : null,
    color ? { id: 'color', kind: '主色', label: colorLabel, remove: () => onColor('') } : null,
    ...selectedTags.map(tag => ({ id: `tag-${tag}`, kind: '标签', label: tag, remove: () => onRemoveTag(tag) })),
  ].filter(Boolean)

  return <section className="library-controls" aria-label="搜索与筛选">
    <div className="search-row">
      <label className="search"><Search size={18} /><input value={query} onChange={event => onQuery(event.target.value)} placeholder={trashMode ? '搜索回收站素材' : '搜索标题、正文或标签'} aria-label={trashMode ? '搜索回收站' : '搜索素材'} /></label>
      <div className="result-tools">
        <span className="result-count"><strong>{totalCount}</strong> 条素材{visibleCount < totalCount ? <small>已显示 {visibleCount}</small> : null}</span>
        <div className="density-control" role="group" aria-label="网格密度">
          <button type="button" className={gridDensity === 'comfortable' ? 'active' : ''} onClick={() => onDensity('comfortable')} aria-pressed={gridDensity === 'comfortable'} title="画廊视图"><Grid2X2 size={15} /><span>画廊</span></button>
          <button type="button" className={gridDensity === 'compact' ? 'active' : ''} onClick={() => onDensity('compact')} aria-pressed={gridDensity === 'compact'} title="索引视图"><Grid3X3 size={15} /><span>索引</span></button>
        </div>
      </div>
    </div>
    <section className="filter-bar" aria-label="素材筛选">
      <div className="type-filter" role="group" aria-label="素材类型">
        {TYPE_OPTIONS.map(option => <button key={option.id || 'all'} type="button" data-type-filter={option.id || 'all'} className={materialType === option.id ? 'active' : ''} onClick={() => onType(option.id)}>{option.label}</button>)}
      </div>
      <label className="select-filter"><span>亮度</span><select value={brightness} onChange={event => onBrightness(event.target.value)}>{BRIGHTNESS_OPTIONS.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}</select></label>
      <div className="color-filter" role="group" aria-label="主色筛选">
        <span>主色</span>
        <ColorWheelFilter value={color} onChange={onColor} tolerance={colorTolerance} onTolerance={onColorTolerance} />
        {COLOR_OPTIONS.map(option => <button key={option.id || 'all'} type="button" className={`${option.id ? 'color-swatch' : 'all-color'} ${color === option.id ? 'active' : ''}`} style={option.id ? { '--swatch': option.color } : undefined} onClick={() => onColor(option.id)} title={option.label} aria-label={option.label}>{option.id ? null : '全部'}</button>)}
      </div>
    </section>
    {isFiltering || activeFilters.length ? <section className="active-filter-summary" aria-label="当前筛选条件" aria-live="polite">
      <span>当前筛选</span>
      {activeFilters.map(filter => <button key={filter.id} type="button" className="active-filter-chip" onClick={filter.remove} title={`移除${filter.kind}：${filter.label}`}><small>{filter.kind}</small><span>{filter.label}</span><X size={12} /></button>)}
      <button type="button" className="clear-filter-button" onClick={onClearFilters}>清除全部筛选</button>
    </section> : null}
    {!trashMode && tags.length ? <section className={`tag-filter ${showAllTags ? 'expanded' : ''}`} aria-label="标签叠加筛选"><span><Tags size={14} />标签筛选<small>同时满足</small></span><div>{visibleTags.map(tag => {
      const selected = selectedTags.includes(tag.name)
      return <button key={tag.name} type="button" className={selected ? 'active' : ''} onClick={() => onToggleTag(tag.name)} aria-pressed={selected}>{selected ? <X size={12} /> : null}{tag.name}<em>{tag.count}</em></button>
    })}</div>{tags.length > 12 ? <button type="button" className="tag-expand" onClick={() => setShowAllTags(value => !value)}>{showAllTags ? '收起标签' : `更多 ${tags.length - visibleTags.length}`}<ChevronDown size={13} className={showAllTags ? 'up' : ''} /></button> : null}</section> : null}
  </section>
}
