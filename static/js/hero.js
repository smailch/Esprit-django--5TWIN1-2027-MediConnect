(function () {
  var menu = document.getElementById('mobile-menu');
  var openBtn = document.getElementById('menu-open');
  var closeBtn = document.getElementById('menu-close');
  var video = document.getElementById('hero-video');

  // Mouvement réduit : la vidéo de fond reste à l'arrêt sur son image d'aperçu.
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)');
  function syncVideo() {
    if (!video) return;
    if (reduce.matches) { video.pause(); } else { video.play().catch(function () {}); }
  }
  syncVideo();
  if (reduce.addEventListener) reduce.addEventListener('change', syncVideo);

  if (!menu || !openBtn || !closeBtn) return;

  function setOpen(open) {
    menu.classList.toggle('is-open', open);
    openBtn.setAttribute('aria-expanded', String(open));
    document.body.style.overflow = open ? 'hidden' : '';
    (open ? closeBtn : openBtn).focus();
  }

  openBtn.addEventListener('click', function () { setOpen(true); });
  closeBtn.addEventListener('click', function () { setOpen(false); });
  menu.querySelectorAll('.menu-link').forEach(function (link) {
    link.addEventListener('click', function () { setOpen(false); });
  });

  document.addEventListener('keydown', function (e) {
    if (!menu.classList.contains('is-open')) return;
    if (e.key === 'Escape') { setOpen(false); return; }
    if (e.key !== 'Tab') return;
    // Garde le focus clavier à l'intérieur du menu ouvert.
    var items = menu.querySelectorAll('a[href], button');
    var first = items[0], last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });

  // Repasse en mise en page desktop : referme le menu s'il était ouvert.
  window.matchMedia('(min-width: 1024px)').addEventListener('change', function (m) {
    if (m.matches && menu.classList.contains('is-open')) setOpen(false);
  });
})();
