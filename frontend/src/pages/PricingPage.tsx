import { useState } from 'react'
import { Check } from 'lucide-react'
import Layout from '../components/Layout'

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

  const proPrice = priceDisplay('pro', proInterval)
  const maxTier: Tier = maxMultiplier === '5x' ? 'max_5x' : 'max_20x'
  const maxPrice = priceDisplay(maxTier, maxInterval)
  const maxInfo = MAX_FEATURES[maxMultiplier]

  return (
    <Layout>
      <div className="page-container">
        <div className="container">
          <div className="page-header">
            <h1 className="page-title">Simple, Transparent Pricing</h1>
            <p className="page-description">
              Start free, no card required. Every paid plan includes a 7-day free trial.
            </p>
          </div>

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
              <a href="/register" className="pricing-cta btn-secondary">Get started free</a>
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
              <a href={`/register?plan=pro&interval=${proInterval}`} className="pricing-cta btn-primary">
                Start Pro trial
              </a>
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
              <a href={`/register?plan=${maxTier}&interval=${maxInterval}`} className="pricing-cta btn-secondary">
                Start Max {maxMultiplier} trial
              </a>
            </div>
          </div>

          <p className="pricing-footnote">
            Prices shown do not include tax. A trial isn't available twice for the same email,
            company, card, or connected Gmail account.
          </p>
        </div>
      </div>
    </Layout>
  )
}
