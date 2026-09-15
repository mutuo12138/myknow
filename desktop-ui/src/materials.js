export const TYPE_OPTIONS = [
  { id: '', label: '全部' },
  { id: 'image', label: '图片' },
  { id: 'video', label: '视频' },
  { id: 'document', label: '文档' },
  { id: 'page', label: '网页' },
]

export const BRIGHTNESS_OPTIONS = [
  { id: 'all', label: '全部亮度' },
  { id: 'dark', label: '偏暗', min: 0, max: 0.35 },
  { id: 'balanced', label: '中等', min: 0.35, max: 0.7 },
  { id: 'bright', label: '偏亮', min: 0.7, max: 1 },
]

export const COLOR_OPTIONS = [
  { id: '', label: '全部颜色', color: 'transparent' },
  { id: 'blue', label: '蓝色', color: '#4f88e8' },
  { id: 'green', label: '绿色', color: '#49a97f' },
  { id: 'warm', label: '暖色', color: '#db8a4d' },
  { id: 'pink', label: '粉紫', color: '#c66aa3' },
  { id: 'neutral', label: '中性色', color: '#909a97' },
]

const now = Math.floor(Date.now() / 1000)

export const DEMO_MATERIALS = [
  {
    id: 'demo-image',
    is_demo: true,
    title: '蓝色人像配色参考',
    material_type: 'image',
    source_name: '示例素材',
    source_url: '',
    captured_at: now - 180,
    status: 'ready',
    folder_id: 'inbox',
    folder_name: '收件箱',
    export_state: 'not_requested',
    category: '图片',
    subcategory: '设计',
    ai_summary: '冷蓝色作为主体，背景较暗，适合夜景人像与科技感视觉参考。',
    tags: ['蓝色', '人像', '夜景'],
    palette: [{ rgb: [48, 104, 215], ratio: 0.68 }, { rgb: [26, 36, 52], ratio: 0.32 }],
    mean_brightness: 0.38,
    detail_score: 0.74,
  },
  {
    id: 'demo-document',
    is_demo: true,
    title: '视觉叙事中的冷暖对比',
    material_type: 'document',
    source_name: '示例文章',
    source_url: '',
    captured_at: now - 3600,
    status: 'ready',
    folder_id: 'inbox',
    folder_name: '收件箱',
    export_state: 'ready',
    category: '文档',
    subcategory: '设计',
    ai_summary: '文章整理了冷暖色在镜头情绪、主体分离和时间感表达中的常见用法。',
    tags: ['色彩', '视觉叙事'],
    palette: [{ rgb: [210, 132, 70], ratio: 1 }],
    mean_brightness: 0.62,
    detail_score: 0.31,
  },
  {
    id: 'demo-video',
    is_demo: true,
    title: '城市夜景镜头节奏案例',
    material_type: 'video',
    source_name: '示例视频',
    source_url: '',
    captured_at: now - 86400,
    status: 'ready',
    folder_id: 'inbox',
    folder_name: '收件箱',
    export_state: 'not_requested',
    category: '视频',
    subcategory: '设计',
    ai_summary: '前半段用快速运动建立城市速度，后半段用固定长镜头收住情绪。',
    tags: ['镜头节奏', '城市', '夜景'],
    palette: [{ rgb: [186, 74, 142], ratio: 1 }],
    mean_brightness: 0.29,
    detail_score: 0.82,
  },
]

export function colorFrom(item) {
  const rgb = item.palette?.[0]?.rgb
  return rgb ? `rgb(${rgb.join(',')})` : '#39504a'
}

export function colorFamily(item) {
  const rgb = item.palette?.[0]?.rgb
  if (!rgb) return 'neutral'
  const [red, green, blue] = rgb.map(value => value / 255)
  const max = Math.max(red, green, blue)
  const min = Math.min(red, green, blue)
  const delta = max - min
  if (delta < 0.12) return 'neutral'
  let hue = 0
  if (max === red) hue = ((green - blue) / delta) % 6
  else if (max === green) hue = (blue - red) / delta + 2
  else hue = (red - green) / delta + 4
  hue = (hue * 60 + 360) % 360
  if (hue >= 190 && hue < 255) return 'blue'
  if (hue >= 70 && hue < 190) return 'green'
  if (hue >= 255 && hue < 345) return 'pink'
  return 'warm'
}

function hexToRgb(color) {
  if (!/^#[0-9a-f]{6}$/i.test(color || '')) return null
  return [1, 3, 5].map(index => parseInt(color.slice(index, index + 2), 16))
}

function rgbToLab([red, green, blue]) {
  const linear = [red, green, blue].map(channel => {
    const normalized = channel / 255
    return normalized > 0.04045 ? ((normalized + 0.055) / 1.055) ** 2.4 : normalized / 12.92
  })
  const x = (linear[0] * 0.4124 + linear[1] * 0.3576 + linear[2] * 0.1805) / 0.95047
  const y = linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722
  const z = (linear[0] * 0.0193 + linear[1] * 0.1192 + linear[2] * 0.9505) / 1.08883
  const pivot = value => value > 0.008856 ? value ** (1 / 3) : 7.787 * value + 16 / 116
  const fx = pivot(x)
  const fy = pivot(y)
  const fz = pivot(z)
  return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)]
}

function perceptualDistance(first, second) {
  const labA = rgbToLab(first)
  const labB = rgbToLab(second)
  return Math.hypot(labA[0] - labB[0], labA[1] - labB[1], labA[2] - labB[2])
}

export function matchesColor(item, color, tolerance = 28) {
  if (!color) return true
  if (!color.startsWith('#')) return colorFamily(item) === color
  const target = hexToRgb(color)
  const palette = (item.palette || []).map(entry => entry.rgb).filter(Boolean)
  if (!target || !palette.length) return false
  return palette.some(rgb => perceptualDistance(rgb, target) <= tolerance)
}

export function pasteHint() {
  return typeof navigator !== 'undefined' && /Mac/i.test(navigator.userAgent || '') ? '⌘V' : 'Ctrl+V'
}
