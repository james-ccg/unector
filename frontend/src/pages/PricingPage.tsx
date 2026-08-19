import { Check } from 'lucide-react'
import Layout from '../components/Layout'

export default function PricingPage() {
  return (
    <Layout>
      <div className="page-container">
        <div className="container">
          <div className="page-header">
            <h1 className="page-title">Simple, Transparent Pricing</h1>
            <p className="page-description">
              Only pay for active drivers. 14-day free trial. Cancel anytime.
            </p>
          </div>

          <div className="pricing-grid">
            <div className="pricing-card card">
              <div className="pricing-badge">Starter</div>
              <div className="pricing-price">
                <span className="price-amount">$25</span>
                <span className="price-period">/ driver / month</span>
              </div>
              <p className="pricing-description">Perfect for small fleets starting out</p>
              <ul className="pricing-features">
                <li><Check size={16} /> Up to 5 drivers</li>
                <li><Check size={16} /> AI load extraction</li>
                <li><Check size={16} /> Gmail integration</li>
                <li><Check size={16} /> GPS tracking</li>
                <li><Check size={16} /> Telegram bot</li>
                <li><Check size={16} /> Basic dashboard</li>
                <li><Check size={16} /> 1 dispatcher login</li>
              </ul>
              <a href="/register" className="btn-primary btn-full">
                Start Free Trial
              </a>
            </div>

            <div className="pricing-card card featured">
              <div className="pricing-badge featured">Most Popular</div>
              <div className="pricing-price">
                <span className="price-amount">$22</span>
                <span className="price-period">/ driver / month</span>
              </div>
              <p className="pricing-description">Best value for growing operations</p>
              <ul className="pricing-features">
                <li><Check size={16} /> Up to 20 drivers</li>
                <li><Check size={16} /> Everything in Starter</li>
                <li><Check size={16} /> Advanced analytics</li>
                <li><Check size={16} /> Custom notifications</li>
                <li><Check size={16} /> Priority support</li>
                <li><Check size={16} /> Unlimited dispatchers</li>
                <li><Check size={16} /> API access</li>
              </ul>
              <a href="/register" className="btn-primary btn-full">
                Start Free Trial
              </a>
            </div>

            <div className="pricing-card card">
              <div className="pricing-badge">Enterprise</div>
              <div className="pricing-price">
                <span className="price-amount">Custom</span>
              </div>
              <p className="pricing-description">For large fleets with custom needs</p>
              <ul className="pricing-features">
                <li><Check size={16} /> Unlimited drivers</li>
                <li><Check size={16} /> Everything in Professional</li>
                <li><Check size={16} /> Dedicated account manager</li>
                <li><Check size={16} /> Custom integrations</li>
                <li><Check size={16} /> White-label options</li>
                <li><Check size={16} /> SLA guarantee</li>
                <li><Check size={16} /> 24/7 phone support</li>
              </ul>
              <a href="#contact" className="btn-secondary btn-full">
                Contact Sales
              </a>
            </div>
          </div>
        </div>
      </div>
    </Layout>
  )
}
