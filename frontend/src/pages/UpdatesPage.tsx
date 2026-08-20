import { Newspaper, Rocket, BarChart3, Link2, Bot, PartyPopper } from 'lucide-react'
import Layout from '../components/Layout'

export default function UpdatesPage() {
  return (
    <Layout>
      <div className="page-container">
        <div className="container">
          <div className="page-header">
            <h1 className="page-title"><Newspaper size={36} /> Product Updates</h1>
            <p className="page-description">Latest features and improvements</p>
          </div>

          <div className="updates-timeline">
            <div className="update-card card">
              <div className="update-date">January 2026</div>
              <h3 className="update-title"><Rocket size={20} /> v2.0 Release</h3>
              <ul className="update-list">
                <li>New React + TypeScript dashboard with improved performance</li>
                <li>Data visualizations on the dashboard for weekly earnings and fleet status</li>
                <li>Smooth page-transition animations and a refreshed icon set across the site</li>
                <li>Mobile-responsive design for all pages</li>
              </ul>
            </div>

            <div className="update-card card">
              <div className="update-date">December 2025</div>
              <h3 className="update-title"><BarChart3 size={20} /> Analytics</h3>
              <ul className="update-list">
                <li>Weekly gross earnings by driver, visualized on the dashboard</li>
                <li>Fleet status overview - active vs. total drivers</li>
              </ul>
            </div>

            <div className="update-card card">
              <div className="update-date">November 2025</div>
              <h3 className="update-title"><Link2 size={20} /> Samsara Integration</h3>
              <ul className="update-list">
                <li>Link a driver's Telegram group to a Samsara vehicle with /setvehicle</li>
                <li>GPS location checked automatically every couple of minutes</li>
                <li>Automatic Telegram alert when a driver nears pickup or delivery</li>
              </ul>
            </div>

            <div className="update-card card">
              <div className="update-date">October 2025</div>
              <h3 className="update-title"><Bot size={20} /> AI Load Extraction</h3>
              <ul className="update-list">
                <li>Google Gemini AI integration</li>
                <li>Automatic rate confirmation parsing</li>
                <li>Extracts load ID, addresses, dates, broker, and rate automatically</li>
              </ul>
            </div>

            <div className="update-card card">
              <div className="update-date">September 2025</div>
              <h3 className="update-title"><PartyPopper size={20} /> Initial Launch</h3>
              <ul className="update-list">
                <li>Telegram bot for drivers</li>
                <li>Gmail integration via OAuth 2.0</li>
                <li>Owner and dispatcher dashboards</li>
                <li>Load management system</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </Layout>
  )
}
