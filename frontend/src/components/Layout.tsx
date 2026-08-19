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
      <main className="main-content">{children}</main>
      {!noFooter && <Footer />}
    </div>
  )
}
