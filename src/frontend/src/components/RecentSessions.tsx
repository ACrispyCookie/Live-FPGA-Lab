// Who had the board lately and how it ended: a filled dot for the outcome, the demo, the words, the time.
import { copy } from '../lab/copy.ts';
import { demoName, recentOutcome, reservedFor } from '../lab/derive.ts';
import type { LabState, Session } from '../lab/types.ts';
import { Skel } from './Skeleton.tsx';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** Sessions that reached the board or failed trying; a queue entry that was cancelled never shows. */
export function wasOnBoard(session: Session): boolean {
  return Boolean(session.started_at)
    || ['starting', 'active', 'ending'].includes(session.status)
    || ['fpga_fault', 'board_offline', 'programming_failed'].includes(session.end_reason || '');
}

export function formatRecentTime(iso: string, now: number): string {
  const t = new Date(iso);
  const today = new Date(now);
  const hhmm = `${String(t.getHours()).padStart(2, '0')}:${String(t.getMinutes()).padStart(2, '0')}`;
  const sameDay = t.getFullYear() === today.getFullYear() && t.getMonth() === today.getMonth() && t.getDate() === today.getDate();
  return sameDay ? `${copy.recent.today} ${hhmm}` : `${t.getDate()} ${MONTHS[t.getMonth()]} ${hhmm}`;
}

export function RecentSessions({ state }: { state: LabState }) {
  if (!state.ready) {
    return (
      <div className="reclist">
        {Array.from({ length: 3 }, (_, i) => (
          <div key={i} className="rec loading" aria-hidden="true"><span className="dot" /><span><Skel h={14} w="40%" pill /><Skel h={12} w={120} pill /></span><Skel h={12} w={70} pill /></div>
        ))}
      </div>
    );
  }
  const rows = state.recent.filter(wasOnBoard).slice(0, 4);
  if (!rows.length) return <div className="empty">{copy.recent.empty}</div>;
  const reserved = reservedFor(state);
  return (
    <div className="reclist">
      {rows.map((session) => {
        const outcome = recentOutcome(session, reserved);
        const when = session.ended_at || session.started_at || session.created_at;
        return (
          <div className="rec" key={session.id}>
            <span className={`dot ${outcome.tone}`} />
            <span><b>{demoName(state.demos, session.demo_id)}</b><small>{outcome.text}</small></span>
            <time dateTime={when}>{formatRecentTime(when, state.now)}</time>
          </div>
        );
      })}
    </div>
  );
}
