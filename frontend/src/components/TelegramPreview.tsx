import { motion } from 'motion/react'
import './TelegramPreview.css'

/** The product, shown rather than described.
 *
 * Everything below mirrors what bot.py actually posts: the emoji, the
 * PU:1 / DEL:1 numbering, the monospaced address block, the "Date/Time"
 * labels and the standing policy notes all come from format_load_template
 * and MANDATORY_NOTES. It's a real example of the output, not an invented
 * mock-up - the point of the hero is to let someone recognise the thing
 * they'd actually get in their dispatch group. */
export default function TelegramPreview() {
  return (
    <motion.div
      className="tg-preview"
      initial={{ opacity: 0, y: 24 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6, delay: 0.15, ease: 'easeOut' }}
      aria-label="Example of the load details Unector posts to a driver's Telegram group"
    >
      <div className="tg-window">
        <div className="tg-titlebar">
          <span className="tg-avatar" aria-hidden="true">UN</span>
          <div className="tg-titlebar-text">
            <strong>Unit 3001</strong>
            <span>driver, dispatcher, bot</span>
          </div>
        </div>

        <div className="tg-thread">
          <motion.div
            className="tg-msg tg-msg-out"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, delay: 0.5 }}
          >
            <code>/dispatch 4471</code>
          </motion.div>

          <motion.div
            className="tg-msg tg-msg-in"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: 1.0 }}
          >
            <p className="tg-line"><b>📌 Broker: TQL</b></p>
            <p className="tg-line"><b>LOAD#:</b> 4471</p>

            <p className="tg-line tg-stop"><b>🟢 PU:1</b></p>
            <pre className="tg-address">Tyson Foods{'\n'}2200 W Don Tyson Pkwy{'\n'}Springdale, AR 72762</pre>
            <p className="tg-line"><b>📅 Date:</b> 08/29/2026 &nbsp;<b>🕔 Time:</b> 15:00 Apt</p>

            <blockquote className="tg-quote">
              <b>⚖️ Weight: 42,000</b>
              <br />
              <b>📤 Commodity:</b> Frozen poultry
              <br />
              TEMP#: -10F
              <br />
              PU#: 8841203
            </blockquote>

            <p className="tg-line tg-stop"><b>🔴 DEL:1</b></p>
            <pre className="tg-address">Kroger DC{'\n'}1500 Grand Ave{'\n'}Dallas, TX 75215</pre>
            <p className="tg-line"><b>📅 Date:</b> 08/31/2026 &nbsp;<b>🕔 Time:</b> By 08:00</p>

            <p className="tg-line tg-notes">
              <b>USE STRAPS AND LOADBARS TO SECURE THE LOAD</b>
            </p>
          </motion.div>

          <motion.div
            className="tg-msg tg-msg-in tg-msg-alert"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: 1.6 }}
          >
            <p className="tg-line">📍 The truck is 5 miles from pickup.</p>
          </motion.div>
        </div>
      </div>
    </motion.div>
  )
}
