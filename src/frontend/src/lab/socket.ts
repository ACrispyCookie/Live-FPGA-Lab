// The one WebSocket to /api/ws: connect, reconnect with backoff, dispatch every server message, send commands.
import { useCallback, useEffect, useRef } from 'react';
import type { Action, WsEvent } from './types.ts';

export const WS_PROTOCOL = 'fpga-demo.v1';
const MAX_RETRY_MS = 2000;

export function useLabSocket(dispatch: (action: Action) => void, enabled: boolean = true): { send: (type: string, payload?: Record<string, unknown>) => string } {
  const wsRef = useRef<WebSocket | null>(null);
  const attemptsRef = useRef(0);
  const retryRef = useRef<number | undefined>(undefined);
  const requestRef = useRef(0);

  useEffect(() => {
    if (!enabled) return;
    let closed = false;
    function connect() {
      if (closed) return;
      const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
      const ws = new WebSocket(`${protocol}//${location.host}/api/ws`, WS_PROTOCOL);
      wsRef.current = ws;
      ws.addEventListener('open', () => {
        attemptsRef.current = 0;
        dispatch({ type: 'socket.opened' });
      });
      ws.addEventListener('message', (event) => {
        let msg: WsEvent | null = null;
        try { msg = JSON.parse(event.data); } catch { return; }
        if (msg && typeof msg.type === 'string') dispatch(msg);
      });
      ws.addEventListener('close', () => {
        if (closed || wsRef.current !== ws) return;
        attemptsRef.current += 1;
        dispatch({ type: 'socket.closed' });
        retryRef.current = window.setTimeout(connect, Math.min(MAX_RETRY_MS, 200 * 2 ** Math.max(0, attemptsRef.current - 1)));
      });
      ws.addEventListener('error', () => ws.close());
    }
    connect();
    return () => {
      closed = true;
      window.clearTimeout(retryRef.current);
      wsRef.current?.close(1000, 'page unload');
    };
  }, [enabled, dispatch]);

  const send = useCallback((type: string, payload: Record<string, unknown> = {}) => {
    const id = `${Date.now()}-${++requestRef.current}`;
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type, request_id: id, ...payload }));
    return id;
  }, []);

  return { send };
}
