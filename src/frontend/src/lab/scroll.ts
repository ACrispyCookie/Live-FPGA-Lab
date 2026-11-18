// Whether the session panel needs scrolling into view: it does unless it sits fully between the top bar and the
// bottom of the viewport.
export function needsScroll(top: number, bottom: number, viewportHeight: number, barHeight: number): boolean {
  return !(top >= barHeight && bottom <= viewportHeight);
}
