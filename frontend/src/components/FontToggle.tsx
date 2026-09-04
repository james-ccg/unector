import { usePreferences, type FontChoice } from '../context/PreferencesContext'
import './FontToggle.css'

// Every option resolves to a face already available to the page - the brand
// webfont, or a system stack - so switching costs no extra download.
const OPTIONS: { value: FontChoice; label: string; sample: string }[] = [
  { value: 'default', label: 'Unector', sample: 'Aa' },
  { value: 'system', label: 'System', sample: 'Aa' },
  { value: 'serif', label: 'Serif', sample: 'Aa' },
]

export default function FontToggle() {
  const { font, setFont } = usePreferences()

  return (
    <div className="font-toggle" role="radiogroup" aria-label="Interface font">
      {OPTIONS.map((opt) => (
        <button
          key={opt.value}
          type="button"
          role="radio"
          aria-checked={font === opt.value}
          title={opt.label}
          className={`font-toggle-option font-toggle-${opt.value} ${font === opt.value ? 'is-active' : ''}`}
          onClick={() => setFont(opt.value)}
        >
          <span className="font-toggle-sample">{opt.sample}</span>
          <span className="font-toggle-label">{opt.label}</span>
        </button>
      ))}
    </div>
  )
}
