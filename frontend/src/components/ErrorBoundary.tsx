import { Component, type ErrorInfo, type ReactNode } from 'react'
import Icon from './Icon'
import './ErrorBoundary.css'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  /** What actually failed, so the screen can say so. */
  error: Error | null
}

// The only class component in this codebase - React has no hook
// equivalent for catching render errors in a subtree (getDerivedStateFromError/
// componentDidCatch are class-only APIs). Without this, any uncaught error
// anywhere in the tree (a malformed API response, an unexpected null, ...)
// unmounts the whole app to a blank white screen with no way back short of
// a manual refresh - wrapping the router in this keeps that failure
// contained to a friendly screen with an actual way to recover.
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Uncaught render error:', error, info.componentStack)
  }

  render() {
    if (!this.state.hasError) return this.props.children

    // "Something went wrong" on its own is not reportable: it reads the same
    // for a dropped connection, a bad API response and a genuine bug, so
    // nobody who sees it can say which one they saw. The name and message go
    // on the screen next to the reload button.
    const { error } = this.state
    const label = error ? `${error.name}: ${error.message}` : null

    return (
      <div className="error-boundary">
        <div className="error-boundary-card">
          <Icon name="warning" size={32} />
          <h1>This page stopped working</h1>
          <p>Reloading usually fixes it. If it keeps happening, the detail below is worth reporting.</p>
          {label && <p className="error-boundary-detail">{label}</p>}
          <button className="error-boundary-btn" onClick={() => window.location.reload()}>
            Reload page
          </button>
        </div>
      </div>
    )
  }
}
