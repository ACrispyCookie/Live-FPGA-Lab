// The status LED: a filled dot that breathes while online, blinks while the board is being programmed.
export function Led({ on, blink = false, ink = false }: { on: boolean; blink?: boolean; ink?: boolean }) {
  return <i className={`led ${on ? 'on' : 'off'}${blink && on ? ' blink' : ''}${ink ? ' ink' : ''}`} aria-hidden="true" />;
}
