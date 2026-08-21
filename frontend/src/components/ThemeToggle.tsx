import { useTheme, type ThemePreference } from '../context/ThemeContext'
import Icon from './Icon'
import './ThemeToggle.css'

const OPTIONS: { value: ThemePreference; label: string; icon: 'monitor' | 'sun' | 'moon' }[] = [
  { value: 'system', label: 'System', icon: 'monitor' },
  { value: 'light', label: 'Light', icon: 'sun' },
  { value: 'dark', label: 'Dark', icon: 'moon' },
]

export default function ThemeToggle() {
  const { preference, setPreference } = useTheme()

  return (
    <div className="theme-toggle" role="radiogroup" aria-label="Appearance">
      {OPTIONS.map((opt) => (
        <button
          key={opt.value}
          type="button"
          role="radio"
          aria-checked={preference === opt.value}
          title={opt.label}
          className={`theme-toggle-option ${preference === opt.value ? 'is-active' : ''}`}
          onClick={() => setPreference(opt.value)}
        >
          <Icon name={opt.icon} size={15} />
        </button>
      ))}
    </div>
  )
}
