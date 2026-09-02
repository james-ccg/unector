import { useCallback, useEffect, useRef, useState } from 'react'
import Icon from './Icon'
import './AvatarCropper.css'

const VIEW = 288        // the square the crop circle is inscribed in, on screen
const OUTPUT_SIZE = 160 // what actually gets stored - see AvatarPicker
const MAX_ZOOM = 4

interface Props {
  file: File
  onCancel: () => void
  onDone: (dataUrl: string) => void
}

type Offset = { x: number; y: number }

/** Choose which part of a picture becomes the avatar.
 *
 * The picture used to be centre-cropped on upload, which is right roughly
 * never: faces are rarely dead centre, and a group photo cropped blind is
 * a picture of somebody else's shoulder. This puts the decision where it
 * belongs.
 *
 * Deliberately no cropping library. Pointer Events already unify mouse and
 * touch, the maths is a scale and two offsets, and the project just spent a
 * pass tightening its supply chain - a dependency for this would be more
 * code to trust than to write.
 */
export default function AvatarCropper({ file, onCancel, onDone }: Props) {
  const [image, setImage] = useState<HTMLImageElement | null>(null)
  const [zoom, setZoom] = useState(1)
  const [offset, setOffset] = useState<Offset>({ x: 0, y: 0 })
  const [error, setError] = useState('')

  const frameRef = useRef<HTMLDivElement>(null)
  const drag = useRef<{ id: number; x: number; y: number; from: Offset } | null>(null)
  // Live pointers, for pinch. A phone is the likeliest place this is used.
  const pointers = useRef(new Map<number, { x: number; y: number }>())
  const pinch = useRef<{ distance: number; zoom: number } | null>(null)

  useEffect(() => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => setImage(img)
    img.onerror = () => setError("Couldn't read that image. Try a JPEG or PNG.")
    img.src = url
    return () => URL.revokeObjectURL(url)
  }, [file])

  // At zoom 1 the shorter side exactly covers the frame, so there is never a
  // gap to crop into - the same "cover" fit the finished avatar uses.
  const baseScale = image ? VIEW / Math.min(image.width, image.height) : 1
  const scale = baseScale * zoom
  const drawnWidth = image ? image.width * scale : 0
  const drawnHeight = image ? image.height * scale : 0

  /** Keeps the picture covering the frame however it is dragged. */
  const clamp = useCallback(
    (next: Offset, atZoom = zoom): Offset => {
      if (!image) return next
      const s = baseScale * atZoom
      const limitX = Math.max(0, (image.width * s - VIEW) / 2)
      const limitY = Math.max(0, (image.height * s - VIEW) / 2)
      return {
        x: Math.min(limitX, Math.max(-limitX, next.x)),
        y: Math.min(limitY, Math.max(-limitY, next.y)),
      }
    },
    [image, baseScale, zoom]
  )

  const applyZoom = useCallback(
    (next: number) => {
      const clamped = Math.min(MAX_ZOOM, Math.max(1, next))
      setZoom(clamped)
      setOffset((current) => clamp(current, clamped))
    },
    [clamp]
  )

  const onPointerDown = (e: React.PointerEvent) => {
    ;(e.target as Element).setPointerCapture?.(e.pointerId)
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY })
    if (pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()]
      pinch.current = { distance: Math.hypot(a.x - b.x, a.y - b.y), zoom }
      drag.current = null
    } else {
      drag.current = { id: e.pointerId, x: e.clientX, y: e.clientY, from: offset }
    }
  }

  const onPointerMove = (e: React.PointerEvent) => {
    if (!pointers.current.has(e.pointerId)) return
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY })

    if (pinch.current && pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()]
      const distance = Math.hypot(a.x - b.x, a.y - b.y)
      applyZoom(pinch.current.zoom * (distance / pinch.current.distance))
      return
    }
    if (drag.current?.id === e.pointerId) {
      setOffset(
        clamp({
          x: drag.current.from.x + (e.clientX - drag.current.x),
          y: drag.current.from.y + (e.clientY - drag.current.y),
        })
      )
    }
  }

  const onPointerUp = (e: React.PointerEvent) => {
    pointers.current.delete(e.pointerId)
    if (pointers.current.size < 2) pinch.current = null
    if (drag.current?.id === e.pointerId) drag.current = null
  }

  // Wheel zoom, non-passive so the page does not scroll underneath it.
  useEffect(() => {
    const frame = frameRef.current
    if (!frame) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      applyZoom(zoom * (e.deltaY < 0 ? 1.12 : 1 / 1.12))
    }
    frame.addEventListener('wheel', onWheel, { passive: false })
    return () => frame.removeEventListener('wheel', onWheel)
  }, [zoom, applyZoom])

  const handleSave = () => {
    if (!image) return
    const canvas = document.createElement('canvas')
    canvas.width = OUTPUT_SIZE
    canvas.height = OUTPUT_SIZE
    const ctx = canvas.getContext('2d')
    if (!ctx) {
      setError("Couldn't process that image.")
      return
    }

    // What the frame shows, mapped back to source pixels: the frame's
    // top-left in image space, then a VIEW-sized square from there.
    const ratio = OUTPUT_SIZE / VIEW
    ctx.imageSmoothingQuality = 'high'
    ctx.translate(OUTPUT_SIZE / 2, OUTPUT_SIZE / 2)
    ctx.drawImage(
      image,
      -drawnWidth / 2 * ratio + offset.x * ratio,
      -drawnHeight / 2 * ratio + offset.y * ratio,
      drawnWidth * ratio,
      drawnHeight * ratio
    )
    onDone(canvas.toDataURL('image/jpeg', 0.85))
  }

  return (
    <div className="cropper">
      <p className="cropper-hint">
        Drag to reposition, and use the slider to zoom. The circle is what people will see.
      </p>

      <div
        ref={frameRef}
        className="cropper-frame"
        style={{ width: VIEW, height: VIEW }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        {image && (
          <img
            className="cropper-image"
            src={image.src}
            alt=""
            draggable={false}
            style={{
              width: drawnWidth,
              height: drawnHeight,
              transform: `translate(-50%, -50%) translate(${offset.x}px, ${offset.y}px)`,
            }}
          />
        )}
        <div className="cropper-mask" aria-hidden="true" />
      </div>

      <label className="cropper-zoom">
        <Icon name="eye-off" size={15} />
        <input
          type="range"
          min={1}
          max={MAX_ZOOM}
          step={0.01}
          value={zoom}
          onChange={(e) => applyZoom(Number(e.target.value))}
          aria-label="Zoom"
        />
        <Icon name="eye" size={17} />
      </label>

      {error && <p className="cropper-error">{error}</p>}

      <div className="cropper-actions">
        <button type="button" className="btn-ghost" onClick={onCancel}>
          Cancel
        </button>
        <button type="button" className="btn-primary" onClick={handleSave} disabled={!image}>
          Set as picture
        </button>
      </div>
    </div>
  )
}
