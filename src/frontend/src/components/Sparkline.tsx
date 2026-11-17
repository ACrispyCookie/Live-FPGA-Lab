// The last minutes of die temperature as one cyan line over a raised tile.
import { sparkPath } from '../lab/derive.ts';
import type { TempSample } from '../lab/types.ts';

export function Sparkline({ temps }: { temps: TempSample[] }) {
  const d = sparkPath(temps, 100, 34);
  return (
    <svg className="spark" viewBox="0 0 100 34" preserveAspectRatio="none" aria-hidden="true">
      <path className="base" d="M0 33 H100" />
      {d && <path d={d} />}
    </svg>
  );
}
