import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { useToastStore, type Toast as ToastData } from "@/stores/toast_store";

const accentColors: Record<ToastData["type"], string> = {
  success: "var(--color-success)",
  error: "var(--color-danger)",
  info: "var(--brand-primary)",
};

const containerStyle: React.CSSProperties = {
  position: "fixed",
  bottom: 24,
  right: 24,
  zIndex: 9999,
  display: "flex",
  flexDirection: "column",
  gap: 10,
  pointerEvents: "none",
};

const toastBaseStyle: React.CSSProperties = {
  pointerEvents: "auto",
  display: "flex",
  alignItems: "center",
  gap: 12,
  minWidth: 260,
  maxWidth: 380,
  padding: "12px 14px",
  borderRadius: 16,
  background: "linear-gradient(180deg, rgba(22, 33, 62, 0.92) 0%, rgba(12, 20, 42, 0.88) 100%)",
  border: "1px solid rgba(139, 92, 246, 0.12)",
  boxShadow:
    "0 20px 50px rgba(15, 23, 42, 0.5), 0 0 0 1px rgba(139, 92, 246, 0.06), inset 0 1px 0 rgba(255, 255, 255, 0.04)",
  backdropFilter: "blur(14px)",
  color: "rgba(248, 250, 252, 0.92)",
  fontSize: 13,
  fontWeight: 600,
  lineHeight: 1.4,
  transition: "opacity 250ms ease, transform 250ms ease",
};

const closeBtnStyle: React.CSSProperties = {
  marginLeft: "auto",
  flexShrink: 0,
  width: 22,
  height: 22,
  borderRadius: 8,
  border: "none",
  background: "rgba(255, 255, 255, 0.08)",
  color: "rgba(226, 232, 240, 0.6)",
  fontSize: 14,
  lineHeight: 1,
  cursor: "pointer",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  padding: 0,
};

function ToastItem({ toast, onRemove }: { toast: ToastData; onRemove: () => void }) {
  const [visible, setVisible] = useState(false);
  const mountedRef = useRef(true);

  useEffect(() => {
    // Trigger enter animation on next frame
    const raf = requestAnimationFrame(() => {
      if (mountedRef.current) setVisible(true);
    });
    return () => {
      mountedRef.current = false;
      cancelAnimationFrame(raf);
    };
  }, []);

  const accent = accentColors[toast.type];

  return (
    <div
      style={{
        ...toastBaseStyle,
        borderLeft: `3px solid ${accent}`,
        opacity: visible ? 1 : 0,
        transform: visible ? "translateX(0)" : "translateX(40px)",
      }}
    >
      <span style={{ flex: 1, minWidth: 0 }}>{toast.message}</span>
      <button style={closeBtnStyle} onClick={onRemove} aria-label="Dismiss">
        &times;
      </button>
    </div>
  );
}

export default function Toast() {
  const toasts = useToastStore((s) => s.toasts);
  const removeToast = useToastStore((s) => s.removeToast);

  if (toasts.length === 0) return null;

  return createPortal(
    <div style={containerStyle}>
      {toasts.map((toast) => (
        <ToastItem key={toast.id} toast={toast} onRemove={() => removeToast(toast.id)} />
      ))}
    </div>,
    document.body,
  );
}
