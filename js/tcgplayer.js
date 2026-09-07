(function () {
  var PARTNER = "https://partner.tcgplayer.com/c/7670706/1780961/21018";
  var REL = "noopener nofollow sponsored";
  var PRODUCT_LINE = "Magic";

  function affiliate(dest) {
    if (!dest) return dest;
    if (dest.indexOf("partner.tcgplayer.com") >= 0) return dest;
    return PARTNER + (PARTNER.indexOf("?") >= 0 ? "&" : "?") + "u=" + encodeURIComponent(dest);
  }

  function cardSearchUrl(name) {
    var dest = "https://www.tcgplayer.com/search/magic/product?q=" +
      encodeURIComponent(name) + "&productLineName=magic";
    return affiliate(dest);
  }

  function massLine(qty, name) {
    return qty + " " + name;
  }

  function uniqueCards(cards) {
    var out = [];
    var seen = {};
    (cards || []).forEach(function (row) {
      var qty = row.qty || row[0];
      var name = (row.name || row[1] || "").trim();
      if (!qty || !name || seen[name]) return;
      seen[name] = 1;
      out.push({ qty: qty, name: name });
    });
    return out;
  }

  function massText(cards) {
    return uniqueCards(cards).map(function (row) {
      return massLine(row.qty, row.name);
    }).join("\n");
  }

  function massDest(cards) {
    var q = "productline=" + encodeURIComponent(PRODUCT_LINE);
    var c = uniqueCards(cards).map(function (row) {
      return massLine(row.qty, row.name);
    }).join("||");
    if (c) q += "&c=" + encodeURIComponent(c);
    return "https://www.tcgplayer.com/massentry?" + q;
  }

  function massBoxUrl(cards) {
    return affiliate(massDest(cards || []));
  }

  function copyText(text) {
    if (!text) return false;
    try {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.cssText = "position:fixed;left:-9999px;top:0";
      document.body.appendChild(ta);
      ta.select();
      ta.setSelectionRange(0, text.length);
      var ok = document.execCommand("copy");
      document.body.removeChild(ta);
      if (ok) return true;
    } catch (e) {}
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).catch(function () {});
    }
    return false;
  }

  function cardsFromDeck(root) {
    var cards = [];
    Array.prototype.forEach.call((root || document).querySelectorAll(".text-line"), function (line) {
      var qty = parseInt(((line.querySelector(".qty") || {}).textContent || "").replace(/\D/g, ""), 10);
      var name = ((line.querySelector(".card-title") || {}).textContent || "").trim();
      if (qty && name) cards.push({ qty: qty, name: name });
    });
    return cards;
  }

  function enhance() {
    Array.prototype.forEach.call(document.querySelectorAll(".text-line"), function (line) {
      if (line.querySelector(".buy-tcg-inline")) return;
      var name = ((line.querySelector(".card-title") || {}).textContent || "").trim();
      if (!name) return;
      var a = document.createElement("a");
      a.className = "buy-tcg-inline";
      a.href = cardSearchUrl(name);
      a.target = "_blank";
      a.rel = REL;
      a.textContent = "Buy";
      a.addEventListener("click", function (e) { e.stopPropagation(); });
      line.appendChild(a);
    });

    Array.prototype.forEach.call(document.querySelectorAll("[data-buy-deck]"), function (btn) {
      var root = btn.closest(".card") || document;
      var cards = cardsFromDeck(root);
      btn.href = massBoxUrl(cards);
      btn.target = "_blank";
      btn.rel = REL;
      btn.addEventListener("click", function (e) {
        copyText(massText(cards));
      });
    });

    Array.prototype.forEach.call(document.querySelectorAll("[data-copy-deck]"), function (btn) {
      btn.addEventListener("click", function () {
        var root = btn.closest(".card") || document;
        var ok = copyText(massText(cardsFromDeck(root)));
        btn.textContent = ok ? "Copied" : "Copy list";
        setTimeout(function () { btn.textContent = "Copy list"; }, 1400);
      });
    });
  }

  window.MTG_TCGPLAYER = {
    affiliate: affiliate,
    cardSearchUrl: cardSearchUrl,
    massBoxUrl: massBoxUrl
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", enhance);
  } else {
    enhance();
  }
})();
