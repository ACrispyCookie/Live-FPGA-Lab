// The path from pressing Start to the demo on screen, as three lights on a short trace: lit when done, blinking
// while current, dark while ahead, red where it failed. Not numbered: the order is the trace's.
import type { Step } from '../lab/derive.ts';

export function Steps({ steps }: { steps: Step[] }) {
  return (
    <ol className="steps">
      {steps.map((s) => (
        <li key={s.key} data-state={s.state} aria-current={s.state === 'current' ? 'step' : undefined}>
          <i className="sl" aria-hidden="true" />{s.label}
        </li>
      ))}
    </ol>
  );
}
