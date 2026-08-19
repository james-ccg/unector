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
                <li>Enhanced AI accuracy with GPT-4 integration</li>
                <li>Mobile-responsive design for all pages</li>
                <li>Real-time notifications via WebSocket</li>
              </ul>
            </div>

            <div className="update-card card">
              <div className="update-date">December 2025</div>
              <h3 className="update-title"><BarChart3 size={20} /> Advanced Analytics</h3>
              <ul className="update-list">
                <li>Weekly and monthly earnings reports</li>
                <li>Driver performance metrics</li>
                <li>Load profitability analysis</li>
                <li>Export to CSV/PDF</li>
              </ul>
            </div>

            <div className="update-card card">
              <div className="update-date">November 2025</div>
              <h3 className="update-title"><Link2 size={20} /> Samsara Integration</h3>
              <ul className="update-list">
                <li>Real-time GPS tracking</li>
                <li>Geofencing alerts</li>
                <li>ETA calculations</li>
                <li>Driver proximity notifications</li>
              </ul>
            </div>

            <div className="update-card card">
              <div className="update-date">October 2025</div>
              <h3 className="update-title"><Bot size={20} /> AI Load Extraction</h3>
              <ul className="update-list">
                <li>Google Gemini AI integration</li>
                <li>Automatic rate confirmation parsing</li>
                <li>99%+ accuracy on load details</li>
                <li>Support for 50+ broker formats</li>
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
