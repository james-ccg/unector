import { Newspaper, Construction, Palette, Gamepad2, ShieldCheck, Map, CreditCard, Rocket } from 'lucide-react'
import Layout from '../components/Layout'

/** The changelog, and only what actually happened.
 *
 * This page used to carry five releases dated September 2025 through
 * January 2026. The repository's first commit is 19 August 2026, so none of
 * those dates described anything - it was a year of history invented to make
 * a two-week-old product look established. Anyone who checked would have
 * stopped believing the rest of the site too, which is a far worse trade
 * than looking new.
 *
 * Every entry below is dated from the commit that shipped it. If something
 * is not finished, it goes in the "In progress" card at the top rather than
 * being written up as though it were done. */
export default function UpdatesPage() {
  return (
    <Layout>
      <div className="page-container">
        <div className="container">
          <div className="page-header">
            <h1 className="page-title"><Newspaper size={36} /> Product Updates</h1>
            <p className="page-description">
              Freight Pilot&apos;s first build was 19 August 2026. Everything below has shipped
              since then, dated as it happened. It is a short history, and it is the real one.
            </p>
          </div>

          <div className="updates-timeline">
            <div className="update-card card">
              <div className="update-date">In progress</div>
              <h3 className="update-title"><Construction size={20} /> Not finished yet</h3>
              <ul className="update-list">
                <li>
                  Gmail connections currently need reconnecting once a week. Google revokes access
                  for apps whose consent screen is still under review, and ours is. Settings warns
                  two days ahead; the limit disappears once the review clears.
                </li>
                <li>The offline game only works offline from your second visit, once the browser has cached it.</li>
                <li>No public status page or uptime figure - we will not publish one we cannot measure.</li>
              </ul>
            </div>

            <div className="update-card card">
              <div className="update-date">1-2 September 2026</div>
              <h3 className="update-title"><Palette size={20} /> Identity</h3>
              <ul className="update-list">
                <li>The logo across the header, footer and browser tab, with the tab icon following your system theme</li>
                <li>Profile and description artwork for the Telegram bot</li>
                <li>Fixes: the homepage product preview was rendering unstyled, and two icons were drawn from bad path data</li>
              </ul>
            </div>

            <div className="update-card card">
              <div className="update-date">30-31 August 2026</div>
              <h3 className="update-title"><Gamepad2 size={20} /> Offline, and the homepage</h3>
              <ul className="update-list">
                <li>A cargo-loading game for when the connection drops, with a leaderboard that syncs once you are back</li>
                <li>A 404 page that offers somewhere to go instead of a dead end</li>
                <li>The homepage now shows the dispatch message the bot actually posts, rather than describing it</li>
                <li>The dashboard organises the fleet around trucks instead of drivers</li>
              </ul>
            </div>

            <div className="update-card card">
              <div className="update-date">29 August 2026</div>
              <h3 className="update-title"><ShieldCheck size={20} /> Sign-in and legal</h3>
              <ul className="update-list">
                <li>Sign in with Google</li>
                <li>Privacy Policy and Terms of Service, naming the legal entity and jurisdiction</li>
                <li>The dashboard warns before a Gmail connection dies, not after rate confirmations stop arriving</li>
                <li>A fleet status view, and app navigation separated from the marketing site</li>
              </ul>
            </div>

            <div className="update-card card">
              <div className="update-date">22-23 August 2026</div>
              <h3 className="update-title"><Map size={20} /> Monitoring and accounts</h3>
              <ul className="update-list">
                <li>A live fleet map on GPS Monitoring</li>
                <li>Self-service password reset, and dispatcher account management for owners</li>
                <li>Driver status, profile menus and profile pictures</li>
                <li>Registration is Gmail-first: nothing is created until the last step submits</li>
                <li>A new visual identity across the site</li>
              </ul>
            </div>

            <div className="update-card card">
              <div className="update-date">20-21 August 2026</div>
              <h3 className="update-title"><CreditCard size={20} /> Billing and dispatch</h3>
              <ul className="update-list">
                <li>Stripe billing - Free, Pro and Max, monthly or yearly, with a 7-day trial</li>
                <li>Add a driver from Settings and link their Telegram group with a one-time code</li>
                <li>Location alert rules you can set yourself, with a test mode for trying them without a live Samsara account</li>
                <li><code>/detention</code> for detention and layover pay, <code>/commands</code> for the full reference, and <code>/loadid</code> renamed to <code>/dispatch</code></li>
                <li>Appearance, chat font and reduced-motion preferences</li>
              </ul>
            </div>

            <div className="update-card card">
              <div className="update-date">19 August 2026</div>
              <h3 className="update-title"><Rocket size={20} /> First build</h3>
              <ul className="update-list">
                <li>The Telegram bot: rate confirmations pulled from Gmail, load details extracted with AI, load photos and BOLs checked, PODs forwarded</li>
                <li>Owner and dispatcher dashboards</li>
                <li>Sessions on httpOnly cookies with CSRF protection, rate limiting on auth, and bot protection on register and login</li>
                <li>Stored credentials encrypted at rest, and tenant isolation covered by regression tests</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </Layout>
  )
}
