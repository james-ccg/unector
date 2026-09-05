import { Link } from 'react-router-dom'
import { motion, type Variants } from 'motion/react'
import { Zap, Bot, Mail, Map, Smartphone, BarChart3, Users, type LucideIcon } from 'lucide-react'
import Layout from '../components/Layout'
import TelegramPreview from '../components/TelegramPreview'
import './HomePage.css'

/** The actual command sequence from bot.py, not an idealised version of it.
 *  A dispatcher evaluating this needs to recognise their own working day in
 *  it - a vague "AI automates your workflow" tells them nothing they can
 *  check. Numbered because these genuinely happen in this order: each step
 *  depends on the load record the previous one created. */
const STEPS: { command: string; title: string; description: string }[] = [
  {
    command: '/dispatch 4471',
    title: 'The load lands in the group',
    description:
      'Unector finds that rate confirmation in your connected inbox, reads the PDF, and posts the pickup, delivery, times, rate and notes into the driver’s Telegram group — formatted the same way every time.',
  },
  {
    command: '/loadpics',
    title: 'The driver proves the load is right',
    description:
      'Photos of the freight, the seal and the reefer display come back checked: securement, seal number against the BOL, and temperature against what the rate confirmation asked for.',
  },
  {
    command: '/bol',
    title: 'The paperwork gets checked before it’s a problem',
    description:
      'The Bill of Lading is compared against the rate confirmation — weight, delivery address, seal — so a mismatch surfaces at the dock instead of at invoicing.',
  },
  {
    command: '/pod',
    title: 'The broker gets the POD',
    description:
      'Proof of delivery goes straight from the driver’s phone to the broker’s inbox, sent from your own connected Gmail. No forwarding, no chasing.',
  },
]

const FEATURES: { icon: LucideIcon; title: string; description: string }[] = [
  {
    icon: Bot,
    title: 'AI Load Extraction',
    description: 'Google Gemini AI automatically extracts load details from rate confirmations',
  },
  {
    icon: Mail,
    title: 'Gmail Integration',
    description: 'Connect your Gmail via OAuth 2.0 - bot monitors and processes emails automatically',
  },
  {
    icon: Map,
    title: 'GPS Tracking',
    description: 'Samsara integration with real-time location tracking and auto-notifications',
  },
  {
    icon: Smartphone,
    title: 'Telegram Bot',
    description: 'Drivers get loads via Telegram - simple, familiar, and always accessible',
  },
  {
    icon: BarChart3,
    title: 'Smart Dashboard',
    description: 'Track drivers, loads, and earnings in real-time from any device',
  },
  {
    icon: Users,
    title: 'Multi-Dispatcher',
    description: 'Give each dispatcher their own secure login - up to 10 on Max, unlimited on Max 20x',
  },
]

const cardVariants: Variants = {
  hidden: { opacity: 0, y: 24 },
  visible: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { delay: i * 0.08, duration: 0.45, ease: 'easeOut' },
  }),
}

export default function HomePage() {
  return (
    <Layout transparentHeader>
      <section className="hero">
        <div className="hero-container container">
          <motion.div
            className="hero-content"
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, ease: 'easeOut' }}
          >
            <div className="hero-badge">
              <Zap size={16} />
              <span>AI-Powered Dispatch Automation</span>
            </div>
            <h1 className="hero-title">
              Smart Dispatch Management for
              <span className="gradient-text"> Modern Trucking</span>
            </h1>
            <p className="hero-description">
              Automate load management, track drivers in real-time, and streamline communication
              with brokers. Unector brings intelligence to your dispatch operations through
              Telegram.
            </p>
            {/* Router links, not <a href>: a plain anchor to /register tore
                down the SPA and re-downloaded the whole bundle on the primary
                CTA. The lift on hover is already in .btn-primary's CSS, so
                there's nothing for motion to add here. */}
            <div className="hero-buttons">
              <Link to="/register" className="btn-primary btn-lg">
                <span>Start Free Trial</span>
                <span>→</span>
              </Link>
              <Link to="/#how-it-works" className="btn-secondary btn-lg">
                <span>See how it works</span>
              </Link>
            </div>
          </motion.div>
          <TelegramPreview />
        </div>
      </section>

      <section className="steps-section" id="how-it-works">
        <div className="container">
          <div className="section-header">
            <h2 className="section-title">One load, start to finish</h2>
            <p className="section-description">
              Four commands in the driver&apos;s Telegram group. That&apos;s the whole job.
            </p>
          </div>
          <ol className="steps-list">
            {STEPS.map((step, i) => (
              <motion.li
                key={step.command}
                className="step-item"
                custom={i}
                initial="hidden"
                whileInView="visible"
                viewport={{ once: true, amount: 0.4 }}
                variants={cardVariants}
              >
                <div className="step-marker" aria-hidden="true">
                  <span className="step-number">{i + 1}</span>
                </div>
                <div className="step-body">
                  <code className="step-command">{step.command}</code>
                  <h3 className="step-title">{step.title}</h3>
                  <p className="step-description">{step.description}</p>
                </div>
              </motion.li>
            ))}
          </ol>
        </div>
      </section>

      <section className="features-section" id="features">
        <div className="container">
          <div className="section-header">
            <h2 className="section-title">Everything You Need to Run Your Fleet</h2>
            <p className="section-description">
              Powerful features designed for modern trucking operations
            </p>
          </div>
          <div className="features-grid">
            {FEATURES.map((feature, i) => (
              <motion.div
                key={feature.title}
                className="feature-card"
                custom={i}
                initial="hidden"
                whileInView="visible"
                viewport={{ once: true, amount: 0.3 }}
                variants={cardVariants}
                whileHover={{ y: -8 }}
              >
                <div className="feature-icon">
                  <feature.icon size={28} />
                </div>
                <h3 className="feature-title">{feature.title}</h3>
                <p className="feature-description">{feature.description}</p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>
    </Layout>
  )
}
