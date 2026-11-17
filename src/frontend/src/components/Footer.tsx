// The page's foot, the same component as njason.dev's: a full-width band off the trace, its content aligned with the
// page's column. The name and one line on the left, links on the right, copyright and source underneath.
import { copy } from '../lab/copy.ts';

export function Footer() {
  const f = copy.footer;
  return (
    <footer className="foot">
      <div className="foot-in">
        <div><b>{copy.site.name}</b><p>{f.line}</p></div>
        <div className="links">
          {f.links.map((l) => <a key={l.href} href={l.href} rel="noopener">{l.label}</a>)}
        </div>
        <small><span>{f.copyright(new Date().getFullYear())}</span><a href={copy.site.source} rel="noopener">{copy.site.sourceLabel}</a></small>
      </div>
    </footer>
  );
}
