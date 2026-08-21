import { usePreferences, type FontSize } from '../context/PreferencesContext'
import './FontSizeToggle.css'

const OPTIONS: { value: FontSize; label: string }[] = [
  { value: 'small', label: 'Small' },
  { value: 'medium', label: 'Medium' },
  { value: 'large', label: 'Large' },
]

export default function FontSizeToggle() {
  const { fontSize, setFontSize } = usePreferences()

  return (
    <div className="font-size-toggle" role="radiogroup" aria-label="Chat font size">
      {OPTIONS.map((opt) => (
        <button
          key={opt.value}
          type="button"
          role="radio"
          aria-checked={fontSize === opt.value}
          title={opt.label}
          className={`font-size-toggle-option font-size-toggle-${opt.value} ${fontSize === opt.value ? 'is-active' : ''}`}
          onClick={() => setFontSize(opt.value)}
        >
          Aa
        </button>
      ))}
    </div>
  )
}
