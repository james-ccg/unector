import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Check } from 'lucide-react'
import Layout from '../components/Layout'
import Alert from '../components/Alert'
import { useAuth } from '../context/AuthContext'
import { billingApi, errorMessage } from '../services/api'

type Interval = 'month' | 'year'
type Multiplier = '5x' | '20x'
type Tier = 'free' | 'pro' | 'max_5x' | 'max_20x'

const MONTHLY_PRICE: Record<Tier, number> = { free: 0, pro: 20, max_5x: 100, max_20x: 200 }
const YEARLY_PRICE: Record<Tier, number> = { free: 0, pro: 200, max_5x: 1000, max_20x: 2000 }

function priceDisplay(tier: Tier, interval: Interval) {
  if (tier === 'free') return { amount: '$0', note: null as string | null }
  if (interval === 'month') {
    return { amount: `$${MONTHLY_PRICE[tier]}`, note: null as string | null }
  }
  const perMonth = Math.round(YEARLY_PRICE[tier] / 12)
  return { amount: `$${perMonth}`, note: `$${YEARLY_PRICE[tier]} billed yearly` }
}

const MAX_FEATURES: Record<Multiplier, { tagline: string; drivers: string; everything: string }> = {
  '5x': { tagline: '5x more drivers than Pro', drivers: 'Up to 25 active drivers', everything: 'Everything in Pro' },
  '20x': { tagline: '20x more drivers than Pro', drivers: 'Up to 100 active drivers', everything: 'Everything in Max 5x' },
}

function IntervalToggle({ value, onChange }: { value: Interval; onChange: (v: Interval) => void }) {
  return (
    <div className="pricing-pill-toggle">
      <button
        type="button"
        className={`pricing-pill-option ${value === 'month' ? 'active' : ''}`}
        onClick={() => onChange('month')}
      >
        Monthly
      </button>
      <button
        type="button"
        className={`pricing-pill-option ${value === 'year' ? 'active' : ''}`}
        onClick={() => onChange('year')}
      >
        Yearly
      </button>
    </div>
  )
}

