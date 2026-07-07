"""Silnik raportów PDF dla aplikacji Anbernic — tu używany przez AnberISA
(ekran INWERSJA, raport z rozpisanymi obliczeniami); silnik jest wspólny
z AnberWM / AnberPKM (reportlab).

Wspólny generator: tytuł, autor, schemat obciążenia (obraz), tabela danych
wejściowych, obliczenia (nazwa = wzór = podstawienie = wynik), warunki
(spełnione / nie) oraz wnioski. Treść per-moduł dostarcza aplikacja w `meta`.

meta = {
  'tytul':    str,                       # co liczone
  'autor':    str, 'tel': str, 'data': str,
  'diagram':  ścieżka PNG | None,        # schemat obciążenia
  'zmienne':  [(symbol, opis, wartość, jednostka), ...],
  'wzory':    [(nazwa, wzór, podstawienie, wynik), ...],
  'warunki':  [(opis, spełniony_bool), ...],
  'wnioski':  str,
}
"""
from __future__ import annotations
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, Image as RLImage)
from reportlab.lib.styles import ParagraphStyle
from PIL import Image as PILImage

_FONTS_OK = False
_FDIR = '/usr/share/fonts/truetype/dejavu'
GREEN = colors.HexColor('#1B5E20')
GOLD  = colors.HexColor('#B8860B')
REDC  = colors.HexColor('#B71C1C')
LITE  = colors.HexColor('#E8F5E9')


def _ensure_fonts():
    global _FONTS_OK
    if _FONTS_OK:
        return
    pdfmetrics.registerFont(TTFont('DejaVu', f'{_FDIR}/DejaVuSans.ttf'))
    pdfmetrics.registerFont(TTFont('DejaVu-Bold', f'{_FDIR}/DejaVuSans-Bold.ttf'))
    pdfmetrics.registerFont(TTFont('DejaVuMono', f'{_FDIR}/DejaVuSansMono.ttf'))
    _FONTS_OK = True


