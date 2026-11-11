// Premium-pohjan elävöitys. Sivu toimii kokonaan ilman tätä: tämä ajoittaa puhelimen varauspalkin,
// korostaa hinnaston aktiivisen kategorian ja piirtää heron ruutusarjan (kamera liikkuu vierityksen mukana).
// Tyylit tyylit.css:ssä: html.js, html.napit-poissa, .hero.on-ohi, .tausta.on-elokuva, .palkki.on-esilla, a[aria-current].
(function () {
  var hero = document.querySelector(".hero");
  if (!hero || !("IntersectionObserver" in window)) return;
  var juuri = document.documentElement;
  var rauha = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  document.documentElement.classList.add("js");

  // Hero on ohitettu, kun sen alareuna on ruudun ylimmässä kolmanneksessa (napit jo poissa näkyvistä)
  var palkki = document.querySelector(".palkki");
  new IntersectionObserver(function (osumat) {
    var ohi = !osumat[osumat.length - 1].isIntersecting;
    hero.classList.toggle("on-ohi", ohi);
    if (palkki) palkki.classList.toggle("on-esilla", ohi);
  }, { rootMargin: "-33% 0px 0px 0px" }).observe(hero);

  // Puhelimen yläpalkin Varaa aika / Soita näkyy vasta, kun heron oma nappi on poissa ruudulta
  // (ei kahta samaa nappia yhtä aikaa). Ilman tätä skriptiä molemmat näkyvät.
  var heronNapit = hero.querySelector(".napit");
  if (heronNapit) {
    new IntersectionObserver(function (osumat) {
      juuri.classList.toggle("napit-poissa", !osumat[osumat.length - 1].isIntersecting);
    }).observe(heronNapit);
  }

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

  // Heron elokuva: ruutusarja canvasille stillin päälle. Still jää näkyviin, jos liikettä ei haluta
  // (reduced motion, Save-Data, vähän muistia) tai ruudut eivät lataudu.
  var tausta = hero.querySelector(".tausta");
  var yhteys = navigator.connection;
  if (!tausta || rauha || (yhteys && yhteys.saveData) || navigator.deviceMemory < 2) return;

  var ALKU = 0.25;      // osuus liikkeestä, joka ajetaan itsestään sivun auettua
  var ALKU_MS = 1600;
  var leveys = window.matchMedia("(min-width: 64rem)");
  var kierros = 0;      // kasvaa, kun ruutusarja vaihtuu: vanhan sarjan lataukset jäävät huomiotta

  function kaynnista() {
    var oma = ++kierros;
    var iso = leveys.matches;
    var osoitteet = (tausta.getAttribute(iso ? "data-ruudut-l" : "data-ruudut-p") || "").split(" ").filter(Boolean);
    var maara = osoitteet.length;
    var canvas = document.createElement("canvas");
    var piirto = canvas.getContext && canvas.getContext("2d");
    if (maara < 2 || !piirto) return;
    canvas.className = "elokuva";

    var ruudut = new Array(maara);
    var kohta = 0, piirretty = -1, ruutu = -1, alkuHetki = 0, kaynnissa = false, muuttui = false;

    // Lähin ladattu ruutu annetusta kohdasta annettuun suuntaan
    function ladattu(i, suunta) {
      while (i >= 0 && i < maara && !ruudut[i]) i += suunta;
      return i >= 0 && i < maara ? i : -1;
    }

    function askel(nyt) {
      if (oma !== kierros) return;
      // Liike ajetaan sillä matkalla, jonka kuva on näkyvissä: puhelimella kuva on vain heron yläosassa
      var alue = hero.getBoundingClientRect();
      var kuvanAla = canvas.offsetTop + canvas.offsetHeight;
      var matka = (kuvanAla > 0 ? Math.min(alue.height, kuvanAla) : alue.height) + alue.top + window.scrollY;
      var vieritys = Math.min(Math.max(window.scrollY / matka, 0), 1);
      var alku = alkuHetki ? Math.min((nyt - alkuHetki) / ALKU_MS, 1) : 0;
      var tavoite = ALKU * (1 - Math.pow(1 - alku, 3)) + (1 - ALKU) * vieritys;
      kohta += (tavoite - kohta) * 0.16;
      if (Math.abs(tavoite - kohta) < 0.0005) kohta = tavoite;

      if (muuttui || Math.abs(kohta - piirretty) > 0.0004) {
        // Lähin ladattu ruutu sellaisenaan: kahden ruudun häivytys näyttäisi putoavan hiuksen kahtena
        var lahin = Math.round(kohta * (maara - 1));
        var ala = ladattu(lahin, -1);
        var yla = ladattu(lahin, 1);
        var uusi = ala < 0 || yla >= 0 && yla - lahin < lahin - ala ? yla : ala;
        if (uusi >= 0 && uusi !== ruutu) {
          piirto.drawImage(ruudut[uusi], 0, 0, canvas.width, canvas.height);
          ruutu = uusi;
        }
        // Kuva liikkuu hitaammin kuin sisältö ja himmenee, kun hinnasto tulee sen päälle
        canvas.style.transform = "translate3d(0," + (window.scrollY * (iso ? 0.15 : 0.2)).toFixed(1) + "px,0)";
        canvas.style.opacity = (1 - 0.7 * vieritys * vieritys).toFixed(3);
        piirretty = kohta;
        muuttui = false;
      }
      if (kohta !== tavoite || alku < 1 && alkuHetki) requestAnimationFrame(askel);
      else kaynnissa = false;
    }

    function heratys() {
      if (!kaynnissa && oma === kierros) { kaynnissa = true; requestAnimationFrame(askel); }
    }

    // Ensin joka neljäs ruutu (liike toimii heti karkeana), sitten loput väleihin
    var jono = [];
    [4, 2, 1].forEach(function (vali) {
      for (var i = 0; i < maara; i += vali) if (jono.indexOf(i) < 0) jono.push(i);
    });
    var karkea = Math.ceil(maara / 4);
    var valmiina = 0, seuraava = 0;

    function lataa() {
      if (oma !== kierros || seuraava >= jono.length) return;
      var i = jono[seuraava++];
      var kuva = new Image();
      kuva.decoding = "async";
      kuva.fetchPriority = "low";
      var valmis = function () {
        if (oma !== kierros) return;
        ruudut[i] = kuva;
        valmiina++;
        if (i === 0) {
          // Ensimmäinen ruutu on sama kuva kuin still: vaihto ei näy
          canvas.width = kuva.naturalWidth;
          canvas.height = kuva.naturalHeight;
          piirto.drawImage(kuva, 0, 0);
          tausta.insertBefore(canvas, tausta.querySelector(".himmennys"));
          tausta.classList.add("on-elokuva");
        }
        if (valmiina === karkea) alkuHetki = performance.now();
        muuttui = true;
        heratys();
        lataa();
      };
      // Virheessä ruutu jää väliin: piirto käyttää lähintä ladattua
      var ohita = function () { lataa(); };
      kuva.src = osoitteet[i];
      if (kuva.decode) kuva.decode().then(valmis, ohita);
      else { kuva.onload = valmis; kuva.onerror = ohita; }
    }

    window.addEventListener("scroll", heratys, { passive: true });
    window.addEventListener("resize", heratys);
    for (var n = 0; n < 3; n++) lataa();

    return function () {
      window.removeEventListener("scroll", heratys);
      window.removeEventListener("resize", heratys);
      tausta.classList.remove("on-elokuva");
      if (canvas.parentNode) canvas.parentNode.removeChild(canvas);
    };
  }

  // Ruudut ladataan vasta, kun sivu on valmis: ne eivät kilpaile stillin, fonttien ja tyylien kanssa
  var pura = null;
  var aloita = function () {
    var kun = window.requestIdleCallback || function (f) { setTimeout(f, 200); };
    kun(function () { pura = kaynnista(); });
  };
  if (document.readyState === "complete") aloita();
  else window.addEventListener("load", aloita);

  // Näytön kääntö tai ikkunan koon muutos rajan yli: vaihdetaan toiseen sarjaan
  var vaihda = function () {
    if (pura) pura();
    pura = kaynnista();
  };
  if (leveys.addEventListener) leveys.addEventListener("change", vaihda);
})();
