// Premium-pohjan elävöitys. Sivu toimii kokonaan ilman tätä: tämä vain ajoittaa puhelimen
// varauspalkin, korostaa hinnaston aktiivisen kategorian ja antaa valon seurata osoitinta herossa.
// Tyylit tyylit.css:ssä: html.js, .hero.on-ohi, .hero.on-osoitin, .palkki.on-esilla, a[aria-current].
(function () {
  var hero = document.querySelector(".hero");
  if (!hero || !("IntersectionObserver" in window)) return;
  var rauha = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  document.documentElement.classList.add("js");

  // Hero on ohitettu, kun sen alareuna on ruudun ylimmässä kolmanneksessa (napit jo poissa näkyvistä)
  var palkki = document.querySelector(".palkki");
  new IntersectionObserver(function (osumat) {
    var ohi = !osumat[osumat.length - 1].isIntersecting;
    hero.classList.toggle("on-ohi", ohi);
    if (palkki) palkki.classList.toggle("on-esilla", ohi);
  }, { rootMargin: "-33% 0px 0px 0px" }).observe(hero);

  // Aktiivinen kategoria: ylin ryhmä, joka osuu ruudun yläosan kaistaan
  var linkit = Array.prototype.slice.call(document.querySelectorAll(".valilehdet a"));
  var rivi = document.querySelector(".valilehdet ul");
  if (linkit.length && rivi) {
    var kaistalla = {};
    var nykyinen = null;
    var tarkkailija = new IntersectionObserver(function (osumat) {
      osumat.forEach(function (osuma) { kaistalla[osuma.target.id] = osuma.isIntersecting; });
      var aktiivinen = linkit.filter(function (a) { return kaistalla[a.hash.slice(1)]; })[0];
      if (!aktiivinen || aktiivinen === nykyinen) return;
      nykyinen = aktiivinen;
      linkit.forEach(function (a) {
        if (a === aktiivinen) a.setAttribute("aria-current", "location");
        else a.removeAttribute("aria-current");
      });
      // Puhelimen vaakarivi: aktiivinen välilehti näkyviin
      if (rivi.scrollWidth > rivi.clientWidth) {
        rivi.scrollTo({ left: aktiivinen.offsetLeft - 20, behavior: rauha ? "auto" : "smooth" });
      }
    }, { rootMargin: "-20% 0px -70% 0px" });
    linkit.forEach(function (a) {
      var ryhma = document.getElementById(a.hash.slice(1));
      if (ryhma) tarkkailija.observe(ryhma);
    });
  }

  // Valo seuraa osoitinta (vain hiiri, ei kosketus), pehmennettynä
  var valo = document.querySelector(".valo-osoitin");
  if (valo && !rauha && window.matchMedia("(hover: hover) and (pointer: fine)").matches) {
    var x = 0, y = 0, kohdeX = 0, kohdeY = 0, kaynnissa = false, alussa = true;
    var askel = function () {
      x += (kohdeX - x) * 0.09;
      y += (kohdeY - y) * 0.09;
      valo.style.transform = "translate3d(" + x.toFixed(1) + "px," + y.toFixed(1) + "px,0)";
      if (Math.abs(kohdeX - x) + Math.abs(kohdeY - y) > 0.5) requestAnimationFrame(askel);
      else kaynnissa = false;
    };
    hero.addEventListener("pointermove", function (e) {
      var alue = hero.getBoundingClientRect();
      kohdeX = e.clientX - alue.left;
      kohdeY = e.clientY - alue.top;
      if (alussa) { x = kohdeX; y = kohdeY; alussa = false; }
      hero.classList.add("on-osoitin");
      if (!kaynnissa) { kaynnissa = true; requestAnimationFrame(askel); }
    });
    hero.addEventListener("pointerleave", function () { hero.classList.remove("on-osoitin"); });
  }
})();
