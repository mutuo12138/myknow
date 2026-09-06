import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { ArrowLeft, ChevronLeft, ChevronRight, Hand, Minus, Plus, RotateCcw, X } from 'lucide-react'
import { createPortal } from 'react-dom'
import gsap from 'gsap'

const clampZoom = value => Math.min(5, Math.max(0.6, Math.round(value * 100) / 100))
const previewFor = item => item?.asset_url || item?.thumbnail_asset_url || item?.thumbnail_url || ''

export function ImageLightbox({ item, items = [], onClose, onNavigate }) {
  const rootRef = useRef(null)
  const panelRef = useRef(null)
  const canvasRef = useRef(null)
  const imageRef = useRef(null)
  const closeRef = useRef(null)
  const closingRef = useRef(false)
  const renderFrameRef = useRef(0)
  const viewRef = useRef({ zoom: 1, x: 0, y: 0 })
  const viewportRef = useRef({ imageWidth: 0, imageHeight: 0, canvasWidth: 0, canvasHeight: 0 })
  const dragRef = useRef(null)
  const [zoom, setZoom] = useState(1)
  const [dragging, setDragging] = useState(false)
  const previewUrl = previewFor(item)
  const navigableItems = useMemo(() => {
    const source = Array.isArray(items) && items.length ? items : [item]
    const seen = new Set()
    return source.filter(candidate => {
      if (!candidate || !previewFor(candidate) || seen.has(candidate.id)) return false
      seen.add(candidate.id)
      return true
    })
  }, [items, item])
  const currentIndex = Math.max(0, navigableItems.findIndex(candidate => candidate.id === item?.id))
  const hasPrevious = currentIndex > 0
  const hasNext = currentIndex < navigableItems.length - 1

  const clampPan = useCallback((x, y, scale) => {
    const viewport = viewportRef.current
    if (!viewport.imageWidth || !viewport.canvasWidth) return { x: 0, y: 0 }
    const maxX = Math.max(0, (viewport.imageWidth * scale - viewport.canvasWidth) / 2 + 24)
    const maxY = Math.max(0, (viewport.imageHeight * scale - viewport.canvasHeight) / 2 + 24)
    return { x: Math.min(maxX, Math.max(-maxX, x)), y: Math.min(maxY, Math.max(-maxY, y)) }
  }, [])

  const measureViewport = useCallback(() => {
    const canvas = canvasRef.current
    const image = imageRef.current
    if (!canvas || !image) return
    viewportRef.current = {
      imageWidth: image.offsetWidth,
      imageHeight: image.offsetHeight,
      canvasWidth: canvas.clientWidth,
      canvasHeight: canvas.clientHeight,
    }
  }, [])

  const applyTransform = useCallback(() => {
    const image = imageRef.current
    if (!image) return
    const { zoom: scale, x, y } = viewRef.current
    image.style.transformOrigin = '50% 50%'
    image.style.transform = `translate3d(${x}px, ${y}px, 0) scale(${scale})`
  }, [])

  const renderView = useCallback((animate = false) => {
    const image = imageRef.current
    if (!image) return
    const { zoom: scale, x, y } = viewRef.current
    if (animate && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      if (renderFrameRef.current) window.cancelAnimationFrame(renderFrameRef.current)
      renderFrameRef.current = 0
      gsap.killTweensOf(image)
      gsap.to(image, { x, y, scale, transformOrigin: '50% 50%', force3D: true, duration: 0.22, ease: 'power3.out', overwrite: true })
      return
    }
    if (renderFrameRef.current) return
    renderFrameRef.current = window.requestAnimationFrame(() => {
      renderFrameRef.current = 0
      applyTransform()
    })
  }, [applyTransform])

  const changeZoom = useCallback((value, point) => {
    const canvas = canvasRef.current
    const previous = viewRef.current
    const nextZoom = clampZoom(value)
    if (!canvas || nextZoom === previous.zoom) return
    const rect = canvas.getBoundingClientRect()
    const anchorX = point ? point.clientX - rect.left - rect.width / 2 : 0
    const anchorY = point ? point.clientY - rect.top - rect.height / 2 : 0
    const ratio = nextZoom / previous.zoom
    const proposedX = anchorX - (anchorX - previous.x) * ratio
    const proposedY = anchorY - (anchorY - previous.y) * ratio
    const constrained = clampPan(proposedX, proposedY, nextZoom)
    viewRef.current = { zoom: nextZoom, ...constrained }
    setZoom(nextZoom)
    renderView(true)
  }, [clampPan, renderView])

  const resetView = useCallback(() => {
    viewRef.current = { zoom: 1, x: 0, y: 0 }
    setZoom(1)
    setDragging(false)
    dragRef.current = null
    renderView(true)
  }, [renderView])

  const navigate = useCallback((direction) => {
    const next = navigableItems[currentIndex + direction]
    if (!next) return
    resetView()
    onNavigate?.(next)
  }, [currentIndex, navigableItems, onNavigate, resetView])

  const close = useCallback(() => {
    if (closingRef.current) return
    closingRef.current = true
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches || !rootRef.current) {
      onClose()
      return
    }
    gsap.to(rootRef.current, { autoAlpha: 0, duration: 0.16, ease: 'power2.in', onComplete: onClose })
  }, [onClose])

  useEffect(() => {
    const previousFocus = document.activeElement
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    closeRef.current?.focus()
    const handleKey = event => {
      if (event.key === 'Escape') close()
      if (event.key === 'ArrowLeft') { event.preventDefault(); navigate(-1) }
      if (event.key === 'ArrowRight') { event.preventDefault(); navigate(1) }
      if (event.key === '+' || event.key === '=') { event.preventDefault(); changeZoom(viewRef.current.zoom + 0.2) }
      if (event.key === '-') { event.preventDefault(); changeZoom(viewRef.current.zoom - 0.2) }
      if (event.key === '0') resetView()
    }
    window.addEventListener('keydown', handleKey)
    return () => {
      window.removeEventListener('keydown', handleKey)
      document.body.style.overflow = previousOverflow
      previousFocus?.focus?.()
    }
  }, [changeZoom, close, navigate, resetView])

  useLayoutEffect(() => {
    closingRef.current = false
    viewRef.current = { zoom: 1, x: 0, y: 0 }
    viewportRef.current = { imageWidth: 0, imageHeight: 0, canvasWidth: 0, canvasHeight: 0 }
    setZoom(1)
    setDragging(false)
    dragRef.current = null
    renderView(false)
  }, [item?.id, renderView])

  useLayoutEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return undefined
    const context = gsap.context(() => {
      gsap.fromTo(rootRef.current, { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.18, ease: 'power2.out' })
      gsap.fromTo(panelRef.current, { autoAlpha: 0, y: 6 }, { autoAlpha: 1, y: 0, duration: 0.2, ease: 'power3.out', clearProps: 'transform,opacity,visibility' })
    }, rootRef)
    return () => context.revert()
  }, [])

  useEffect(() => {
    const handleResize = () => {
      measureViewport()
      const current = viewRef.current
      const constrained = clampPan(current.x, current.y, current.zoom)
      viewRef.current = { ...current, ...constrained }
      renderView(false)
    }
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [clampPan, measureViewport, renderView])

  useEffect(() => () => {
    if (renderFrameRef.current) window.cancelAnimationFrame(renderFrameRef.current)
    renderFrameRef.current = 0
    gsap.killTweensOf(imageRef.current)
  }, [])

  if (!item || !previewUrl) return null

  const beginPan = event => {
    if (event.target !== imageRef.current || viewRef.current.zoom <= 1) return
    event.preventDefault()
    event.currentTarget.setPointerCapture(event.pointerId)
    dragRef.current = { pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, originX: viewRef.current.x, originY: viewRef.current.y }
    setDragging(true)
    gsap.killTweensOf(imageRef.current)
  }

  const movePan = event => {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    event.preventDefault()
    const proposed = clampPan(drag.originX + event.clientX - drag.startX, drag.originY + event.clientY - drag.startY, viewRef.current.zoom)
    viewRef.current = { ...viewRef.current, ...proposed }
    renderView(false)
  }

  const endPan = event => {
    if (!dragRef.current || dragRef.current.pointerId !== event.pointerId) return
    dragRef.current = null
    setDragging(false)
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
  }

  return createPortal(<div className="image-lightbox" ref={rootRef} role="dialog" aria-modal="true" aria-label={`查看大图：${item.title}`}>
    <div className="lightbox-panel" ref={panelRef}>
      <header className="lightbox-header">
        <div className="lightbox-leading">
          <button className="lightbox-back" type="button" onClick={close}><ArrowLeft size={18} /><span>返回素材库</span></button>
          <span className="lightbox-counter" aria-live="polite">{navigableItems.length ? `${currentIndex + 1} / ${navigableItems.length}` : '1 / 1'}</span>
        </div>
        <div className="lightbox-title"><strong>{item.title}</strong><span>{zoom > 1 ? '按住图片拖动查看细节' : '双击图片快速放大'} · ← → 切换</span></div>
        <button className="lightbox-close" ref={closeRef} type="button" onClick={close} title="关闭大图" aria-label="关闭大图"><X size={19} /></button>
      </header>
      <div className={`lightbox-canvas ${zoom > 1 ? 'can-pan' : ''} ${dragging ? 'is-panning' : ''}`} ref={canvasRef} onPointerDown={beginPan} onPointerMove={movePan} onPointerUp={endPan} onPointerCancel={endPan} onWheel={event => { event.preventDefault(); changeZoom(viewRef.current.zoom + (event.deltaY < 0 ? 0.12 : -0.12), event) }} onDoubleClick={event => changeZoom(viewRef.current.zoom > 1 ? 1 : 2, event)}>
        <button className="lightbox-dismiss" type="button" tabIndex={-1} onClick={close} aria-label="点击空白处返回素材库" />
        <img ref={imageRef} src={previewUrl} alt={item.title} draggable="false" onLoad={() => { measureViewport(); renderView(false) }} />
        <div className="lightbox-nav" role="group" aria-label="切换素材">
          <button className="lightbox-nav-button lightbox-prev" type="button" onClick={() => navigate(-1)} disabled={!hasPrevious} title="上一张（←）" aria-label="上一张"><ChevronLeft size={25} /></button>
          <button className="lightbox-nav-button lightbox-next" type="button" onClick={() => navigate(1)} disabled={!hasNext} title="下一张（→）" aria-label="下一张"><ChevronRight size={25} /></button>
        </div>
      </div>
      <div className="lightbox-controls" role="group" aria-label="图片缩放">
        <button type="button" onClick={() => changeZoom(viewRef.current.zoom - 0.2)} disabled={zoom <= 0.6} title="缩小" aria-label="缩小"><Minus size={17} /></button>
        <output aria-live="polite">{Math.round(zoom * 100)}%</output>
        <button type="button" onClick={() => changeZoom(viewRef.current.zoom + 0.2)} disabled={zoom >= 5} title="放大" aria-label="放大"><Plus size={17} /></button>
        <button type="button" onClick={resetView} title="适合窗口" aria-label="适合窗口"><RotateCcw size={16} /></button>
      </div>
      <footer className="lightbox-footer"><span>点击图片外空白处返回图库</span><span><Hand size={13} />放大后拖动图片</span><span>← → 切换</span><span>ESC 关闭</span></footer>
    </div>
  </div>, document.body)
}
