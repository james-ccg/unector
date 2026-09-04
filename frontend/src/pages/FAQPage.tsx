import { Lightbulb, CreditCard, Mail, Map, Bot, Users, Bell } from 'lucide-react'
import Layout from '../components/Layout'

export default function FAQPage() {
  return (
    <Layout>
      <div className="page-container">
        <div className="container">
          <div className="page-header">
            <h1 className="page-title">Frequently Asked Questions</h1>
            <p className="page-description">Everything you need to know about Unector</p>
          </div>

          <div className="faq-list">
            <div className="faq-item card">
              <h3 className="faq-question"><Lightbulb size={18} /> What is Unector?</h3>
              <p className="faq-answer">
                AI-powered dispatch management system that automates load management through
                Telegram. Connects Gmail, extracts load details with AI, tracks GPS, and provides
                a real-time dashboard for owners and dispatchers.
              </p>
            </div>

            <div className="faq-item card">
              <h3 className="faq-question"><CreditCard size={18} /> How does billing work?</h3>
              <p className="faq-answer">
                Free to look around. Pro is $20/mo (or $200/yr) for up to 5 active drivers.
                Max plans are $100/mo for up to 25 drivers, or $200/mo for up to 100 drivers.
                Every paid plan starts with a 7-day free trial. Starting one asks for a payment
                method - card, PayPal or a wallet - but nothing is charged while the trial runs.
                The plan then renews by itself: the price is charged on the day the trial ends and
                every period after, until you cancel from Settings. Until that first payment goes
                through your only payment method cannot be removed, since it is the only way to
                take it; afterwards you can remove it whenever you like, and doing so ends the plan
                when the period you have paid for runs out. We email you two days before a trial
                ends so the charge is never a surprise.
              </p>
            </div>

            <div className="faq-item card">
              <h3 className="faq-question"><Mail size={18} /> How does Gmail integration work?</h3>
              <p className="faq-answer">
                Secure OAuth 2.0 connection. Google account authorization required. Bot
                automatically finds rate confirmations in your inbox.
              </p>
            </div>

            <div className="faq-item card">
              <h3 className="faq-question"><Map size={18} /> How does GPS tracking work?</h3>
              <p className="faq-answer">
                Samsara integration. Checks each vehicle's GPS position every couple of minutes
                and automatically messages the driver's group when they're near pickup or delivery.
              </p>
            </div>

            <div className="faq-item card">
              <h3 className="faq-question"><Bot size={18} /> What does AI do?</h3>
              <p className="faq-answer">
                Google Gemini AI extracts all load details from rate confirmations: load ID,
                addresses, dates, broker, rate, and more. Eliminates manual data entry.
              </p>
            </div>

            <div className="faq-item card">
              <h3 className="faq-question"><Users size={18} /> Can I add dispatchers?</h3>
              <p className="faq-answer">
                Yes - add as many dispatchers as you need, each with their own dashboard login
                and permissions.
              </p>
            </div>

            <div className="faq-item card">
              <h3 className="faq-question"><Bell size={18} /> How do notifications work?</h3>
              <p className="faq-answer">
                Three places: a bell in the dashboard, a Telegram message, and email. Settings
                &rarr; Notifications is where you choose which of them each kind of news reaches
                you on, and an owner and a dispatcher each set their own. The dashboard list
                always gets everything - email can bounce and Telegram won't message anyone who
                hasn't started a chat with the bot, so the bell is the one place nothing goes
                missing. A few things stay on whatever you choose: a failed payment, a sign-in
                you didn't make, an integration that stopped working. They're shown as locked
                rather than hidden, so you can always see what will reach you.
              </p>
            </div>
          </div>
        </div>
      </div>
    </Layout>
  )
}
