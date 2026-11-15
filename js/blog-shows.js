/* Page-specific live listings for UK Comedy Map blog guides.
   Reads the site's existing /data/shows.json; no extra scraper or server needed.
   Uses venue/title names (NOT show.type, which may be unreliable in old exports).
*/
(() => {
  'use strict';
  const sections = [...document.querySelectorAll('[data-blog-shows]')];
  if (!sections.length) return;
  const text = value => String(value == null ? '' : value).toLowerCase().replace(/&amp;/g, '&').replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
  const has = (source, aliases) => aliases.some(alias => text(source).includes(text(alias)));
  const metroCity = (s, area) => {
    const c = text(s.city);
    if (area === 'london') return c === 'london' || c === 'greater london';
    if (area === 'manchester') return c === 'manchester' || c === 'salford';
    if (area === 'greater-manchester') return ['manchester','salford','stockport','bury','altrincham','oldham','chorley','cheadle','saddleworth','glossop','congleton','lymm','padiham','lancaster'].includes(c);
    return true;
  };
  const localDate = () => {
    const n = new Date();
    return [n.getFullYear(), String(n.getMonth()+1).padStart(2,'0'), String(n.getDate()).padStart(2,'0')].join('-');
  };
  const venues = {
    london: ['angel comedy','the bill murray','bill murray','camden head','eagle eats','rye lane ruckus','downstairs at the kings head','downstairs at the king','the kings head muswell hill','pub on the park','quinns','quinn s'],
    openmic: ['frog bucket','frog and bucket','creatures','ape apple','ape and apple','laughienda','lion s den','fitzgerald','stage radio','stage and radio','comedy balloon'],
    manchester: ['frog bucket','frog and bucket','creatures','xs malarkey','53two','laughienda','lion s den','club 9','banyan tree','manfords comedy club','manford s comedy club','didsbury comedy club','heatons comedy club','oldham comedy club','off the rails comedy club','hope mill theatre','chorley little theatre','altrincham garrick']
  };
  const micTitle = /\b(beat the frog|comedy balloon|easy comedy|laughienda|comedy circus|open mic|open mike|new act|new material|hatched|work in progress|wip|try out|tryout|comedy bingo|comedy at the fitzgerald)\b/i;
  const tourNames = ['peter kay','jimmy carr','bill bailey','ricky gervais','jason manford','romesh ranganathan','chris ramsey','sophie duker','maisie adam','susan calman','phil ellis','rob auton','stephen bailey','nick doody','alistair barrie','steve gribbin'];
  function matches(s, type) {
    const title = String(s.comedian || s.title || '');
    const venue = String(s.venue || '');
    if (type === 'free-london') return metroCity(s,'london') && (has(venue,venues.london) || has(title,['rye lane ruckus','angel comedy','quintessentially comedy','comedy industrial complex']));
    if (type === 'open-mic-manchester') return metroCity(s,'manchester') && micTitle.test(title) && (has(venue,venues.openmic) || has(title,['beat the frog','comedy balloon','laughienda','easy comedy']));
    if (type === 'clubs-manchester') return metroCity(s,'greater-manchester') && (
      (has(venue,venues.manchester) && (!has(venue,['53two','banyan tree','lion s den','hope mill theatre','chorley little theatre','altrincham garrick']) || has(title,['xs malarkey','club 9','laughienda','manford']))) || has(title,['xs malarkey','laughienda','club 9 comedy','beat the frog','manfords comedy club','manford s comedy club'])
    );
    if (type === 'touring') return has(title,tourNames) && !/\b(tribute|lookalike|impersonator|impressionist)\b/i.test(title);
    return false;
  }
  function price(s) {
    const val = String(s.price || s.ticket_price || s.cost || '').trim();
    if (!val) return 'Check ticket price';
    return val;
  }
  function httpsUrl(v) {
    const value = String(v || '');
    try { const u = new URL(value, window.location.origin); return ['http:', 'https:'].includes(u.protocol) && value !== '#' ? u.href : ''; }
    catch { return ''; }
  }
  function make(tag, className, string) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (string !== undefined) el.textContent = String(string);
    return el;
  }
  function formatDate(dateText) {
    const date = new Date(String(dateText).slice(0,10) + 'T12:00:00');
    return Number.isNaN(date.getTime()) ? String(dateText).slice(0,10) : date.toLocaleDateString('en-GB',{weekday:'short',day:'numeric',month:'short',year:'numeric'});
  }
  function renderCard(s) {
    const card = make('article','blog-show-card');
    const imgURL = httpsUrl(s.image);
    if (imgURL) {
      const img = make('img','blog-show-card__image');
      img.src = imgURL; img.alt = ''; img.loading = 'lazy'; img.decoding = 'async';
      img.addEventListener('error', () => img.remove(), {once:true});
      card.appendChild(img);
    }
    const body = make('div','blog-show-card__body');
    body.appendChild(make('h3','blog-show-card__title',s.comedian || s.title));
    body.appendChild(make('p','blog-show-card__meta',s.venue || 'Venue to confirm'));
    body.appendChild(make('p','blog-show-card__meta',s.city || 'UK'));
    body.appendChild(make('p','blog-show-card__meta blog-show-card__date',formatDate(s.date)));
    if (s.time) body.appendChild(make('p','blog-show-card__meta',s.time));
    body.appendChild(make('span','blog-show-card__price',price(s)));
    const link = httpsUrl(s.tickets || s.ticket_url || s.url);
    if (link) { const a=make('a','blog-show-card__link','Show details & tickets'); a.href=link; a.target='_blank'; a.rel='noopener noreferrer'; body.appendChild(a); }
    card.appendChild(body);
    return card;
  }
  function renderSection(section, shows) {
    const type = section.dataset.blogShows;
    const target = section.querySelector('[data-show-results]');
    const more = section.querySelector('[data-show-more]');
    if (!target) return;
    const cutoff=localDate();
    const seen = new Set();
    let matchesForPage=shows.filter(s => {
      const date=String(s.date||'').slice(0,10);
      const name = text(s.comedian || s.title);
      if (!name || ['nearby accommodation','description','dates and tickets','tickets','book now','contact us','more info','upcoming events','upcoming shows','website','find tickets'].includes(name)) return false;
      if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || date < cutoff || !matches(s,type)) return false;
      const key=[text(s.city),text(s.venue),date,text(s.comedian || s.title)].join('|');
      if (seen.has(key)) return false;
      seen.add(key);return true;
    }).sort((a,b)=>String(a.date).localeCompare(String(b.date)));
    // A named comedian is more reliable for touring than legacy type:'tour'.
    const perPage=6; let showing=0;
    const add = () => {
      const next=matchesForPage.slice(showing,showing+perPage);
      next.forEach(s => target.appendChild(renderCard(s)));
      showing += next.length;
      more.hidden = showing >= matchesForPage.length;
      more.textContent = `Load more shows (${matchesForPage.length - showing} left)`;
    };
    target.replaceChildren();
    if (!matchesForPage.length) {
      target.appendChild(make('p','blog-shows__status','No upcoming matching listings in the current feed. You can still check the venue links and the main show listings for more dates.'));
      more.hidden=true;return;
    }
    more.addEventListener('click',add); add();
  }
  fetch('/data/shows.json',{cache:'no-store'})
    .then(r=>{ if(!r.ok) throw new Error('Show feed unavailable');return r.json(); })
    .then(data=>{
      // Support the site's existing array and a possible {shows:[...]} export.
      const shows=Array.isArray(data)?data:(Array.isArray(data.shows)?data.shows:[]);
      sections.forEach(s=>renderSection(s,shows));
    })
    .catch(()=>sections.forEach(s=>{
      const target=s.querySelector('[data-show-results]');
      const more=s.querySelector('[data-show-more]');
      if(target){target.replaceChildren(make('p','blog-shows__status','Could not load live listings right now. Please check the main show listings or the venue’s own website.'));}
      if(more)more.hidden=true;
    }));
})();
