import { motion } from 'motion/react'
import Header from './Header'
import Footer from './Footer'

interface LayoutProps {
  children: React.ReactNode
  transparentHeader?: boolean
  noFooter?: boolean
}

export default function Layout({ children, transparentHeader = false, noFooter = false }: LayoutProps) {
  return (
    <div className="layout">
      <Header transparent={transparentHeader} />
      <motion.main
        className="main-content"
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, ease: 'easeOut' }}
      >
        {children}
      </motion.main>
      {!noFooter && <Footer />}
    </div>
  )
}
