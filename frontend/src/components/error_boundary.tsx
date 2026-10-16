import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("ErrorBoundary caught:", error, info.componentStack);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            height: "100vh",
            background: "var(--bg-primary, #0f172a)",
            color: "var(--text-primary, #e2e8f0)",
            fontFamily: "system-ui, -apple-system, sans-serif",
            padding: 32,
            textAlign: "center",
          }}
        >
          <div
            style={{
              maxWidth: 480,
              padding: 40,
              borderRadius: 24,
              background: "rgba(30, 41, 59, 0.8)",
              border: "1px solid rgba(139, 92, 246, 0.15)",
              boxShadow: "0 25px 50px rgba(0, 0, 0, 0.25)",
            }}
          >
            <div style={{ fontSize: 48, marginBottom: 16 }}>Something went wrong</div>
            <p
              style={{
                fontSize: 15,
                color: "rgba(203, 213, 225, 0.7)",
                lineHeight: 1.6,
                margin: "0 0 24px",
              }}
            >
              An unexpected error occurred while rendering the application.
              {this.state.error && (
                <span
                  style={{
                    display: "block",
                    marginTop: 12,
                    padding: "8px 12px",
                    borderRadius: 8,
                    background: "rgba(239, 68, 68, 0.1)",
                    border: "1px solid rgba(239, 68, 68, 0.2)",
                    fontSize: 13,
                    fontFamily: "monospace",
                    wordBreak: "break-word",
                  }}
                >
                  {this.state.error.message}
                </span>
              )}
            </p>
            <button
              onClick={this.handleReset}
              style={{
                padding: "12px 32px",
                borderRadius: 12,
                border: "none",
                background: "linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%)",
                color: "#fff",
                fontSize: 15,
                fontWeight: 600,
                cursor: "pointer",
                boxShadow: "0 8px 20px rgba(37, 99, 235, 0.3)",
              }}
            >
              Try again
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
