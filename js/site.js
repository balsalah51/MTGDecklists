(function () {
  var THEME_COOKIE = "mtg-theme";
  var THEME_MAX_AGE = 365 * 24 * 60 * 60;
  var PAGE_SIZE = 48;

  function readTheme() {
    var match = document.cookie.match(/(?:^|; )mtg-theme=(dark|light)/);
    if (match) return match[1];
    return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
  }

  function applyTheme(theme) {
    theme = theme === "dark" ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", theme);
    document.documentElement.style.colorScheme = theme;
    document.cookie = THEME_COOKIE + "=" + theme + "; path=/; max-age=" + THEME_MAX_AGE + "; SameSite=Lax";
    var btn = document.getElementById("theme-toggle");
    if (btn) {
      var dark = theme === "dark";
      btn.setAttribute("aria-pressed", dark ? "true" : "false");
      btn.setAttribute("aria-label", dark ? "Switch to daylight" : "Switch to night library");
    }
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", theme === "dark" ? "#161213" : "#9c1c28");
  }

  applyTheme(readTheme());
  var toggle = document.getElementById("theme-toggle");
  if (toggle) {
    toggle.addEventListener("click", function () {
      applyTheme(readTheme() === "dark" ? "light" : "dark");
    });
  }

  var year = document.getElementById("year");
  if (year) year.textContent = String(new Date().getFullYear());

  document.documentElement.classList.add("is-ready");

  function colorMatch(colors, needle) {
    if (!needle || needle === "all") return true;
    colors = colors || "";
    if (needle.length === 1) return colors.indexOf(needle) >= 0;
    return colors === needle;
  }

  function setupPager(list) {
    if (!list) return function () {};
    var shown = PAGE_SIZE;
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "show-more";
    btn.hidden = true;
    list.after(btn);

    function visibleItems() {
      return Array.prototype.filter.call(list.querySelectorAll(".recent-item"), function (el) {
        return !el.classList.contains("hidden-row");
      });
    }

    function apply() {
      var vis = visibleItems();
      vis.forEach(function (el, i) {
        if (i >= shown) el.classList.add("page-hidden");
        else el.classList.remove("page-hidden");
      });
      Array.prototype.forEach.call(list.querySelectorAll(".recent-item.hidden-row"), function (el) {
        el.classList.remove("page-hidden");
      });
      var more = vis.length - shown;
      if (more > 0) {
        btn.hidden = false;
        btn.textContent = "Show " + Math.min(PAGE_SIZE, more) + " more · " + vis.length + " lists in this hall";
      } else {
        btn.hidden = true;
      }
    }

    btn.addEventListener("click", function () {
      shown += PAGE_SIZE;
      apply();
    });

    return function resetAndApply() {
      shown = PAGE_SIZE;
      apply();
    };
  }

  var list = document.querySelector(".recent-list");
  var paginate = setupPager(list);

  function applyColorFilter(color) {
    Array.prototype.forEach.call(document.querySelectorAll("[data-colors]"), function (row) {
      var has = colorMatch(row.getAttribute("data-colors") || "", color);
      row.classList.toggle("hidden-row", !has);
    });
    Array.prototype.forEach.call(document.querySelectorAll(".filter-bar [data-color]"), function (btn) {
      var key = btn.getAttribute("data-color") || "";
      btn.classList.toggle("is-on", color ? key === color : key === "all");
    });
    paginate();
  }

  var params = new URLSearchParams(location.search);
  var color = params.get("color");
  applyColorFilter(color);

  Array.prototype.forEach.call(document.querySelectorAll(".filter-bar [data-color]"), function (btn) {
    btn.addEventListener("click", function () {
      var next = btn.getAttribute("data-color") || "";
      if (next === "all") {
        history.replaceState(null, "", location.pathname);
        applyColorFilter("");
        return;
      }
      history.replaceState(null, "", location.pathname + "?color=" + encodeURIComponent(next));
      applyColorFilter(next);
    });
  });

  var q = document.getElementById("q") || document.getElementById("home-q");
  var status = document.getElementById("search-status");
  var results = document.getElementById("search-results");
  if (!results) return;

  function render(items, query) {
    results.innerHTML = "";
    if (!items.length) {
      if (status) status.textContent = query ? "No lists matched “" + query + "”." : "Type a format, color, player, or card.";
      return;
    }
    if (status) status.textContent = items.length + " result" + (items.length === 1 ? "" : "s");
    items.slice(0, 80).forEach(function (item) {
      var a = document.createElement("a");
      a.className = "item";
      a.href = item.url;
      a.innerHTML = "<div><div>" + item.title + "</div><div class='muted'>" + item.meta + "</div></div><div class='link'>Open →</div>";
      results.appendChild(a);
    });
  }

  fetch("/data/search.json").then(function (r) { return r.json(); }).then(function (index) {
    function run() {
      var query = (params.get("q") || (q && q.value) || "").trim().toLowerCase();
      if (q && !q.value && params.get("q")) q.value = params.get("q");
      if (!query) {
        render([], "");
        return;
      }
      var hits = index.filter(function (item) {
        return (item.hay || "").indexOf(query) >= 0;
      });
      render(hits, query);
    }
    if (q) {
      q.addEventListener("input", run);
      var form = q.closest("form");
      if (form) form.addEventListener("submit", function (e) {
        if (location.pathname.indexOf("search") >= 0) {
          e.preventDefault();
          history.replaceState(null, "", "/search.html?q=" + encodeURIComponent(q.value));
          params = new URLSearchParams(location.search);
          run();
        }
      });
    }
    run();
  }).catch(function () {
    if (status) status.textContent = "Search index could not load.";
  });
})();
