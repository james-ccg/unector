import { useState } from 'react'
import {
  dashboardApi,
  errorMessage,
  ApiError,
  type GroupProfileProposal,
  type GroupProfileField,
} from '../services/api'
import ErrorMessage from './ErrorMessage'
import { FIELD_LABELS, FIELD_ORDER } from '../lib/groupProfileFields'
import './GroupProfileReview.css'

/**
 * What the bot read out of a truck's Telegram group description, shown for
 * someone to check before it is saved.
 *
 * Carriers keep the unit number, trailer, driver and phone numbers in the
 * group's bio, typed by hand. The reading is good but it is still a reading,
 * so every value here is editable: a misread digit gets corrected in place
 * rather than costing the whole thing. The text it came from sits underneath
 * so the values can be checked against it instead of taken on trust.
 *
 * The same reading is also sitting in the Telegram group with Confirm on it.
 * Whichever side goes first wins, and the other gets a 409 - which is not an
 * error worth alarming anyone about, so it is reported as what it is.
 */

type Values = Partial<Record<GroupProfileField, string>>

export function FieldGrid({
  values,
  unclear,
  onChange,
  disabled,
}: {
  values: Values
  unclear?: GroupProfileField[]
  onChange: (field: GroupProfileField, value: string) => void
  disabled?: boolean
}) {
  return (
    <div className="gp-grid">
      {FIELD_ORDER.map((field) => {
        const isUnclear = unclear?.includes(field)
        return (
          <label key={field} className="gp-field">
            <span className="gp-label">
              {FIELD_LABELS[field]}
              {isUnclear && (
                <span className="gp-flag" title="Read from the bio, but not clearly - worth a look">
                  check
                </span>
              )}
            </span>
            <input
              type="text"
              className={isUnclear ? 'gp-input is-unclear' : 'gp-input'}
              value={values[field] ?? ''}
              onChange={(e) => onChange(field, e.target.value)}
              disabled={disabled}
              maxLength={150}
            />
          </label>
        )
      })}
    </div>
  )
}

function ProposalCard({
  proposal,
  onResolved,
}: {
  proposal: GroupProfileProposal
  onResolved: (id: number, message: string) => void
}) {
  const [values, setValues] = useState<Values>(proposal.fields)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showSource, setShowSource] = useState(false)

  const edited = FIELD_ORDER.some((f) => (values[f] ?? '') !== (proposal.fields[f] ?? ''))

  const handleConfirm = async () => {
    setBusy(true)
    setError(null)
    try {
      await dashboardApi.confirmGroupProfile(proposal.id, edited ? values : undefined)
      onResolved(proposal.id, `Saved to ${proposal.driver_name || 'the driver'}.`)
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        onResolved(proposal.id, 'Already confirmed from Telegram - nothing left to do here.')
        return
      }
      setError(errorMessage(err, "Couldn't save these details."))
    } finally {
      setBusy(false)
    }
  }

  const handleDismiss = async () => {
    setBusy(true)
    setError(null)
    try {
      await dashboardApi.dismissGroupProfile(proposal.id)
      onResolved(proposal.id, 'Dismissed. Send /readbio in the group to read it again.')
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        onResolved(proposal.id, 'Already handled from Telegram.')
        return
      }
      setError(errorMessage(err, "Couldn't dismiss this."))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="gp-card">
      <div className="gp-head">
        <h4 className="gp-title">
          From {proposal.source_title ? <span className="mono">{proposal.source_title}</span> : 'a linked group'}
        </h4>
        <p className="gp-sub">
          Read from the group description. Check it, change anything that is wrong, then save it.
        </p>
      </div>

      {proposal.conflicts.length > 0 && (
        <ul className="gp-conflicts">
          {proposal.conflicts.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}

      <FieldGrid
        values={values}
        unclear={proposal.unclear}
        disabled={busy}
        onChange={(field, value) => setValues((prev) => ({ ...prev, [field]: value }))}
      />

      {proposal.source_description && (
        <div className="gp-source">
          <button type="button" className="gp-source-toggle" onClick={() => setShowSource((v) => !v)}>
            {showSource ? 'Hide the description' : 'Show the description it was read from'}
          </button>
          {showSource && <pre className="gp-source-text">{proposal.source_description}</pre>}
        </div>
      )}

      {error && <ErrorMessage className="form-error" text={error} />}

      <div className="gp-actions">
        <button className="btn btn-primary btn-sm" onClick={handleConfirm} disabled={busy}>
          {busy ? 'Saving...' : edited ? 'Save my changes' : 'Save these details'}
        </button>
        <button className="btn btn-ghost btn-sm" onClick={handleDismiss} disabled={busy}>
          Not now
        </button>
      </div>
    </div>
  )
}

export default function GroupProfileReview({
  proposals,
  onResolved,
}: {
  proposals: GroupProfileProposal[]
  onResolved: (id: number, message: string) => void
}) {
  if (proposals.length === 0) return null

  return (
    <div className="card gp-review">
      <h3 className="settings-subtitle">
        {proposals.length === 1
          ? 'One group description to check'
          : `${proposals.length} group descriptions to check`}
      </h3>
      {proposals.map((p) => (
        <ProposalCard key={p.id} proposal={p} onResolved={onResolved} />
      ))}
    </div>
  )
}
