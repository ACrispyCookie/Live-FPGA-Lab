// Toasts are for the unexpected only (server messages, reconnects); the normal flow never relies on them.
import type { Toast } from '../lab/types.ts';

export function Toasts({ toasts, onDismiss }: { toasts: Toast[]; onDismiss: (id: string) => void }) {
  if (!toasts.length) return null;
  return (
    <div className="toast-stack" role="status" aria-live="polite">
      {toasts.map((toast) => (
        <button key={toast.id} type="button" className={`toast toast-${toast.level}`} onClick={() => onDismiss(toast.id)} title="Dismiss">
          <span className="toast-dot" />
          <span>{toast.message}</span>
        </button>
      ))}
    </div>
  );
}
