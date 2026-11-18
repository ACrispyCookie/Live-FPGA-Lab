// The mirror of the portfolio's top bar: the name links back to njason.dev, the board pill sits at the right.
// While the session panel is off screen and the visitor has a session, the pill mirrors that session instead.
import { copy } from '../lab/copy.ts';
import { phase, pillText } from '../lab/derive.ts';
import { isLive } from '../lab/reducer.ts';
import type { LabState } from '../lab/types.ts';
import { Led } from './Led.tsx';

export function TopBar({ state, sessionVisible }: { state: LabState; sessionVisible: boolean }) {
  const p = phase(state);
  const pill = pillText(state, sessionVisible);
  const online = state.ready && state.socket === 'connected' && p !== 'offline';
  const mirrorsSession = !sessionVisible && (isLive(state.session) || Boolean(state.requesting));
  const name = state.board?.label || copy.board.fallbackName;
  return (
    <header className="topbar">
      <div className="in">
        <a className="name" href={copy.site.home}>{copy.site.name}</a>
        <nav aria-label="Sections">
          <a href="#session-hero">{p === 'active' ? copy.nav.yourDemo : copy.nav.session}</a>
          <a href="#demos">{copy.nav.demos}</a>
          <a href="#recent">{copy.nav.recent}</a>
        </nav>
        <a className={`boardpill tone-${pill.tone}`} href="#session-hero" aria-live="polite">
          <Led on={online} blink={p === 'starting' || p === 'requesting'} />
          {!mirrorsSession && <b>{name}</b>}
          <span>{pill.text}</span>
        </a>
      </div>
    </header>
  );
}
