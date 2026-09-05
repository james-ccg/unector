import {
  Newspaper, Construction, Palette, Gamepad2, ShieldCheck, Map, CreditCard, Rocket,
  UserRound, Bell, MessagesSquare, Tag, Link2, Receipt, Pin as PinIcon,
} from 'lucide-react'
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
              Unector&apos;s first build was 19 August 2026. Everything below has shipped
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
              <div className="update-date">5 September 2026</div>
              <h3 className="update-title"><Receipt size={20} /> One plan, and a record of who bought it</h3>
              <ul className="update-list">
                <li>
                  The plan has always belonged to the company rather than to a person - whoever
                  pays for it puts everyone on it - but nothing recorded which login actually did.
                  Settings now says who bought the current plan and when, above a history of what
                  has been charged.
                </li>
                <li>
                  A renewal Stripe collects by itself is listed with no name against it, because
                  nobody clicked anything. Crediting it to whoever last touched the account would
                  be worse than saying nothing.
                </li>
                <li>
                  The name is kept as it was at the time, so a dispatcher who paid in March and
                  left in June still shows as having paid in March.
                </li>
                <li>
                  Billing news now reaches every dispatcher and not only the owner. One who arrives
                  to find the account paused shouldn&apos;t have to work that out from the driver
                  cap, and the person who can fix a failed payment may not be the owner. They could
                  already see the plan and start a checkout, so nothing new is on show.
                </li>
                <li>
                  The bot&apos;s <code>/faq</code> had grown past what Telegram will accept in one
                  message - which is refused outright rather than truncated, so the command would
                  simply have stopped answering. It now carries what you would ask from inside
                  Telegram - what this is, how to set up a truck&apos;s group, what it costs and
                  who pays - and links to the full FAQ on the site for the rest.
                </li>
              </ul>
            </div>

            <div className="update-card card">
              <div className="update-date">5 September 2026</div>
              <h3 className="update-title"><MessagesSquare size={20} /> A truck&apos;s group is something you manage</h3>
              <ul className="update-list">
                <li>
                  Confirming a reading now renames the group as well as rewriting its description.
                  The unit number leads, because that is what you scan a crowded chat list for and
                  the half that survives when Telegram truncates. The trailer stays out - it
                  changes week to week, and a name that has to be rewritten every time it does is
                  a name that ends up wrong.
                </li>
                <li>
                  Your logo goes on each truck&apos;s group, so a dispatcher looking at forty of
                  them sees who they work for in every one. It reads the other way too: if you
                  have never uploaded one and a group already has a picture, that becomes the
                  company logo instead of us asking. It only ever fills a gap - a mark you chose
                  yourself is never overwritten.
                </li>
                <li>
                  The picture in Settings was labelled &ldquo;profile picture&rdquo; on the
                  owner&apos;s login and never was one - it is stored against the company, one per
                  carrier. It now says <strong>Company logo</strong> and says where it ends up. A
                  dispatcher&apos;s stays personal.
                </li>
                <li>
                  Settings can move a group between drivers, or unlink one - the case that matters
                  most when a truck is sold on a Sunday and nobody can get into the group to run a
                  command. What it deliberately cannot do is claim a group by typing an id:
                  sending the code inside a group is what proves you are in it.
                </li>
                <li>
                  Six new kinds of news cover what was never announced before - the bot&apos;s own
                  writes to a group, edits to truck and driver details, the fleet list, settings
                  and integrations, who is on the team, and payment methods. Almost all of them
                  arrive in the dashboard and nowhere else unless you ask for more.
                </li>
                <li>
                  Dispatcher logins now have a per-plan allowance: one on Free, three on Pro, ten
                  on Max 5x, and no limit on Max 20x. The pricing page had been calling them
                  unlimited on one plan and saying nothing on the others while the code capped
                  none of them. Changing plan never removes a login you already have - going over
                  the allowance only stops you adding another.
                </li>
              </ul>
            </div>

            <div className="update-card card">
              <div className="update-date">4 September 2026</div>
              <h3 className="update-title"><Tag size={20} /> A new name</h3>
              <ul className="update-list">
                <li>
                  The product is called <strong>Unector</strong>. The old name turned out to be in
                  use by other companies, and a trademark argument is not a thing to spend a first
                  year on.
                </li>
                <li>
                  It is built from <em>unus</em>, one, and <em>rector</em>, one who steers - which
                  is what the product does with a load. Being invented rather than assembled out
                  of freight words, it also sits somewhere nobody else is standing.
                </li>
                <li>
                  Everything moved with it: the site, the bot, the Telegram channel and group, the
                  repository, and the address our email comes from.
                </li>
              </ul>
            </div>

            <div className="update-card card">
              <div className="update-date">4 September 2026</div>
              <h3 className="update-title"><PinIcon size={20} /> What the bot writes back</h3>
              <ul className="update-list">
                <li>
                  Once a reading is confirmed, the group&apos;s description is rewritten from it,
                  so the two stop disagreeing. It goes back in the shape carriers already use,
                  which means <code>/readbio</code> can still read it afterwards without the round
                  trip losing anything.
                </li>
                <li>
                  The load card is pinned in the driver&apos;s group and the one it replaces is
                  unpinned. Exactly one load stays pinned: a stack of finished jobs is worse than
                  no pin at all, because then the driver has to work out which is today&apos;s.
                </li>
                <li>
                  Both need the bot to be an admin with <strong>Change group info</strong> and{' '}
                  <strong>Pin messages</strong>. Without them the writes are skipped and the load
                  still lands - nothing about dispatch depends on it.
                </li>
                <li>
                  A public endpoint was totalling every load&apos;s rate and serving the figure to
                  anyone, signed in or not. Counts stay anonymous however few carriers are signed
                  up; a sum of money does not. It has been removed - and no page was drawing it.
                </li>
                <li>
                  <code>/commands</code> was missing <code>/readbio</code>, so the only people who
                  found it were the ones who already knew. The three places a command is written
                  down are now checked against each other.
                </li>
              </ul>
            </div>

            <div className="update-card card">
              <div className="update-date">4 September 2026</div>
              <h3 className="update-title"><Bell size={20} /> Being told, and choosing how</h3>
              <ul className="update-list">
                <li>
                  A bell in the header with everything the app has told you, and a screen in
                  Settings for choosing what reaches you by Telegram or email as well.
                </li>
                <li>
                  The dashboard list always gets everything. Email can bounce and Telegram
                  won&apos;t let a bot message anyone who hasn&apos;t started a chat with it
                  first, so the bell is the one place nothing goes missing - which is also why
                  it&apos;s the one channel with nothing to configure.
                </li>
                <li>
                  Anything with money or account access attached stays on: a failed payment, a
                  sign-in you didn&apos;t make, an integration that quietly stopped working.
                  Those are shown in Settings as locked rather than hidden, so you can see what
                  will reach you even where you can&apos;t change it.
                </li>
                <li>
                  The bot has been telling drivers &ldquo;your dispatcher has been
                  notified&rdquo; when detention is requested. Until now nothing was.
                </li>
                <li>
                  All eleven kinds of news are now wired: loads dispatched and moved along,
                  drivers and groups, billing, and account security. The sign-in notice only
                  fires for an address you haven&apos;t signed in from before - one that went off
                  every time you logged in would just teach you to ignore it.
                </li>
              </ul>
            </div>

            <div className="update-card card">
              <div className="update-date">3 September 2026</div>
              <h3 className="update-title"><CreditCard size={20} /> What a trial costs, said out loud</h3>
              <ul className="update-list">
                <li>
                  Starting a paid plan now asks for a payment method up front - card, PayPal or a
                  wallet - so the plan can carry on by itself when the trial ends. Nothing is
                  charged while the trial runs.
                </li>
                <li>
                  A trial that ends in a charge is now spelled out wherever the trial is
                  mentioned: that it renews by itself, the exact date, the exact amount, and how
                  to cancel. On the pricing page that sits in ordinary text above the fold rather
                  than a grey footnote.
                </li>
                <li>
                  You now get an email two days before a trial ends, saying what will happen and
                  how to stop it. If there is no card on file it says that too - nothing is
                  charged, the account simply pauses.
                </li>
                <li>
                  Until the first payment for a plan has actually gone through, your only payment
                  method can&apos;t be removed - it is the only way that payment can be taken. The
                  Remove button says so before you press it instead of failing afterwards.
                </li>
                <li>
                  After that first payment, remove it whenever you like. Taking off your only
                  payment method now ends the plan when the period you already paid for runs out:
                  you keep everything until then and nothing is charged again, instead of a failed
                  renewal dropping the account into a run of dunning emails.
                </li>
              </ul>
            </div>

            <div className="update-card card">
              <div className="update-date">3 September 2026</div>
              <h3 className="update-title"><Link2 size={20} /> What a shared link looks like</h3>
              <ul className="update-list">
                <li>
                  Pasting a link to the site into Telegram, Slack or a message showed the host
                  name and a thumbnail. It now shows the product, a description and a full-width
                  card - the crawlers that build those previews never run JavaScript, so the tags
                  have to be in the HTML that arrives, resolved against whichever address the
                  request came in on.
                </li>
                <li>
                  Safari and iOS never got a usable icon: they ignore the SVG one, and iOS puts a
                  transparent background on black. Both now have their own, and the tab icon
                  follows your system theme where the browser supports it.
                </li>
                <li>
                  The site is installable, with an icon that survives being cropped into whatever
                  shape a phone uses.
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
