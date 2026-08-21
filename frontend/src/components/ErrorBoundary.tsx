import { Component, type ErrorInfo, type ReactNode } from 'react'
import Icon from './Icon'
import './ErrorBoundary.css'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
}

// The only class component in this codebase - React has no hook
// equivalent for catching render errors in a subtree (getDerivedStateFromError/
// componentDidCatch are class-only APIs). Without this, any uncaught error
// anywhere in the tree (a malformed API response, an unexpected null, ...)
// unmounts the whole app to a blank white screen with no way back short of
// a manual refresh - wrapping the router in this keeps that failure
// contained to a friendly screen with an actual way to recover.
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false }

  static getDerivedStateFromError(): State {
    return { hasError: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Uncaught render error:', error, info.componentStack)
  }

  render() {
    if (!this.state.hasError) return this.props.children

    return (
      <div className="error-boundary">
        <div className="error-boundary-card">
          <Icon name="warning" size={32} />
          <h1>Something went wrong</h1>
          <p>An unexpected error occurred. Reloading usually fixes it.</p>
          <button className="error-boundary-btn" onClick={() => window.location.reload()}>
            Reload page
          </button>
        </div>
      </div>
    )
  }
}
