import { Check, Pipette, SlidersHorizontal, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { COLOR_OPTIONS } from '../materials'

function hslToHex(hue, saturation = 72, lightness = 52) {
  const s = saturation / 100
  const l = lightness / 100
  const chroma = (1 - Math.abs(2 * l - 1)) * s
  const part = ((hue / 60) % 2 + 2) % 2
  const x = chroma * (1 - Math.abs(part - 1))
  const match = l - chroma / 2
  let rgb = [0, 0, 0]
  if (hue < 60) rgb = [chroma, x, 0]
  else if (hue < 120) rgb = [x, chroma, 0]
  else if (hue < 180) rgb = [0, chroma, x]
  else if (hue < 240) rgb = [0, x, chroma]
  else if (hue < 300) rgb = [x, 0, chroma]
  else rgb = [chroma, 0, x]
  return '#' + rgb.map(channel => Math.round((channel + match) * 255).toString(16).padStart(2, '0')).join('')
}

function colorHue(color) {
  const normalized = color.startsWith('#') ? color : '#2f80b8'
  const red = parseInt(normalized.slice(1, 3), 16) / 255
  const green = parseInt(normalized.slice(3, 5), 16) / 255
  const blue = parseInt(normalized.slice(5, 7), 16) / 255
  const max = Math.max(red, green, blue)
  const min = Math.min(red, green, blue)
  const delta = max - min
  if (!delta) return 210
  let hue = 0
  if (max === red) hue = ((green - blue) / delta) % 6
  else if (max === green) hue = (blue - red) / delta + 2
  else hue = (red - green) / delta + 4
  return (hue * 60 + 360) % 360
}

export function ColorWheelFilter({ value, onChange, tolerance, onTolerance }) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef(null)
  const wheelRef = useRef(null)
  const hueFrameRef = useRef(0)
  const pendingColorRef = useRef('')
  const preset = COLOR_OPTIONS.find(option => option.id === value)
  // The "all colours" preset intentionally uses a transparent swatch. It is
  // not a valid value for <input type="color"> and previously surfaced as a
  // black picker with the literal label TRANSPARENT. Use a neutral blue only
  // as the unopened/default wheel position; no filter is applied until change.
  const selectedColor = value?.startsWith('#') ? value : value ? preset?.color || '#2f80b8' : '#2f80b8'
  const hue = useMemo(() => colorHue(selectedColor), [selectedColor])
  const pointerRadians = (hue - 90) * Math.PI / 180
  const pointerStyle = {
    '--wheel-x': (50 + Math.cos(pointerRadians) * 39) + '%',
    '--wheel-y': (50 + Math.sin(pointerRadians) * 39) + '%',
    '--chosen-color': selectedColor,
  }

  useEffect(() => {
    return () => {
      if (hueFrameRef.current) window.cancelAnimationFrame(hueFrameRef.current)
      hueFrameRef.current = 0
      pendingColorRef.current = ''
    }
  }, [])

  useEffect(() => {
    if (!open) return undefined
    const close = event => {
      if (!rootRef.current?.contains(event.target)) setOpen(false)
    }
    const closeWithKeyboard = event => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', close)
    document.addEventListener('keydown', closeWithKeyboard)
    return () => {
      document.removeEventListener('pointerdown', close)
      document.removeEventListener('keydown', closeWithKeyboard)
    }
  }, [open])

  const scheduleColorChange = nextColor => {
    pendingColorRef.current = nextColor
    if (hueFrameRef.current) return
    hueFrameRef.current = window.requestAnimationFrame(() => {
      hueFrameRef.current = 0
      const color = pendingColorRef.current
      pendingColorRef.current = ''
      if (color) onChange(color)
    })
  }

  const chooseHue = event => {
    const rect = wheelRef.current.getBoundingClientRect()
    const dx = event.clientX - (rect.left + rect.width / 2)
    const dy = event.clientY - (rect.top + rect.height / 2)
    if (Math.hypot(dx, dy) < rect.width * 0.22) return
    const nextHue = (Math.atan2(dy, dx) * 180 / Math.PI + 450) % 360
    scheduleColorChange(hslToHex(nextHue))
  }

  const beginHueDrag = event => {
    event.currentTarget.setPointerCapture(event.pointerId)
    chooseHue(event)
  }

  const moveHueDrag = event => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) chooseHue(event)
  }

  const moveHueWithKeyboard = event => {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return
    event.preventDefault()
    const direction = ['ArrowRight', 'ArrowUp'].includes(event.key) ? 1 : -1
    onChange(hslToHex((hue + direction * (event.shiftKey ? 12 : 3) + 360) % 360))
  }

  const pickScreenColor = async () => {
    if (!window.EyeDropper) return
    try {
      const result = await new window.EyeDropper().open()
      if (result?.sRGBHex) onChange(result.sRGBHex)
    } catch {
      // Cancelling the system eyedropper is not an error state.
    }
  }

  return <div className="color-wheel-filter" ref={rootRef}>
    <button className={'color-wheel-trigger ' + (value ? 'active' : '')} type="button" onClick={() => setOpen(current => !current)} aria-haspopup="dialog" aria-expanded={open}>
      <span className="mini-color-wheel" style={{ '--chosen-color': selectedColor }}><i /></span>
      <span>{value?.startsWith('#') ? value.toUpperCase() : value ? preset?.label : '色轮'}</span>
    </button>
    {open ? <section className="color-wheel-popover" role="dialog" aria-label="选择素材主色">
      <header><div><strong>选择主色</strong><span>筛选与这个颜色接近的图片</span></div><button type="button" onClick={() => setOpen(false)} aria-label="关闭颜色选择"><X size={16} /></button></header>
      <div className="wheel-stage">
        <div ref={wheelRef} className="hue-wheel" style={pointerStyle} onPointerDown={beginHueDrag} onPointerMove={moveHueDrag} onClick={chooseHue} onKeyDown={moveHueWithKeyboard} role="slider" aria-label="色相" aria-valuemin="0" aria-valuemax="360" aria-valuenow={Math.round(hue)} tabIndex={0}>
          <span className="hue-wheel-center" />
          <i className="hue-wheel-pointer" />
        </div>
        <div className="chosen-color">
          <i style={{ background: selectedColor }} />
          <label><span>精确颜色</span><input type="color" value={selectedColor} onInput={event => onChange(event.target.value)} onChange={event => onChange(event.target.value)} /></label>
          <code>{selectedColor.toUpperCase()}</code>
        </div>
      </div>
      <div className="color-preset-row" aria-label="常用颜色">
        {COLOR_OPTIONS.filter(option => option.id).map(option => <button key={option.id} type="button" className={value === option.id ? 'active' : ''} onClick={() => onChange(option.id)} title={option.label} aria-label={option.label} style={{ '--preset-color': option.color }}>{value === option.id ? <Check size={11} /> : null}</button>)}
      </div>
      <label className="color-tolerance"><span><SlidersHorizontal size={13} />颜色范围</span><input type="range" min="12" max="48" step="2" value={tolerance} onChange={event => onTolerance(Number(event.target.value))} /><em>{tolerance < 22 ? '接近' : tolerance < 36 ? '适中' : '宽松'}</em></label>
      <footer>
        {window.EyeDropper ? <button type="button" onClick={pickScreenColor}><Pipette size={14} />屏幕取色</button> : <span />}
        <button type="button" onClick={() => { onChange(''); setOpen(false) }}>清除颜色</button>
      </footer>
    </section> : null}
  </div>
}
