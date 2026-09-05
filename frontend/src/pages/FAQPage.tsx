import { Lightbulb, CreditCard, Mail, Map, Bot, Users, Bell, MessagesSquare, ScanText, Image } from 'lucide-react'
import Layout from '../components/Layout'

/** The questions, grouped, and closed until asked for.
 *
 * These used to be seven always-open cards. That reads fine at seven and
 * badly at eleven: the answers are long, so the questions - the part
 * somebody is actually scanning for - end up a screen apart. Grouping them
 * and closing them puts every question in view at once, which is the whole
 * job of the page.
 *
 * Built on <details>, not a state hook, so it works with the keyboard and
 * with the browser's own find-in-page, and would still open without any
 * JavaScript at all. Each one carries an id so a specific answer can be
 * linked to directly - "see the billing question" is a link somebody in
 * support will want to send. */

type Question = {
  id: string
  icon: React.ReactNode
  question: string
  answer: React.ReactNode
}

type Section = {
  title: string
  questions: Question[]
}

const SECTIONS: Section[] = [
  {
    title: 'Getting started',
    questions: [
      {
        id: 'what-is-unector',
        icon: <Lightbulb size={18} />,
        question: 'What is Unector?',
        answer: (
          <p>
            Dispatch management for trucking companies, run through Telegram. It reads rate
            confirmations out of your inbox, posts each load to the driver&apos;s group, checks
            BOL and POD photos, watches GPS for arrivals, and keeps a dashboard for the office.
          </p>
        ),
      },
      {
        id: 'setting-up-a-group',
        icon: <MessagesSquare size={18} />,
        question: "How do I set up a truck's group?",
        answer: (
          <>
            <p>
              Add the bot to the group, then send the linking code from Settings &rarr; Drivers
              inside that group. Sending it there is what proves you are in it, which is why a
              group can&apos;t be claimed by typing its id anywhere.
            </p>
            <p>
              While you&apos;re in the group settings, make the bot an admin with{' '}
              <strong>Change group info</strong> and <strong>Pin messages</strong>. With those two
              it keeps the group&apos;s name, description and picture matching the confirmed
              record, and pins the load card everyone keeps scrolling back to. Without them
              nothing breaks - those writes are skipped, not retried.
            </p>
          </>
        ),
      },
      {
        id: 'group-description',
        icon: <ScanText size={18} />,
        question: 'The group description already has the truck and driver in it.',
        answer: (
          <>
            <p>
              Then the bot reads it. Most carriers keep the unit number, trailer, driver and phone
              numbers in there, and no two groups are laid out the same way - so it&apos;s read
              rather than parsed.
            </p>
            <p>
              What it found is shown for someone to confirm, from the group or from Settings,
              whichever comes first. Nothing reaches your records until a person says yes, every
              value is editable so a misread digit doesn&apos;t cost the whole reading, and
              anything that disagrees with what&apos;s on file is pointed out rather than applied
              quietly. <code>/readbio</code> reads it again after you edit it.
            </p>
            <p>
              Once it&apos;s confirmed the writing goes the other way, and the group ends up named
              after the unit and driver with the details in its description - in the same shape it
              was read from, so nothing is lost on the round trip.
            </p>
          </>
        ),
      },
      {
        id: 'company-logo',
        icon: <Image size={18} />,
        question: 'Which logo ends up on the group?',
        answer: (
          <p>
            The company&apos;s. The picture in Settings on the owner&apos;s login is your
            carrier&apos;s mark rather than a personal photo - there is one per company, however
            many people sign in as the owner - and it goes on each truck&apos;s group so a
            dispatcher scanning forty of them sees who they work for in every one. If you have
            never uploaded one and a group already has a picture, the bot takes that instead of
            asking. A dispatcher&apos;s own picture stays their own.
          </p>
        ),
      },
    ],
  },
  {
    title: 'Billing',
    questions: [
      {
        id: 'billing',
        icon: <CreditCard size={18} />,
        question: 'How does billing work?',
        answer: (
          <>
            <p>
              Free to look around. Pro is $20/mo (or $200/yr) for up to 5 active drivers. Max
              plans are $100/mo for up to 25 drivers, or $200/mo for up to 100 drivers.
            </p>
            <p>
              Every paid plan starts with a 7-day free trial. Starting one asks for a payment
              method - card, PayPal or a wallet - but nothing is charged while the trial runs. The
              plan then renews by itself: the price is charged on the day the trial ends and every
              period after, until you cancel from Settings. We email you two days before a trial
              ends, so the charge is never a surprise.
            </p>
            <p>
              Until that first payment goes through, your only payment method can&apos;t be
              removed - it is the only way the payment can be taken. Afterwards you can remove it
              whenever you like, and doing so ends the plan when the period you have paid for runs
              out.
            </p>
          </>
        ),
      },
    ],
  },
  {
    title: 'What it connects to',
    questions: [
      {
        id: 'gmail',
        icon: <Mail size={18} />,
        question: 'How does Gmail integration work?',
        answer: (
          <p>
            A secure OAuth 2.0 connection, authorised once by the owner from the dashboard. The
            bot then finds rate confirmations in that inbox by itself. If the connection ever
            lapses the dashboard says so - dispatch quietly stops working otherwise, which is why
            that particular warning can&apos;t be switched off.
          </p>
        ),
      },
      {
        id: 'gps',
        icon: <Map size={18} />,
        question: 'How does GPS tracking work?',
        answer: (
          <p>
            Through a Samsara integration. It checks each vehicle&apos;s position every couple of
            minutes and messages the driver&apos;s group as they get near pickup or delivery. You
            can set your own rules for when that fires - a heads-up at fifty miles out and again
            at five, say - or leave the built-in default alone.
          </p>
        ),
      },
      {
        id: 'ai',
        icon: <Bot size={18} />,
        question: 'What does the AI do?',
        answer: (
          <p>
            Google Gemini reads each rate confirmation and pulls out the load id, addresses,
            dates, broker, rate and the rest, so nobody retypes a PDF. It also reads a group
            description, which is the other place carriers keep details in no fixed format.
          </p>
        ),
      },
    ],
  },
  {
    title: 'Your team, and being told things',
    questions: [
      {
        id: 'dispatchers',
        icon: <Users size={18} />,
        question: 'How many dispatchers can I have?',
        answer: (
          <p>
            Each dispatcher gets their own dashboard login. Free includes one, Pro three, and Max
            5x ten; Max 20x has no limit. Changing plan never removes a login you already have -
            going over the allowance only stops you adding another. Adding or removing one is
            emailed to the owner as well as shown in the dashboard, because it changes who can get
            in.
          </p>
        ),
      },
      {
        id: 'notifications',
        icon: <Bell size={18} />,
        question: 'How do notifications work?',
        answer: (
          <>
            <p>
              Three places: a bell in the dashboard, a Telegram message, and email. Settings &rarr;
              Notifications is where you choose which of them each kind of news reaches you on, and
              an owner and a dispatcher each set their own.
            </p>
            <p>
              The dashboard list always gets everything - email can bounce and Telegram won&apos;t
              message anyone who hasn&apos;t started a chat with the bot, so the bell is the one
              place nothing goes missing. Most things arrive there and nowhere else unless you ask,
              because a message per edit is the fastest way to learn to ignore us.
            </p>
            <p>
              A few stay on whatever you choose: a failed payment, a sign-in you didn&apos;t make,
              an integration that stopped working. Those are shown as locked rather than hidden, so
              you can always see what will reach you.
            </p>
          </>
        ),
      },
    ],
  },
]

export default function FAQPage() {
  return (
    <Layout>
      <div className="page-container">
        <div className="container">
          <div className="page-header">
            <h1 className="page-title">Frequently Asked Questions</h1>
            <p className="page-description">
              Everything you need to know about Unector. Open a question to read the answer.
            </p>
          </div>

          <div className="faq-sections">
            {SECTIONS.map((section) => (
              <section className="faq-section" key={section.title}>
                <h2 className="faq-section-title">{section.title}</h2>
                <div className="faq-list">
                  {section.questions.map((item) => (
                    <details className="faq-item card" id={item.id} key={item.id}>
                      <summary className="faq-question">
                        {item.icon}
                        <span>{item.question}</span>
                      </summary>
                      <div className="faq-answer">{item.answer}</div>
                    </details>
                  ))}
                </div>
              </section>
            ))}
          </div>
        </div>
      </div>
    </Layout>
  )
}