def _esc(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


_PLT = None


def diagram_to_png(draw_fn, vals, results, w, h, path, fontsize=12):
    """Renderuje schemat (funkcja draw_* aplikacji) na BIAŁE tło, bez czarnych
    wypełnień: rysuje na warstwie przezroczystej i spłaszcza na biel
    (otwory/dziury fill=(0,0,0,0) stają się białe)."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new('RGBA', (w, h), (255, 255, 255, 0))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(f'{_FDIR}/DejaVuSansMono.ttf', fontsize)
    c = {'fill': (210, 235, 218), 'out': (27, 94, 32), 'acc': (176, 110, 0),
         'dim': (95, 95, 95), 'font': font, 'raport': True}
    draw_fn(d, vals, results, 4, 4, w - 8, h - 8, c)
    bg = Image.new('RGB', (w, h), (255, 255, 255))
    bg.paste(img, (0, 0), img)
    bg.save(path)
    return path


def _render_mixed(s, path, color='black', fontsize=11):
    """Renderuje tekst z wtrąceniami matematycznymi ($...$) do PNG. (w,h) px|None."""
    global _PLT
    if _PLT is None:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        _PLT = plt
    fig = _PLT.figure(figsize=(0.01, 0.01))
    fig.text(0, 0, s, fontsize=fontsize, color=color)
    try:
        fig.savefig(path, dpi=200, bbox_inches='tight', pad_inches=0.03, transparent=True)
        _PLT.close(fig)
        return PILImage.open(path).size
    except Exception:
        _PLT.close(fig)
        return None


def _render_eq(latex, path, fontsize=16):
    """Renderuje równanie LaTeX (mathtext) do PNG. Zwraca (w,h) px lub None."""
    global _PLT
    if _PLT is None:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        _PLT = plt
    fig = _PLT.figure(figsize=(0.01, 0.01))
    fig.text(0, 0, f'${latex}$', fontsize=fontsize)
    try:
        fig.savefig(path, dpi=200, bbox_inches='tight', pad_inches=0.03, transparent=True)
        _PLT.close(fig)
        return PILImage.open(path).size
    except Exception:
        _PLT.close(fig)
        return None


def generuj_pdf(sciezka, meta):
    """Buduje PDF wg meta. Zwraca ścieżkę."""
    _ensure_fonts()
    doc = SimpleDocTemplate(str(sciezka), pagesize=A4,
                            leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=13 * mm, bottomMargin=13 * mm,
                            title=meta.get('tytul', 'Raport'))
    H   = ParagraphStyle('H',  fontName='DejaVu-Bold', fontSize=14, leading=17, textColor=GREEN, spaceAfter=5)
    sub = ParagraphStyle('sub', fontName='DejaVu', fontSize=9, textColor=colors.grey, spaceAfter=8)
    sec = ParagraphStyle('sec', fontName='DejaVu-Bold', fontSize=11, textColor=GREEN,
                         spaceBefore=9, spaceAfter=3)
    body = ParagraphStyle('body', fontName='DejaVu', fontSize=9.5, leading=13)
    monoS = ParagraphStyle('mono', fontName='DejaVuMono', fontSize=8.6, leading=12.5)
    opisE = ParagraphStyle('opisE', fontName='DejaVu', fontSize=8.5,
                           textColor=colors.HexColor('#555555'), spaceBefore=3, spaceAfter=0)
    cellH = ParagraphStyle('cellH', fontName='DejaVu-Bold', fontSize=8.5, textColor=colors.white)
    cell  = ParagraphStyle('cell', fontName='DejaVu', fontSize=8.5, leading=11)

    el = []
    el.append(Paragraph(_esc(meta.get('tytul', 'Raport obliczeniowy')), H))
    el.append(Paragraph(
        f"Wykonał: <b>{_esc(meta.get('autor',''))}</b> &nbsp;|&nbsp; "
        f"Tel: {_esc(meta.get('tel',''))} &nbsp;|&nbsp; {_esc(meta.get('data',''))}", sub))

    # ── Schemat obciążenia ──
    if meta.get('diagram'):
        el.append(Paragraph('1. Schemat obciążenia', sec))
        try:
            iw, ih = PILImage.open(meta['diagram']).size
            w_mm = 150
            h_mm = w_mm * ih / iw
            el.append(RLImage(meta['diagram'], width=w_mm * mm, height=h_mm * mm))
        except Exception:
            pass

    # ── Dane wejściowe ──
    el.append(Paragraph('2. Dane wejściowe (przyjęte zmienne)', sec))
    rows = [[Paragraph('Wielkość', cellH), Paragraph('Symbol', cellH),
             Paragraph('Wartość', cellH), Paragraph('Jedn.', cellH)]]
    for sym, opis, val, unit in meta.get('zmienne', []):
        rows.append([Paragraph(_esc(opis), cell), Paragraph(_esc(sym), cell),
                     Paragraph(_esc(val), cell), Paragraph(_esc(unit), cell)])
    t = Table(rows, colWidths=[88 * mm, 24 * mm, 45 * mm, 18 * mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), GREEN),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LITE]),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#A5D6A7')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 2), ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    el.append(t)

    import tempfile, shutil
    _tmpd = tempfile.mkdtemp(prefix='rap_')
    _ic = [0]

    def _nf(pref):
        _ic[0] += 1
        return f'{_tmpd}/{pref}{_ic[0]}.png'

    def _img(path, sz, maxw=172):
        if not sz:
            return
        iw, ih = sz
        w_mm = iw / 7.874              # naturalna skala (dpi=200) = jednolity font
        h_mm = ih / 7.874
        if w_mm > maxw:
            k = maxw / w_mm
            w_mm *= k; h_mm *= k
        el.append(RLImage(path, width=w_mm * mm, height=h_mm * mm, hAlign='LEFT'))

    # ── Obliczenia ── (równania + opisy renderowane GRAFICZNIE)
    el.append(Paragraph('3. Obliczenia (wzór = podstawienie = wynik)', sec))
    wzory_tex = meta.get('wzory_tex')
    if wzory_tex:
        for item in wzory_tex:
            if isinstance(item, (tuple, list)):
                opis, tex = item[0], item[1]
            else:
                opis, tex = None, item
            if opis:
                po = _nf('op')
                _img(po, _render_mixed('• ' + opis, po, color='#555555', fontsize=9.5))
            pq = _nf('eq')
            _img(pq, _render_eq(tex, pq))
            el.append(Spacer(1, 4))
    else:
        for nazwa, wzor, podst, wynik in meta.get('wzory', []):
            line = f"{_esc(nazwa)} = {_esc(wzor)}"
            if podst:
                line += f" = {_esc(podst)}"
            line += f" = <b>{_esc(wynik)}</b>"
            el.append(Paragraph(line, monoS))
            el.append(Spacer(1, 2))

    # ── Warunki ── (math GRAFICZNIE; kolor zależny od spełnienia)
    el.append(Paragraph('4. Warunki', sec))
    for opis, ok in meta.get('warunki', []):
        col = '#1B5E20' if ok else '#B71C1C'
        suf = '    — SPEŁNIONY' if ok else '    — NIESPEŁNIONY'
        pw = _nf('wa')
        _img(pw, _render_mixed(opis + suf, pw, color=col, fontsize=11))
        el.append(Spacer(1, 3))

    # ── Wnioski ── (math GRAFICZNIE)
    el.append(Paragraph('5. Wnioski', sec))
    wszystkie_ok = all(ok for _, ok in meta.get('warunki', [])) if meta.get('warunki') else True
    col = '#1B5E20' if wszystkie_ok else '#B71C1C'
    for part in meta.get('wnioski', '').replace('. ', '.\n').split('\n'):
        part = part.strip()
        if not part:
            continue
        pwn = _nf('wn')
        _img(pwn, _render_mixed(part, pwn, color=col, fontsize=11))
        el.append(Spacer(1, 1))

    doc.build(el)
    shutil.rmtree(_tmpd, ignore_errors=True)
    return str(sciezka)
