import { ShieldCheck } from 'lucide-react'
import Layout from '../components/Layout'

export default function PrivacyPolicyPage() {
  return (
    <Layout>
      <div className="page-container">
        <div className="container">
          <div className="page-header">
            <h1 className="page-title"><ShieldCheck size={36} /> Privacy Policy</h1>
            <p className="page-description">
              What we collect, why we collect it, and what we do (and don't do) with it.
            </p>
          </div>
          <p className="legal-updated">Last updated: August 29, 2026</p>

          <div className="legal-content">
            <section>
              <p>
                Unector ("Unector," "we," "us") is a dispatch-automation service for trucking companies,
                operated by Unector LLC. This policy explains what
                information we collect through our Telegram bot, web dashboard, and related services (together, the
                "Service"), how we use it, and the choices you have. It applies to the company owners and dispatchers
                who use the Service, and to the drivers whose information an owner or dispatcher adds to it.
              </p>
              <p>
                We built Unector to automate dispatch paperwork, not to build a profile on anyone. We don't
                sell data, and we don't use your business's information for advertising.
              </p>
            </section>

            <section>
              <h2>1. Information we collect</h2>
              <h3>Account information</h3>
              <p>
                When a company registers, we collect its MC number, company name, and a contact email, and set a
                password (stored as a bcrypt hash - we never see or store the plaintext password). An owner can
                create dispatcher logins, each with their own username and password. Owners and dispatchers may
                optionally add a display status message and a profile picture, both visible to their own teammates.
              </p>
              <h3>Driver information</h3>
              <p>
                An owner or dispatcher can add drivers to the Service, providing a name and linking each driver's
                Telegram account (via a one-time linking code) so the bot can message that driver's dispatch group.
              </p>
              <h3>Load and document data</h3>
              <p>
                The bot reads Rate Confirmation (RC) emails or PDFs a driver/dispatcher submits, and photos of loads,
                seals, and Bills of Lading (BOL) sent through Telegram, and sends this content to Google's Gemini API
                to extract structured details (load ID, addresses, dates, rate, broker, etc.) and to check photos
                against that data. The extracted details and the resulting load record are stored so the dashboard
                can show load history; the underlying photos and email attachments are not stored longer than needed
                to process them.
              </p>
              <h3>Location data</h3>
              <p>
                If a company connects a Samsara account, we periodically read each linked vehicle's GPS position
                from Samsara's API, only to detect proximity to a pickup/delivery point and trigger the relevant
                driver-group notification. We don't build or retain a location history beyond what's needed for
                that check.
              </p>
              <h3>Payment information</h3>
              <p>
                Billing is handled entirely by Stripe. We never receive or store your card number - Stripe gives us
                only a subscription status, plan tier, and billing dates.
              </p>
              <h3>Security &amp; two-factor authentication data</h3>
              <p>
                If you enable two-factor authentication, we store what's needed to verify it: an encrypted TOTP
                secret (authenticator apps), a phone number (SMS codes), or a WebAuthn public key (security keys,
                Touch ID, Windows Hello) - never a private key, which never leaves your device. Recovery codes are
                stored as one-way hashes, the same way passwords are.
              </p>
              <h3>Automatically collected data</h3>
              <p>
                Our servers log standard technical data (IP address, request timestamps, user agent) for security
                and troubleshooting. We use no third-party analytics, no advertising, and no cross-site trackers
                of any kind.
              </p>

              <h3>Cookies and browser storage</h3>
              <p>
                This is the complete list &mdash; there is nothing else. You can change the optional choices at
                any time from Settings &rarr; App Preferences &rarr; What we store, and withdrawing a choice
                deletes what was stored under it.
              </p>
              <p><strong>Required, and not optional</strong> &mdash; the site cannot work without these:</p>
              <ul>
                <li><code>fp_session</code> &mdash; keeps you signed in. Set by the server and not readable by page scripts.</li>
                <li><code>fp_csrf</code> &mdash; stops other sites making requests as you.</li>
                <li><code>fp-register-plan</code> &mdash; carries the plan you picked through signup.</li>
                <li><code>fp-consent</code> &mdash; remembers your answer to the question below, so you aren&apos;t asked repeatedly.</li>
              </ul>
              <p><strong>Optional, off until you allow them</strong> &mdash; grouped under a single
                &ldquo;Remember my settings&rdquo; choice:</p>
              <ul>
                <li><code>fp-theme</code>, <code>fp-font</code>, <code>fp-reduce-motion</code> &mdash; your theme, interface font and reduced-motion setting. Declined, the app still follows your device settings; it just won&apos;t remember changes you make here.</li>
                <li><code>fp-game-tickets</code>, <code>fp-game-queue</code> &mdash; progress on the offline page at <code>/play</code>, held until it can be uploaded.</li>
              </ul>
            </section>

            <section>
              <h2>2. How we use this information</h2>
              <ul>
                <li>To operate the core service: extracting load data, checking photos, tracking GPS proximity, and messaging drivers.</li>
                <li>To authenticate you and keep your account secure (password hashing, 2FA, rate limiting on login attempts).</li>
                <li>To bill your subscription and enforce your plan's driver limit.</li>
                <li>To send account-related email (password resets, 2FA codes, registration verification) from our own address.</li>
                <li>To respond to support requests and diagnose bugs.</li>
              </ul>
              <p>We do not use your data to train AI models, and we do not sell or rent it to third parties.</p>
            </section>

            <section>
              <h2>3. Who we share it with</h2>
              <p>We share data only with the service providers needed to run Unector, and only what each one needs to do its job:</p>
              <ul>
                <li><strong>Google</strong> - Gemini API (document/photo extraction) and, only if you connect your inbox, the Gmail API (reads emails to find RCs, sends emails to deliver PODs - nothing else in your inbox is accessed).</li>
                <li><strong>Stripe</strong> - payment processing and subscription management.</li>
                <li><strong>Samsara</strong> - GPS vehicle location, only if you connect a Samsara account.</li>
                <li><strong>Telegram</strong> - the bot and all driver/dispatcher messaging runs on Telegram's platform, subject to Telegram's own privacy policy.</li>
                <li><strong>Cloudflare</strong> - Turnstile, a bot-detection check on our login/registration forms.</li>
                <li>An SMS provider, only if you enable SMS-based two-factor authentication.</li>
              </ul>
              <p>
                We may also disclose information if required by law, or to protect the rights, property, or safety
                of Unector, our users, or the public.
              </p>
            </section>

            <section>
              <h2>4. How we protect it</h2>
              <ul>
                <li>All traffic between your device and our servers is encrypted (HTTPS/TLS).</li>
                <li>Passwords are hashed with bcrypt; connected-account credentials (Gmail refresh tokens, Samsara API keys) are encrypted at rest.</li>
                <li>The session cookie is httpOnly (inaccessible to page scripts) and paired with a CSRF token on every account-changing request.</li>
                <li>Every login-related endpoint is rate-limited against brute-force attempts.</li>
              </ul>
            </section>

            <section>
              <h2>5. Your choices &amp; rights</h2>
              <ul>
                <li>Disconnect Gmail or Samsara at any time from Settings - this immediately deletes the stored credential.</li>
                <li>An owner can edit or remove a dispatcher account, and remove a driver, from the dashboard at any time.</li>
                <li>You can request a copy of your account's data, or full deletion of your account and its data, by contacting us (below). We'll act on a deletion request within a reasonable time, except for records we're legally required to retain.</li>
              </ul>
            </section>

            <section>
              <h2>6. Data retention</h2>
              <p>
                We keep account and load data for as long as your account is active, since load history is part of
                the product (drivers/dispatchers use it to look up past loads). If you close your account, we
                delete your account data within a reasonable period, except where we need to retain limited records
                for legal, tax, or security purposes.
              </p>
            </section>

            <section>
              <h2>7. Children's privacy</h2>
              <p>
                Unector is a business tool for trucking companies and is not directed at, or knowingly used
                by, anyone under 18.
              </p>
            </section>

            <section>
              <h2>8. Changes to this policy</h2>
              <p>
                If we make a material change to this policy, we'll post the update here with a new "Last updated"
                date, and where appropriate, notify account owners directly.
              </p>
            </section>

            <section>
              <h2>9. Contact us</h2>
              <p>
                Questions about this policy or your data: <a href="mailto:unector.bot@gmail.com">unector.bot@gmail.com</a>, or
                message us on Telegram at <a href="https://t.me/Unector" target="_blank" rel="noopener noreferrer">@Unector</a>.
              </p>
            </section>
          </div>
        </div>
      </div>
    </Layout>
  )
}
