// Raised blocks in the shape of the content they stand in for, shimmering while the first state loads.
import type { CSSProperties } from 'react';

export function Skel({ w, h, pill = false, className = '' }: { w?: string | number; h?: string | number; pill?: boolean; className?: string }) {
  const style: CSSProperties = {};
  if (w != null) style.width = w;
  if (h != null) style.height = h;
  return <span className={`skel${pill ? ' pill' : ''}${className ? ` ${className}` : ''}`} style={style} aria-hidden="true" />;
}
