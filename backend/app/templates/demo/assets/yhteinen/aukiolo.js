// "Auki nyt" -tila aukioloajoista. Sama tiedosto kaikilla esimerkkisivuilla (demopohjissa yleinen).
// Lukee ajat elementistä #aukiolo (data-ma … data-su = "HH:MM-HH:MM", useampi jakso pilkulla
// esim. "10:00-12:00,13:00-17:00", "24:00" = keskiyö; puuttuva päivä = suljettu)
// ja päivittää:
//   [data-tila]    lyhyt tila, esim. "Auki nyt" / "Suljettu"; lisää luokan on-auki tai on-kiinni
//   [data-tanaan]  pitkä tila, esim. "Auki nyt, sulkeutuu klo 17" / "Suljettu, avataan huomenna klo 7.30"
//   [data-paiva="1…7"]  tämän päivän rivi saa luokan on-tanaan ja aria-current="date"
// Ilman JavaScriptiä sivulla näkyy HTML:n kiinteä viikkoaikataulu.
// Testaus: ?aika=2026-11-09T12:00 asettaa kellonajan.
(function () {
  var lahde = document.getElementById("aukiolo");
  if (!lahde) return;
  var avaimet = ["su", "ma", "ti", "ke", "to", "pe", "la"]; // Date.getDay()-järjestys
  var nimet = ["sunnuntaina", "maanantaina", "tiistaina", "keskiviikkona", "torstaina", "perjantaina", "lauantaina"];

  var nyt = new Date();
  var testi = /[?&]aika=([^&]+)/.exec(location.search);
  if (testi) { var t = new Date(decodeURIComponent(testi[1])); if (!isNaN(t)) nyt = t; }

  function minuutit(hhmm) { var o = hhmm.split(":"); return +o[0] * 60 + +o[1]; }
  function klo(m) { var h = Math.floor(m / 60), min = m % 60; return h + (min ? "." + (min < 10 ? "0" : "") + min : ""); }
  // Päivän jaksot aikajärjestyksessä, tyhjä lista = suljettu
  function ajat(paiva) {
    var arvo = lahde.getAttribute("data-" + avaimet[paiva]);
    if (!arvo) return [];
    return arvo.split(",").map(function (jakso) {
      var o = jakso.split("-");
      return { auki: minuutit(o[0]), kiinni: minuutit(o[1]) };
    });
  }

  var tamaPaiva = nyt.getDay();
  var hetki = nyt.getHours() * 60 + nyt.getMinutes();
  var tanaan = ajat(tamaPaiva);
  var nykyinen = null, seuraava = null;
  tanaan.forEach(function (j) {
    if (hetki >= j.auki && hetki < j.kiinni) nykyinen = j;
    else if (hetki < j.auki && !seuraava) seuraava = j;
  });
  var auki = !!nykyinen;
  var pitka;

  if (auki) {
    // Keskiyön yli jatkuva aika on jaettu kahdelle päivälle: "klo 24" ei kerro sulkemisaikaa
    pitka = nykyinen.kiinni >= 1440 ? "Auki nyt" : "Auki nyt, sulkeutuu klo " + klo(nykyinen.kiinni);
  } else if (seuraava) {
    pitka = "Suljettu, avataan tänään klo " + klo(seuraava.auki);
  } else {
    pitka = "Suljettu";
    for (var i = 1; i <= 7; i++) {
      var p = (tamaPaiva + i) % 7, a = ajat(p);
      if (a.length) { pitka += ", avataan " + (i === 1 ? "huomenna" : nimet[p]) + " klo " + klo(a[0].auki); break; }
    }
  }

  document.querySelectorAll("[data-tila]").forEach(function (el) {
    el.textContent = auki ? "Auki nyt" : "Suljettu";
    el.classList.add(auki ? "on-auki" : "on-kiinni");
  });
  document.querySelectorAll("[data-tanaan]").forEach(function (el) {
    el.textContent = pitka;
    el.classList.add(auki ? "on-auki" : "on-kiinni");
  });
  var maanantaistaAlkaen = tamaPaiva === 0 ? 7 : tamaPaiva;
  document.querySelectorAll('[data-paiva="' + maanantaistaAlkaen + '"]').forEach(function (el) {
    el.classList.add("on-tanaan");
    el.setAttribute("aria-current", "date");
  });
})();
