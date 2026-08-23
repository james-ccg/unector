import { useState, type InputHTMLAttributes } from 'react'
import Icon from './Icon'
import './PasswordInput.css'

type PasswordInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'type'>

/** A password <input> with a show/hide toggle - forwards every other prop
 * (value, onChange, name, placeholder, required, minLength, ...) straight
 * through, so it drops in wherever a plain type="password" input was. */
export default function PasswordInput(props: PasswordInputProps) {
  const [visible, setVisible] = useState(false)

  return (
    <div className="password-input-wrap">
      <input {...props} type={visible ? 'text' : 'password'} />
      <button
        type="button"
        className="password-input-toggle"
        onClick={() => setVisible((v) => !v)}
        aria-label={visible ? 'Hide password' : 'Show password'}
        tabIndex={-1}
      >
        <Icon name={visible ? 'eye-off' : 'eye'} size={18} />
      </button>
    </div>
  )
}
