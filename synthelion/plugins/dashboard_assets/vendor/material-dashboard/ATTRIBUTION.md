## Material Dashboard 3 (Free) — Creative Tim

`material-dashboard.min.css`, `material-dashboard.min.js`,
`js/perfect-scrollbar.min.js`, and `js/smooth-scrollbar.min.js` in this folder
are vendored, unmodified, from **Material Dashboard 3 Free** by
[Creative Tim](https://www.creative-tim.com/product/material-dashboard)
(https://www.creative-tim.com). They style and drive the Synthelion
dashboard's login page (`login.html`, structure mapped from the template's
`pages/sign-up.html`) and main page (`index.html`, structure mapped from
`pages/dashboard.html`'s sidenav + navbar) — external CDN fonts/icons and
marketing links to pages this dashboard doesn't have were removed rather than
vendored. The template's own stock illustration (`illustration-signup.jpg`)
was replaced with `img/synthelion-login.png`, a Synthelion-branded image, so
it is no longer vendored here.

Licensed under the MIT License — see `LICENSE-material-dashboard.md` in this
folder for the full text and copyright notice, reproduced here as required by
the license:

> Copyright (c) 2017 Creative Tim (https://www.creative-tim.com)

`css/inter.css` + `fonts/inter-latin.woff2` are the Inter typeface (Latin
subset) the template's pages normally load from Google Fonts — downloaded
once from fonts.gstatic.com during development and self-hosted here instead,
so the dashboard never fetches fonts from a CDN at runtime. Inter is licensed
under the SIL Open Font License 1.1 — see `LICENSE-inter.txt`.

Copyright (c) 2016 The Inter Project Authors (https://github.com/rsms/inter)

Note: the template's own bundled Nucleo icon font (`nucleo-icons.woff2/.woff/.ttf`)
is corrupted upstream — verified structurally invalid (bad WOFF2 header) in
three independent copies: a fresh download of the template, a fresh `git
clone`, and a fresh fetch from `raw.githubusercontent.com`. It was dropped
rather than vendored; the dashboard uses no icon font.

Only `login.html` and `index.html` use any of this; `dashboard.css` and
`dashboard.js` are original Synthelion code, and everything is layered over
the vendored Bootstrap 5 in `../bootstrap/`.
