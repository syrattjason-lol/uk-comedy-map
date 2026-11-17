JASON SYRATT PORTFOLIO
======================

Upload the complete Portfolio folder to the root of the UK Comedy Map hosting account.

Expected page address:
https://www.ukcomedymap.co.uk/Portfolio/Jason_syratt_1/

STRUCTURE
---------
Portfolio/
  Jason_syratt_1/
    index.html
    assets/
      images/
      documents/

This revised version organises the portfolio as company accordions. Opening a company reveals a horizontally scrollable project carousel with images, text and links to supporting work.

The page is not linked from the main UK Comedy Map navigation and includes noindex/nofollow metadata. This discourages search indexing but does not make the page private. Use hosting-level password protection for genuine access control.

The After Effects source file still needs to be exported as WebM, MP4 or Lottie before it can be embedded in the browser animation area.

Responsive update:
- Mobile carousel cards now fit exactly within the screen width.
- Accordion headings stack cleanly on narrow screens.
- Images use a stable 4:3 mobile ratio and text panels use content-based height.
- Header, hero, typography, buttons and spacing scale from 320px upward.

Update: carousel project cards now open a responsive project-detail pop-up. Direct deck and website links remain clickable without opening the pop-up.

Motion and performance update:
- Replaced the simple pointer animation with a canvas-based gravity field using interactive circles, capsules, rings, diamonds, triangles and hexagons.
- Cursor movement pushes shapes; holding the pointer creates an attraction field.
- Scroll position adds layered parallax depth to the grid, artwork, type and physics objects.
- The animation pauses when off-screen or when the browser tab is hidden, and respects reduced-motion settings.
- Removed costly full-page blur/noise effects, retained native touch scrolling, throttled carousel updates and prevented carousel controls from shifting the whole page vertically.


Hero update: Apple-style glass bokeh focus shift on scroll, restrained depth movement, smoother cursor response and mobile-safe text/buttons. Gravity bomb game unchanged.
