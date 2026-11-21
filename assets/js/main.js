/* Aditya Dave — minimal progressive enhancement. No dependencies. */
(function () {
  "use strict";

  /* Mobile navigation ---------------------------------------------------- */
  var toggle = document.querySelector(".nav-toggle");
  var nav = document.getElementById("nav");

  if (toggle && nav) {
    toggle.addEventListener("click", function () {
      var open = nav.getAttribute("data-open") === "true";
      nav.setAttribute("data-open", String(!open));
      toggle.setAttribute("aria-expanded", String(!open));
    });

    nav.addEventListener("click", function (e) {
      if (e.target.tagName === "A") {
        nav.setAttribute("data-open", "false");
        toggle.setAttribute("aria-expanded", "false");
      }
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && nav.getAttribute("data-open") === "true") {
        nav.setAttribute("data-open", "false");
        toggle.setAttribute("aria-expanded", "false");
        toggle.focus();
      }
    });
  }

  /* Reading progress bar (article pages only) ---------------------------- */
  var bar = document.querySelector(".progress");
  var article = document.querySelector(".prose");

  if (bar && article) {
    var ticking = false;

    var update = function () {
      var start = article.offsetTop;
      var span = article.offsetHeight - window.innerHeight + 120;
      var pos = window.scrollY - start;
      var pct = span > 0 ? pos / span : 0;
      bar.style.transform = "scaleX(" + Math.min(1, Math.max(0, pct)) + ")";
      ticking = false;
    };

    var onScroll = function () {
      if (ticking) return;
      ticking = true;
      // rAF is parked while the tab is hidden; fall back so the bar is never stale.
      if (window.requestAnimationFrame && !document.hidden) {
        window.requestAnimationFrame(update);
      } else {
        update();
      }
    };

    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll, { passive: true });
    update();
  }

  /* Current year in footer ----------------------------------------------- */
  var year = document.querySelector("[data-year]");
  if (year) year.textContent = String(new Date().getFullYear());
})();
