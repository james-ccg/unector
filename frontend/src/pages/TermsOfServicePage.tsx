import { Scale } from 'lucide-react'
import Layout from '../components/Layout'

export default function TermsOfServicePage() {
  return (
    <Layout>
      <div className="page-container">
        <div className="container">
          <div className="page-header">
            <h1 className="page-title"><Scale size={36} /> Terms of Service</h1>
            <p className="page-description">
              The terms that apply when your company uses Freight Pilot.
            </p>
          </div>
          <p className="legal-updated">Last updated: August 29, 2026</p>

          <div className="legal-content">
            <section>
              <p>
                These Terms of Service ("Terms") are an agreement between your trucking company ("you," "your
                company") and Freight Pilot, operated by <em className="legal-fill">[Legal entity name]</em>
                ("Freight Pilot," "we," "us"), governing your use of our Telegram bot, web dashboard, and related
                services (the "Service"). By registering a company account, you agree to these Terms.
              </p>
            </section>

            <section>
              <h2>1. The Service</h2>
              <p>
                Freight Pilot is a dispatch-automation tool: it reads Rate Confirmation documents, uses AI to extract
                and check load details against photos and Bills of Lading, forwards Proof of Delivery documents,
                tracks GPS proximity to pickup/delivery, and gives an owner and their dispatchers a web dashboard to
                manage drivers, dispatcher logins, and billing.
              </p>
              <h3>AI is an assistant, not a certifier</h3>
              <p>
                The AI features (document extraction, photo review, BOL comparison) are decision-support tools meant
                to speed up manual checks, not to replace them. AI-extracted data and AI-generated comparisons can be
                incomplete or wrong - your company remains responsible for verifying load details, seal numbers,
                weights, and delivery requirements before acting on them.
              </p>
            </section>

            <section>
              <h2>2. Accounts</h2>
              <ul>
                <li>You must provide accurate company information (including your MC number) at registration, and keep your login credentials confidential.</li>
                <li>The company owner is responsible for the dispatcher accounts and driver links they create, and for anything done through those accounts.</li>
                <li>You're responsible for keeping the phone numbers, Telegram accounts, and email addresses linked to your account current, since we use them for account recovery and security notices.</li>
                <li>We may suspend or terminate an account for a violation of these Terms, for non-payment, or for activity that puts the Service or other users at risk.</li>
              </ul>
            </section>

            <section>
              <h2>3. Subscriptions &amp; billing</h2>
              <ul>
                <li>Freight Pilot offers a Free plan (one active driver) and paid plans (Pro, Max 5x, Max 20x) with higher driver limits, billed monthly or yearly through Stripe.</li>
                <li>Paid plans include a 7-day free trial. Unless canceled before the trial ends, the subscription automatically converts to a paid, recurring plan and is billed to the payment method on file.</li>
                <li>Either the company owner or a dispatcher may manage or cancel the subscription - we treat both as authorized to act on the company's billing.</li>
                <li>Subscriptions renew automatically until canceled. You can cancel anytime from the dashboard; cancellation takes effect at the end of the current billing period, and we don't provide refunds for the unused portion of a period except where required by law.</li>
                <li>Adding drivers beyond your plan's limit isn't possible until you upgrade or remove an existing driver.</li>
              </ul>
            </section>

            <section>
              <h2>4. Acceptable use</h2>
              <p>You agree not to:</p>
              <ul>
                <li>Use the Service for any unlawful purpose, or to transport freight you're not legally authorized to carry.</li>
                <li>Attempt to bypass rate limits, authentication, or other security controls, or access another company's data.</li>
                <li>Submit documents or photos you don't have the right to share, or that are deliberately falsified.</li>
                <li>Use the Service to send spam, or to abuse the Telegram bot, AI features, or GPS integration in a way that degrades the Service for other users.</li>
                <li>Reverse-engineer, scrape, or resell the Service without our written permission.</li>
              </ul>
            </section>

            <section>
              <h2>5. Third-party services</h2>
              <p>
                The Service integrates with Google (Gmail, Gemini), Stripe, Samsara, Telegram, and Cloudflare. Your
                use of those integrations is also subject to each provider's own terms, and we're not responsible
                for their availability, accuracy, or changes to their APIs. If a connected provider has an outage or
                changes its API in a way that affects Freight Pilot, we'll work to restore the integration but can't
                guarantee a specific timeline.
              </p>
            </section>

            <section>
              <h2>6. Intellectual property</h2>
              <p>
                Freight Pilot and its underlying software, design, and branding are our property. You retain
                ownership of the load data, documents, and photos you submit; by using the Service you grant us a
                limited license to process that content (including sending it to Google's Gemini API) solely to
                provide the Service to you.
              </p>
            </section>

            <section>
              <h2>7. Disclaimers &amp; limitation of liability</h2>
              <p>
                The Service is provided "as is" and "as available," without warranties of any kind, express or
                implied. We don't warrant that the Service, its AI features, or any connected integration will be
                uninterrupted, error-free, or perfectly accurate. To the maximum extent permitted by law, Freight
                Pilot won't be liable for indirect, incidental, or consequential damages (including lost freight
                revenue, missed deliveries, or detention charges) arising from your use of the Service, and our
                total liability for any claim is limited to the amount you paid us in the 12 months before the
                claim arose.
              </p>
            </section>

            <section>
              <h2>8. Termination</h2>
              <p>
                You may stop using the Service and delete your account at any time. We may suspend or terminate
                access for a breach of these Terms, non-payment, or extended inactivity, with notice where
                reasonably possible. Sections that by their nature should survive termination (billing owed,
                intellectual property, disclaimers, limitation of liability) continue to apply after termination.
              </p>
            </section>

            <section>
              <h2>9. Governing law</h2>
              <p>
                These Terms are governed by the laws of <em className="legal-fill">[Governing state/country]</em>,
                without regard to its conflict-of-law rules.
              </p>
            </section>

            <section>
              <h2>10. Changes to these Terms</h2>
              <p>
                We may update these Terms from time to time. If we make a material change, we'll post the update
                here with a new "Last updated" date and, where appropriate, notify account owners directly.
                Continuing to use the Service after a change takes effect means you accept the updated Terms.
              </p>
            </section>

            <section>
              <h2>11. Contact us</h2>
              <p>
                Questions about these Terms: <a href="mailto:freightpilot.bot@gmail.com">freightpilot.bot@gmail.com</a>, or
                message us on Telegram at <a href="https://t.me/Freight_Pilot" target="_blank" rel="noopener noreferrer">@Freight_Pilot</a>.
              </p>
            </section>
          </div>
        </div>
      </div>
    </Layout>
  )
}
