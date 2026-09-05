import { useRef, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { authApi, errorMessage } from '../services/api'
import AvatarCropper from './AvatarCropper'
import Icon from './Icon'
import './AvatarPicker.css'

/* Two different things share this control, and the wording has to say which
 * one you are looking at. An owner's picture is stored against the COMPANY
 * id, so there is one per carrier however many people sign in as the owner:
 * it is the company's logo, and it is what the bot puts on a truck's
 * Telegram group. A dispatcher's is stored against their own id and is a
 * personal picture, theirs alone.
 *
 * The picture used to be centre-cropped the moment it was chosen, which is
 * right roughly never - faces are rarely dead centre, and neither are
 * logos. Picking a file now opens AvatarCropper, and the crop is the
 * person's own decision. It still comes back as a small JPEG data URL,
 * stored as plain text rather than needing a file-storage service; see
 * _MAX_AVATAR_DATA_URL_LENGTH in miniapp/api.py. */

export default function AvatarPicker() {
  const { user, refreshUser } = useAuth()
  const isCompanyLogo = user?.role === 'owner'
  const noun = isCompanyLogo ? 'logo' : 'picture'
  const inputRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [pending, setPending] = useState<File | null>(null)

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    if (!file.type.startsWith('image/')) {
      setError('That file is not an image. Choose a JPEG, PNG or WebP.')
      return
    }
    setError('')
    setPending(file)
  }

  const handleCropped = async (dataUrl: string) => {
    setPending(null)
    setBusy(true)
    setError('')
    try {
      await authApi.setAvatar(dataUrl)
      await refreshUser()
    } catch (err) {
      setError(errorMessage(err, `Couldn't update the ${noun}.`))
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
      setError(errorMessage(err, `Couldn't remove the ${noun}.`))
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
          aria-label={isCompanyLogo ? 'Change company logo' : 'Change profile picture'}
        >
          {user?.avatar ? <img src={user.avatar} alt="" /> : <Icon name="briefcase" size={20} />}
        </button>
        <div className="avatar-picker-actions">
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => inputRef.current?.click()} disabled={busy}>
            {busy ? 'Uploading...' : user?.avatar ? `Change ${noun}` : `Upload ${noun}`}
          </button>
          {user?.avatar && (
            <button type="button" className="btn btn-danger-ghost btn-sm" onClick={handleRemove} disabled={busy}>
              Remove
            </button>
          )}
        </div>
        <input ref={inputRef} type="file" accept="image/*" onChange={handleFileChange} hidden />
      </div>
      {pending && (
        <AvatarCropper file={pending} onCancel={() => setPending(null)} onDone={handleCropped} />
      )}
      {error && <p className="form-error">{error}</p>}
    </div>
  )
}
