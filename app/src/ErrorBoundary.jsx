import React from 'react';
import { COLORS, FONT_SANS } from './constants';

/**
 * ErrorBoundary — Catches rendering errors in child components.
 *
 * Wraps each tab so a crash in one doesn't take down the entire dashboard.
 * Shows a recovery UI with the error message and a retry button.
 */
class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static isChunkError(error) {
    const msg = error?.message || '';
    return (
      msg.includes('Failed to fetch dynamically imported module') ||
      msg.includes('Loading chunk') ||
      msg.includes('Loading CSS chunk') ||
      msg.includes('Importing a module script failed')
    );
  }

  static getDerivedStateFromError(error) {
    // Chunk load errors mean the browser has a stale index.html referencing
    // asset hashes that no longer exist after a new deploy. Auto-reload once
    // to pick up the new index.html — don't show the error UI at all.
    if (ErrorBoundary.isChunkError(error)) {
      const reloadKey = 'chunkReloadAt';
      const last = parseInt(sessionStorage.getItem(reloadKey) || '0', 10);
      const now = Date.now();
      // Guard: only auto-reload once per 30s to avoid reload loops
      if (now - last > 30_000) {
        sessionStorage.setItem(reloadKey, String(now));
        window.location.reload();
        return { hasError: false, error: null };
      }
    }
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    if (ErrorBoundary.isChunkError(error)) {
      console.warn(`[ErrorBoundary] Chunk load error in "${this.props.label}" — reloading to pick up new deploy.`);
    } else {
      console.error(`[ErrorBoundary] ${this.props.label || 'Component'} crashed:`, error, errorInfo);
    }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div
          style={{
            background: COLORS.s1,
            borderRadius: 10,
            border: `1px solid ${COLORS.rd}33`,
            padding: '32px 24px',
            textAlign: 'center',
            fontFamily: FONT_SANS,
          }}
        >
          <div style={{ fontSize: 28, marginBottom: 12, opacity: 0.3 }}>⚠</div>
          <div style={{ fontSize: 14, fontWeight: 600, color: COLORS.t2, marginBottom: 8 }}>
            {this.props.label || 'This section'} encountered an error
          </div>
          <div style={{ fontSize: 11, color: COLORS.t3, marginBottom: 16, maxWidth: 480, margin: '0 auto 16px' }}>
            {this.state.error?.message || 'An unexpected error occurred while rendering this tab.'}
          </div>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            style={{
              background: COLORS.s2,
              border: `1px solid ${COLORS.bd}`,
              borderRadius: 6,
              padding: '8px 16px',
              fontSize: 11,
              color: COLORS.t2,
              cursor: 'pointer',
              fontFamily: FONT_SANS,
            }}
          >
            Try again
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
