// A link straight to a demo: https://fpga.njason.dev/?start=<demo id> joins the queue for it on arrival, as if the
// visitor had pressed its Start button (the portfolio's "Run the demo" buttons link here).

type DemoRef = { id: string; name: string };
export type Autostart =
  | { action: 'none' }
  | { action: 'start'; demo: DemoRef }
  | { action: 'skip'; message: string };

/** What to do with the address's `start` parameter, once the first state from the server has arrived. */
export function autostart(search: string, state: { demos: DemoRef[]; hasSession: boolean; reserved: boolean }): Autostart {
  const id = new URLSearchParams(search).get('start');
  if (!id) return { action: 'none' };
  const demo = state.demos.find((d) => d.id === id);
  if (!demo) return { action: 'skip', message: 'That demo is not available right now.' };
  if (state.hasSession) return { action: 'skip', message: 'You already have a session, so nothing new was started.' };
  if (state.reserved) return { action: 'skip', message: 'The board is reserved for projects right now.' };
  return { action: 'start', demo };
}

/** The address without `start`, so a refresh or a shared link from here doesn't join the queue again. */
export function withoutStart(pathAndSearch: string, hash: string): string {
  const [path, query = ''] = pathAndSearch.split('?');
  const params = new URLSearchParams(query);
  params.delete('start');
  const rest = params.toString();
  return `${path}${rest ? `?${rest}` : ''}${hash}`;
}
