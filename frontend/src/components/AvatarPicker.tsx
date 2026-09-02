import { useRef, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { authApi, errorMessage } from '../services/api'
import Icon from './Icon'
import './AvatarPicker.css'

const OUTPUT_SIZE = 160

/** Center-crops `file` to a square and resizes it to OUTPUT_SIZE, returning
 * a JPEG data URL small enough to store as plain text (see
 * _MAX_AVATAR_DATA_URL_LENGTH in miniapp/api.py) without needing a separate
 * file-storage service for what's just a small profile picture. */
function resizeToSquareDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => {
      const side = Math.min(img.width, img.height)
      const sx = (img.width - side) / 2
      const sy = (img.height - side) / 2
      const canvas = document.createElement('canvas')
      canvas.width = OUTPUT_SIZE
      canvas.height = OUTPUT_SIZE
      const ctx = canvas.getContext('2d')
      if (!ctx) {
        reject(new Error("Couldn't process image"))
        return
      }
      ctx.drawImage(img, sx, sy, side, side, 0, 0, OUTPUT_SIZE, OUTPUT_SIZE)
      resolve(canvas.toDataURL('image/jpeg', 0.85))
      URL.revokeObjectURL(img.src)
    }
    img.onerror = () => reject(new Error("Couldn't read that image"))
    img.src = URL.createObjectURL(file)
  })
}

export default function AvatarPicker() {
  const { user, refreshUser } = useAuth()
  const inputRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    if (!file.type.startsWith('image/')) {
      setError('Please choose an image file.')
      return
    }
    setBusy(true)
    setError('')
    try {
      const dataUrl = await resizeToSquareDataUrl(file)
      await authApi.setAvatar(dataUrl)
      await refreshUser()
    } catch (err) {
      setError(errorMessage(err, "Couldn't update your picture."))
    } finally {
      setBusy(false)
    }
  }

  const handleRemove = async () => {
    setBusy(true)
    setError('')
    try {
      await authApi.clearAvatar()
      await refreshUser()
    } catch (err) {
      setError(errorMessage(err, "Couldn't remove your picture."))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="avatar-picker">
      <div className="avatar-picker-row">
        <button
          type="button"
          className="avatar-picker-preview"
          onClick={() => inputRef.current?.click()}
          disabled={busy}
          aria-label="Change profile picture"
        >
          {user?.avatar ? <img src={user.avatar} alt="" /> : <Icon name="briefcase" size={20} />}
        </button>
        <div className="avatar-picker-actions">
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => inputRef.current?.click()} disabled={busy}>
            {busy ? 'Uploading...' : user?.avatar ? 'Change picture' : 'Upload picture'}
          </button>
          {user?.avatar && (
            <button type="button" className="btn btn-danger-ghost btn-sm" onClick={handleRemove} disabled={busy}>
              Remove
            </button>
          )}
        </div>
        <input ref={inputRef} type="file" accept="image/*" onChange={handleFileChange} hidden />
      </div>
      {error && <p className="form-error">{error}</p>}
    </div>
  )
}
