import { useState } from 'react'
import { Check } from 'lucide-react'
import Layout from '../components/Layout'

type Interval = 'month' | 'year'
type Tier = 'free' | 'pro' | 'max_5x' | 'max_20x'

const MONTHLY_PRICE: Record<Tier, number> = { free: 0, pro: 20, max_5x: 100, max_20x: 200 }
const YEARLY_PRICE: Record<Tier, number> = { free: 0, pro: 200, max_5x: 1000, max_20x: 2000 }

function priceDisplay(tier: Tier, interval: Interval) {
  if (tier === 'free') return { amount: '$0', note: null as string | null }
  if (interval === 'month') {
    return { amount: `$${MONTHLY_PRICE[tier]}`, note: null }
  }
  const perMonth = Math.round(YEARLY_PRICE[tier] / 12)
  return { amount: `$${perMonth}`, note: `$${YEARLY_PRICE[tier]} billed yearly` }
}

interface PlanCard {
  tier: Tier
  name: string
  tagline: string
  badge?: string
  featured?: boolean
  features: string[]
  cta: string
}

const PLANS: PlanCard[] = [
  {
    tier: 'free',
    name: 'Free',
    tagline: 'Look around before you commit',
    features: [
      'Full access to the dashboard and all pages',
      'Up to 1 active driver',
      'No credit card required',
    ],
    cta: 'Get started free',
  },
  {
    tier: 'pro',
    name: 'Pro',
    tagline: 'For small fleets running real dispatch',
    badge: 'Most popular',
    featured: true,
    features: [
      'Up to 5 active drivers',
      'AI load extraction from Gmail',
      'GPS tracking via Samsara',
      'Telegram bot for drivers',
      'Unlimited dispatchers',
      '7-day free trial',
    ],
    cta: 'Start Pro trial',
  },
  {
    tier: 'max_5x',
    name: 'Max 5x',
    tagline: '5x more drivers than Pro',
    features: [
      'Up to 25 active drivers',
      'Everything in Pro',
      'Priority support',
      '7-day free trial',
    ],
    cta: 'Start Max 5x trial',
  },
  {
    tier: 'max_20x',
    name: 'Max 20x',
    tagline: '20x more drivers than Pro',
    features: [
      'Up to 100 active drivers',
      'Everything in Max 5x',
      'Priority support',
      '7-day free trial',
    ],
    cta: 'Start Max 20x trial',
  },
]

export default function PricingPage() {
  const [interval, setInterval] = useState<Interval>('month')

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

          <div className="pricing-toggle-wrap">
            <div className="billing-toggle">
              <button
                type="button"
                className={`billing-toggle-option ${interval === 'month' ? 'active' : ''}`}
                onClick={() => setInterval('month')}
              >
                Monthly
              </button>
              <button
                type="button"
                className={`billing-toggle-option ${interval === 'year' ? 'active' : ''}`}
                onClick={() => setInterval('year')}
              >
                Yearly <span className="billing-toggle-save">Save 17%</span>
              </button>
            </div>
          </div>

          <div className="pricing-grid">
            {PLANS.map((plan) => {
              const price = priceDisplay(plan.tier, interval)
              const href =
                plan.tier === 'free' ? '/register' : `/register?plan=${plan.tier}&interval=${interval}`
              return (
                <div key={plan.tier} className={`pricing-card ${plan.featured ? 'featured' : ''}`}>
                  {plan.badge && <div className="pricing-badge featured">{plan.badge}</div>}
                  <h3 className="pricing-name">{plan.name}</h3>
                  <div className="pricing-price">
                    <span className="price-amount">{price.amount}</span>
                    {plan.tier !== 'free' && <span className="price-period">/mo</span>}
                  </div>
                  {price.note && <p className="pricing-price-note">{price.note}</p>}
                  <p className="pricing-description">{plan.tagline}</p>
                  <ul className="pricing-features">
                    {plan.features.map((f) => (
                      <li key={f}>
                        <Check size={16} /> {f}
                      </li>
                    ))}
                  </ul>
                  <a
                    href={href}
                    className={`pricing-cta ${plan.featured ? 'btn-primary' : 'btn-secondary'}`}
                  >
                    {plan.cta}
                  </a>
                </div>
              )
            })}
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
