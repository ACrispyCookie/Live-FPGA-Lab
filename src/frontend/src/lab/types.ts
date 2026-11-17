// The lab's state as the browser sees it: what the server sends over /api/ws, plus a few local facts
// (what the visitor just asked for, the temperature history, toasts).

export type Board = {
  device_id?: string | null;
  device_name?: string | null;
  label?: string | null;
  status?: string | null;
  mode?: string | null;
  reserved_for?: string | null;
  bitstream_id?: string | null;
  telemetry?: { temperature_c?: number | null } | null;
  faults?: Array<{ type?: string; message?: string }>;
} | null;

export type Demo = { id: string; name: string; description?: string | null; thumbnail_url?: string | null };

export type SessionStatus = 'queued' | 'starting' | 'active' | 'ending' | 'ended';
export type EndReason =
  | 'user_ended' | 'cancelled' | 'expired' | 'timed_out' | 'fpga_fault' | 'board_offline' | 'programming_failed' | 'board_reserved';

export type Session = {
  id: string;
  demo_id: string;
  status: SessionStatus;
  created_at: string;
  started_at?: string | null;
  expires_at?: string | null;
  ended_at?: string | null;
  end_reason?: EndReason | string | null;
  demo_url?: string | null;
};

export type QueueState = { length: number; position: number | null; active_expires_at?: string | null };

export type ToastLevel = 'info' | 'success' | 'warn' | 'error';
export type Toast = { id: string; level: ToastLevel; message: string };

export type Phase =
  | 'connecting' | 'offline' | 'fault' | 'project' | 'idle' | 'busy'
  | 'requesting' | 'queued' | 'starting' | 'active' | 'ending' | 'ended';

export type TempSample = { at: number; c: number };

export type SocketState = 'connecting' | 'connected' | 'reconnecting';

export type LabState = {
  socket: SocketState;
  ready: boolean;
  now: number;
  board: Board;
  demos: Demo[];
  queue: QueueState;
  session: Session | null;
  recent: Session[];
  requesting: { demoId: string; requestId: string } | null;
  endRequested: boolean;
  lastError: string | null;
  lastEnded: Session | null;
  temps: TempSample[];
  toasts: Toast[];
};

export type WsEvent =
  | { type: 'state.initial'; board: Board; demos?: Demo[]; queue?: QueueState; session?: Session | null; recent_sessions?: Session[] }
  | { type: 'board.updated'; board: Board }
  | { type: 'queue.updated'; queue?: QueueState }
  | { type: 'session.updated'; session: Session | null }
  | { type: 'recent_sessions.updated'; sessions?: Session[] }
  | { type: 'command.result'; request_id?: string; ok: boolean; session_id?: string; error?: { code?: string; message?: string } }
  | { type: 'ui.message'; level?: string; message?: string };

export type LocalAction =
  | { type: 'socket.opened' }
  | { type: 'socket.closed' }
  | { type: 'start.requested'; demoId: string; requestId: string }
  | { type: 'end.requested' }
  | { type: 'error.dismissed' }
  | { type: 'toast.dismissed'; id: string }
  | { type: 'tick'; now: number };

export type Action = WsEvent | LocalAction;
