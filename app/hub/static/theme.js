// SPDX-License-Identifier: GPL-2.0-or-later
// Chooses the web form's theme before the page paints: White Night while the browser prefers a
// dark scheme, White Paper otherwise, and again whenever that preference changes. A classic
// script in <head>, because the page's policy allows no inline script.
(() => {
  const dark = typeof window.matchMedia === "function" ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  const choose = () => { document.documentElement.dataset.theme = dark && dark.matches ? "white-night" : "white-paper"; };
  choose();
  if (dark && typeof dark.addEventListener === "function") dark.addEventListener("change", choose);
})();
