# Moodboard images

The moodboard tiles on `index.html` are currently **CSS/SVG recreations** of the
visual references (so the page stays fully self-contained — no external image deps).

To swap in real source photos, drop them here named `01.jpg` … `12.jpg` in this order:

01 Buccaneer C60 j-card        05 Vintage classics spines     09 Geometric (retro palette)
02 Philips C-60 polka dots     06 Geometric covers            10 Concentric cover design
03 Caravan LP type             07 Geometric posters           11 The Spirit of the Bauhaus
04 Ellison set spines          08 Penguin classics spines     12 (brand ferric tie-in)

…then tell Claude to wire them in (it will switch the `.mood-art` tiles to `<img>`).
