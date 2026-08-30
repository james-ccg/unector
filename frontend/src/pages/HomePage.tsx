import { motion, type Variants } from 'motion/react'
import { Zap, Bot, Mail, Map, Smartphone, BarChart3, Users, type LucideIcon } from 'lucide-react'
import Layout from '../components/Layout'
import TelegramPreview from '../components/TelegramPreview'
import './HomePage.css'

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
    description: 'Add unlimited dispatchers - each with their own secure login',
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
              with brokers. Freight Pilot brings intelligence to your dispatch operations through
              Telegram.
            </p>
            <div className="hero-buttons">
              <motion.a
                href="/register"
                className="btn-primary btn-lg"
                whileHover={{ y: -2 }}
                whileTap={{ y: 0 }}
              >
                <span>Start Free Trial</span>
                <span>→</span>
              </motion.a>
              <motion.a
                href="#features"
                className="btn-secondary btn-lg"
                whileHover={{ y: -2 }}
                whileTap={{ y: 0 }}
              >
                <span>See Features</span>
              </motion.a>
            </div>
          </motion.div>
          <TelegramPreview />
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
