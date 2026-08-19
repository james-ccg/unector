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
                <li>✅ Up to 5 drivers</li>
                <li>✅ AI load extraction</li>
                <li>✅ Gmail integration</li>
                <li>✅ GPS tracking</li>
                <li>✅ Telegram bot</li>
                <li>✅ Basic dashboard</li>
                <li>✅ 1 dispatcher login</li>
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
                <li>✅ Up to 20 drivers</li>
                <li>✅ Everything in Starter</li>
                <li>✅ Advanced analytics</li>
                <li>✅ Custom notifications</li>
                <li>✅ Priority support</li>
                <li>✅ Unlimited dispatchers</li>
                <li>✅ API access</li>
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
                <li>✅ Unlimited drivers</li>
                <li>✅ Everything in Professional</li>
                <li>✅ Dedicated account manager</li>
                <li>✅ Custom integrations</li>
                <li>✅ White-label options</li>
                <li>✅ SLA guarantee</li>
                <li>✅ 24/7 phone support</li>
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
