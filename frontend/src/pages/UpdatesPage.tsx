import { Newspaper, Construction, Palette, Gamepad2, ShieldCheck, Map, CreditCard, Rocket, UserRound } from 'lucide-react'
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
                <li>
                  Signing out does not yet revoke a session server-side. The cookie goes, but a
                  token captured beforehand stays valid until it expires.
                </li>
              </ul>
            </div>

            <div className="update-card card">
              <div className="update-date">3 September 2026</div>
              <h3 className="update-title"><UserRound size={20} /> The truck&apos;s group already knows who is driving it</h3>
              <ul className="update-list">
                <li>
                  Carriers run one Telegram group per truck and keep the unit number, trailer,
                  driver and phone numbers in its description. Link the group and the bot reads
                  that, then shows what it found for someone to confirm.
                </li>
                <li>
                  Nothing is saved until a person says so - from the group or from Settings,
                  whichever comes first. Every value is editable, so a misread digit is corrected
                  rather than costing the whole reading.
                </li>
                <li>
                  The description it was read from is shown alongside the values, and anything
                  that disagrees with your records is said plainly instead of being applied quietly.
                </li>
                <li>
                  /readbio re-reads a description after you edit it. Details can also be typed in
                  by hand, for groups whose description says nothing useful.
                </li>
                <li>
                  Every app email was going out with an empty From header, because the address was
                  set to an empty value rather than left unset. Fixed.
                </li>
              </ul>
            </div>

            <div className="update-card card">
              <div className="update-date">2 September 2026</div>
              <h3 className="update-title"><ShieldCheck size={20} /> Security, and how errors read</h3>
              <ul className="update-list">
                <li>
                  A token issued for one job could be used as a login session. The 2FA handshake
                  token is handed back before any second factor, so knowing a password was enough
                  to get in. Every token now says what it is for, and the check is enforced.
                </li>
                <li>CSRF tokens are now tied to your session, so writing a cookie is no longer enough to forge one</li>
                <li>Every error names itself - the status code, the failure kind - instead of &ldquo;something went wrong&rdquo;</li>
                <li>Error wording rewritten against the published guidance: say what happened, say what to do, don&apos;t blame the reader</li>
                <li>Live GPS was returning a server error on every visit and never loaded; the fleet map no longer needs a map-provider key</li>
                <li>Continuous integration, dependency auditing and secret scanning on every push</li>
              </ul>
            </div>

            <div className="update-card card">
              <div className="update-date">2 September 2026</div>
              <h3 className="update-title"><UserRound size={20} /> Profile and status</h3>
              <ul className="update-list">
                <li>Profile pictures are cropped by you, not centre-cropped by us - drag, zoom, pinch on a phone</li>
                <li>Status has one-click presets for the statuses a driver&apos;s day is actually made of, and tells you when it will clear</li>
                <li>The dashboard&apos;s &ldquo;Reconnect it in Settings&rdquo; now lands on the button itself rather than the top of the page</li>
                <li>Truck and trailer numbers no longer break across two lines on a driver card</li>
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
