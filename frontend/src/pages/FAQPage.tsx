import Layout from '../components/Layout'

export default function FAQPage() {
  return (
    <Layout>
      <div className="page-container">
        <div className="container">
          <div className="page-header">
            <h1 className="page-title">Frequently Asked Questions</h1>
            <p className="page-description">Everything you need to know about Freight Pilot</p>
          </div>

          <div className="faq-list">
            <div className="faq-item card">
              <h3 className="faq-question">💡 What is Freight Pilot?</h3>
              <p className="faq-answer">
                AI-powered dispatch management system that automates load management through
                Telegram. Connects Gmail, extracts load details with AI, tracks GPS, and provides
                a real-time dashboard for owners and dispatchers.
              </p>
            </div>

            <div className="faq-item card">
              <h3 className="faq-question">💳 How does billing work?</h3>
              <p className="faq-answer">
                You pay monthly only for active drivers via Stripe. 14-day free trial available.
                $25/driver/month. No hidden fees.
              </p>
            </div>

            <div className="faq-item card">
              <h3 className="faq-question">📧 How does Gmail integration work?</h3>
              <p className="faq-answer">
                Secure OAuth 2.0 connection. Google account authorization required. Bot
                automatically finds rate confirmations in your inbox.
              </p>
            </div>

            <div className="faq-item card">
              <h3 className="faq-question">🗺️ How does GPS tracking work?</h3>
              <p className="faq-answer">
                Samsara integration. Auto notifications when driver approaches pickup/delivery.
                Real-time tracking and ETA updates.
              </p>
            </div>

            <div className="faq-item card">
              <h3 className="faq-question">🤖 What does AI do?</h3>
              <p className="faq-answer">
                Google Gemini AI extracts all load details from rate confirmations: load ID,
                addresses, dates, broker, rate, and more. Eliminates manual data entry.
              </p>
            </div>

            <div className="faq-item card">
              <h3 className="faq-question">👥 Can I add dispatchers?</h3>
              <p className="faq-answer">
                Unlimited dispatchers in Professional and Enterprise plans. Each gets their own
                dashboard login with appropriate permissions.
              </p>
            </div>
          </div>
        </div>
      </div>
    </Layout>
  )
}