export default function PricingPage() {
  const [proInterval, setProInterval] = useState<Interval>('month')
  const [maxInterval, setMaxInterval] = useState<Interval>('month')
  const [maxMultiplier, setMaxMultiplier] = useState<Multiplier>('5x')
  const [upgradeBusy, setUpgradeBusy] = useState(false)
  const [upgradeError, setUpgradeError] = useState('')
  const { isAuthenticated } = useAuth()
  const navigate = useNavigate()

  const proPrice = priceDisplay('pro', proInterval)
  const maxTier: Tier = maxMultiplier === '5x' ? 'max_5x' : 'max_20x'
  const maxPrice = priceDisplay(maxTier, maxInterval)
  const maxInfo = MAX_FEATURES[maxMultiplier]

  // An already-logged-in owner clicking a paid plan's CTA must go straight
  // to Stripe Checkout, not through /register - that page is for brand-new
  // signups (Gmail-first, then company details) and makes no sense for an
  // account that already exists. This used to route every visitor through
  // /register?plan=..., which for an already-authenticated user landed on
  // that page's "Connect Gmail" step and then silently bounced back to
  // /dashboard the moment checkout failed for any reason.
  const handleUpgradeClick = async (tier: 'pro' | 'max_5x' | 'max_20x', interval: Interval) => {
    if (!isAuthenticated) {
      window.location.href = `/register?plan=${tier}&interval=${interval}`
      return
    }
    setUpgradeError('')
    setUpgradeBusy(true)
    try {
      const { url } = await billingApi.checkout(tier, interval)
      window.location.href = url
    } catch (err) {
      setUpgradeError(errorMessage(err, "Couldn't start checkout. Try again in a moment."))
      setUpgradeBusy(false)
    }
  }

  const handleFreeClick = () => {
    if (isAuthenticated) {
      navigate('/dashboard')
    } else {
      window.location.href = '/register'
    }
  }

  return (
    <Layout>
      <div className="page-container">
        <div className="container">
          <div className="page-header">
            <h1 className="page-title">Simple, Transparent Pricing</h1>
            <p className="page-description">
              Start free, no card required - and the 7-day trial on every paid plan doesn't ask
              for one either. Add a card when you decide to keep it. Nothing is charged until you
              do, and if you never do, the trial simply stops. Add one and the plan renews by
              itself when the trial ends - the terms are spelled out below.
            </p>
          </div>

          {/* Above the cards, not below them. Sitting underneath, this was
              overlapped by the featured card's glow and fell outside the
              viewport the click happened in - so a failed upgrade looked like
              the button simply did nothing. */}
          {upgradeError && (
            <Alert kind="error" className="pricing-alert" onDismiss={() => setUpgradeError('')}>
              {upgradeError}
            </Alert>
          )}

          <div className="pricing-grid">
            <div className="pricing-card">
              <h3 className="pricing-name">Free</h3>
              <div className="pricing-price">
                <span className="price-amount">$0</span>
              </div>
              <p className="pricing-description">Look around before you commit</p>
              <ul className="pricing-features">
                <li><Check size={16} /> Full access to the dashboard and all pages</li>
                <li><Check size={16} /> Up to 1 active driver</li>
                <li><Check size={16} /> No credit card required</li>
              </ul>
              <button type="button" onClick={handleFreeClick} className="pricing-cta btn-secondary">
                {isAuthenticated ? 'Go to dashboard' : 'Get started free'}
              </button>
            </div>

            <div className="pricing-card featured">
              <div className="pricing-badge featured">Most popular</div>
              <h3 className="pricing-name">Pro</h3>
              <IntervalToggle value={proInterval} onChange={setProInterval} />
              <div className="pricing-price">
                <span className="price-amount">{proPrice.amount}</span>
                <span className="price-period">/mo</span>
              </div>
              {proInterval === 'year' && (
                <p className="pricing-price-note">
                  {proPrice.note}
                  <span className="pricing-save-badge">Save 17%</span>
                </p>
              )}
              <p className="pricing-description">For small fleets running real dispatch</p>
              <ul className="pricing-features">
                <li><Check size={16} /> Up to 5 active drivers</li>
                <li><Check size={16} /> AI load extraction from Gmail</li>
                <li><Check size={16} /> GPS tracking via Samsara</li>
                <li><Check size={16} /> Telegram bot for drivers</li>
                <li><Check size={16} /> Unlimited dispatchers</li>
                <li><Check size={16} /> 7-day free trial</li>
              </ul>
              <button
                type="button"
                onClick={() => handleUpgradeClick('pro', proInterval)}
                className="pricing-cta btn-primary"
                disabled={upgradeBusy}
              >
                {upgradeBusy ? 'Starting checkout...' : 'Start Pro trial'}
              </button>
            </div>

            <div className="pricing-card">
              <h3 className="pricing-name">Max</h3>
              <div className="pricing-pill-toggle">
                <button
                  type="button"
                  className={`pricing-pill-option ${maxMultiplier === '5x' ? 'active' : ''}`}
                  onClick={() => setMaxMultiplier('5x')}
                >
                  5x
                </button>
                <button
                  type="button"
                  className={`pricing-pill-option ${maxMultiplier === '20x' ? 'active' : ''}`}
                  onClick={() => setMaxMultiplier('20x')}
                >
                  20x
                </button>
              </div>
              <IntervalToggle value={maxInterval} onChange={setMaxInterval} />
              <div className="pricing-price">
                <span className="price-amount">{maxPrice.amount}</span>
                <span className="price-period">/mo</span>
              </div>
              {maxInterval === 'year' && (
                <p className="pricing-price-note">
                  {maxPrice.note}
                  <span className="pricing-save-badge">Save 17%</span>
                </p>
              )}
              <p className="pricing-description">{maxInfo.tagline}</p>
              <ul className="pricing-features">
                <li><Check size={16} /> {maxInfo.drivers}</li>
                <li><Check size={16} /> {maxInfo.everything}</li>
                <li><Check size={16} /> Priority support</li>
                <li><Check size={16} /> 7-day free trial</li>
              </ul>
              <button
                type="button"
                onClick={() => handleUpgradeClick(maxTier, maxInterval)}
                className="pricing-cta btn-secondary"
                disabled={upgradeBusy}
              >
                {upgradeBusy ? 'Starting checkout...' : `Start Max ${maxMultiplier} trial`}
              </button>
            </div>
          </div>

          <div className="pricing-terms">
            <h2 className="pricing-terms-title">Before you start a trial</h2>
            <ul className="pricing-terms-list">
              <li>
                The trial runs 7 days and costs nothing. It does not ask for a card, and with no
                card on file it simply stops at the end - you are not charged and nothing renews.
              </li>
              <li>
                <strong>If you do put a card on file, the plan renews by itself.</strong> On the
                day the trial ends, the price of the plan you chose is charged to that card
                automatically, and again every month or year after that until you cancel.
              </li>
              <li>
                <strong>While a plan or trial is running, the last card on file can&apos;t be
                removed.</strong> A card with nothing to pay for can be taken off at any time; one
                that is holding up a live plan can be replaced by adding another, or removed once
                the plan is cancelled.
              </li>
              <li>
                Cancel whenever you like, from Settings &rarr; Billing &rarr; Manage billing.
                Cancelling before the trial ends means you are never charged.
              </li>
              <li>
                Prices shown do not include tax. A trial isn&apos;t available twice for the same
                email, company, card, or connected Gmail account.
              </li>
            </ul>
          </div>
        </div>
      </div>
    </Layout>
  )
}
