# -*- coding: utf-8 -*-
"""Feed de precios de la WEB para las tarjetas de producto de los correos BF26 de Select (11-nov).

POR QUÉ: en Klaviyo el `catalog_item` de Shopify solo trae `metadata.price` = precio de la PRIMERA variante y
`compare_at_price`; ni variantes, ni disponibilidad por talla, ni el mínimo. La web pinta «Desde» = el precio más
bajo entre las tallas DISPONIBLES (en la muestra del 9-nov coincidían 7 de 30). Este script calcula ese «Desde»
para todo el catálogo con stock y lo deja en un JSON que Klaviyo descarga como **Web Feed**
(`feeds.SELECT_PRECIOS_WEB`): Klaviyo lo refresca cada 15 min y cada envío usa la última copia buena, así que el
precio del correo es el de la web en el momento del envío sin tocar las plantillas.

QUÉ ESCRIBE (JSON compacto, ~100-150 B por producto; límite de Klaviyo: 4 MB):
  {"v": 1, "ts": "2026-11-11T09:00Z", "n": <productos con stock>,
   "p": {"<handle>": {"d": "110", "t": "135", "x": 20}, "<otro>": {"d": "99,95", "t": "", "de": "99.95", "x": 0}, ...},
   "r": {"c3_m2": [{"h", "n", "m", "f", "d", "t", "x"} ×4], "c8_m2": [...]}}
  Medido el 10-nov: 86 páginas de /products.json, 21.121 productos con stock, ~1,7 MB, ~6 min a 4 s por petición.
  · d / t   = «Desde» y tachado con coma decimal y sin ",00" (ES, FR, DE, IT, PT: «110 €», «99,95 €»)
  · de / te = lo mismo con punto decimal, para el EN («€99.95»); SOLO si hay decimales (si no, el EN usa d / t)
  · t = "" si esa talla no tiene precio anterior más alto (la plantilla no pinta tachado)
  · x = el mayor descuento (%) entre las tallas disponibles = lo que pinta la pastilla «HASTA −X %» de la web
  · r = las rejillas fijas de C3·M2 y C8·M2: los N primeros CON STOCK de la colección (o FIJOS), en el momento de
        refrescar. Así una rejilla nunca enseña una zapatilla agotada ni un precio viejo.
  Regla de cálculo idéntica a `actualizar_precios.py` (la que dio la tarjeta del C3 que aprobó la diseñadora:
  «Desde 110 €» + «135 €» tachado): Desde = variante disponible más barata; tachado = el compare_at de ESA variante.

SEGURIDAD (nunca un precio inventado ni viejo):
  · Si algo falla (Shopify limita, catálogo raro, rejilla incompleta, caída >30 % frente al feed anterior), NO
    publica: sale con código ≠ 0 y Klaviyo sigue con la última copia buena.
  · Un producto que no está en `p` (agotado o nuevo) → la tarjeta dice «Ver precio →» (enlace), nunca un número.

USO
  python3 feed_precios.py --salida precios-select.json            # calcula y escribe en local (simulación)
  python3 feed_precios.py --salida precios-select.json --gist <ID> # y además publica en el gist (GIST_TOKEN o gh)
  python3 feed_precios.py --comprobar precios-select.json          # valida un feed ya escrito
  python3 feed_precios.py --mercados precios-select.json           # ¿el «Desde» de /en-en, /fr-fr… es el mismo?
Variables: GIST_TOKEN (token con alcance «gist»; si falta, usa `gh api`), FEED_ESPERA (s entre peticiones, 2.5).
Solo biblioteca estándar (corre igual en el Mac, en Hetzner o en GitHub Actions).
"""
import argparse, json, os, re, subprocess, sys, time, urllib.error, urllib.request
from datetime import datetime, timezone

TIENDA = 'https://selecteu.com'
UA = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/130.0 Safari/537.36', 'Accept': 'application/json', 'Accept-Language': 'es-ES,es;q=0.9'}
ESPERA = float(os.environ.get('FEED_ESPERA', '4'))     # medido 10-nov: 87 peticiones a 4 s, cero 429 (a <1,5 s, 429)
FICHERO_GIST = 'precios-select.json'
REJILLAS = {           # clave del feed: (colección, nº de tarjetas)  — las mismas que actualizar_precios.PARRILLAS
    'c3_m2': ('mas-vendido', 4),
    'c8_m2': ('mas-vendido', 4),
}
FIJOS = {}             # p. ej. {'c3_m2': ['handle-1', 'handle-2', ...]}: si alguno está agotado, se rellena con la colección
LIM_NOMBRE = 40        # = generar.LIM_NOMBRE (2 líneas a 14 px en la tarjeta de 160 px)
MIN_PRODUCTOS = 15000  # 21.121 el 10-nov: por debajo, el catálogo ha venido cortado o raro: no se publica
MAX_CAIDA = 0.30       # si hay un 30 % menos de productos que en el feed anterior, no se publica
MAX_BYTES = 3_500_000  # margen bajo los 4 MB de Klaviyo


LIMITE = time.monotonic() + float(os.environ.get('FEED_LIMITE_S', '1080'))  # 18 min: aborta limpio antes del job


def get(url, intentos=8):
    """GET con espera fija entre peticiones y respeto del Retry-After de Shopify (429). Solo reintenta 429/5xx/red."""
    for i in range(intentos):
        if time.monotonic() > LIMITE:
            raise RuntimeError('se acabó el tiempo del pase; no se publica')
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                txt = r.read().decode()
            time.sleep(ESPERA)
            return json.loads(txt)
        except urllib.error.HTTPError as e:
            if e.code != 429 and e.code < 500:
                raise
            try:
                espera = min(int(e.headers.get('Retry-After') or 0), 60)
            except ValueError:
                espera = 0
            espera = espera or min(10 * 2 ** i, 60)
            print(f'  {e.code} en {url} · espero {espera + 5} s', file=sys.stderr, flush=True)
            time.sleep(espera + 5)
        except Exception as e:  # red, JSON cortado…
            print(f'  {type(e).__name__} en {url} · reintento', file=sys.stderr, flush=True)
            time.sleep(min(10 * 2 ** i, 120))
    raise RuntimeError('Shopify no responde: ' + url)


def fmt(v, dec=','):
    """110.0 → «110» · 99.95 → «99,95» (o «99.95» con dec='.'). Sin separador de miles (1290 → «1290»)."""
    s = f'{v:.2f}'
    if s.endswith('.00'):
        s = s[:-3]
    return s.replace('.', dec)


def recorta(nombre, n=LIM_NOMBRE):
    nombre = re.sub(r'\s+-\s+[A-Z0-9]{5,}$', '', nombre.split(' | ')[0].strip())  # «… - JI0189»: sin SKU
    return nombre if len(nombre) <= n else nombre[:n].rsplit(' ', 1)[0] + '…'


def precio(prod):
    """Lo que pinta la tarjeta de la web, o None si no queda ninguna talla."""
    disp = [v for v in prod['variants'] if v.get('available')]
    if not disp:
        return None
    cent = lambda x: round(float(x) * 100) if x not in (None, '') else 0   # céntimos enteros, como actualizar_precios
    disp = [v for v in disp if cent(v['price']) > 0]
    if not disp:
        return None
    vmin = min(disp, key=lambda v: (cent(v['price']), -cent(v.get('compare_at_price'))))
    dc, tc = cent(vmin['price']), cent(vmin.get('compare_at_price'))
    x = max([(cent(v.get('compare_at_price')) - cent(v['price'])) * 100 // cent(v.get('compare_at_price'))
             for v in disp if cent(v.get('compare_at_price')) > cent(v['price'])] or [0])
    d, t = dc / 100, (tc / 100 if tc > dc else 0)
    r = {'d': fmt(d), 't': fmt(t) if t else '', 'x': x}
    if ',' in r['d']:          # «de»/«te» (punto decimal, EN) solo si hay decimales: 11 de 21.121 el 10-nov.
        r['de'] = fmt(d, '.')  # La plantilla EN hace «{{ v.de|default:v.d }}»: el feed pesa un 20 % menos.
    if ',' in r['t']:
        r['te'] = fmt(t, '.')
    return r


def catalogo():
    """Todo /products.json (250 por página) → {handle: producto}."""
    todos, pag = {}, 1
    while True:
        lote = get(f'{TIENDA}/products.json?limit=250&page={pag}')['products']
        if not lote:
            break
        for pr in lote:
            todos[pr['handle']] = pr
        print(f'  página {pag}: {len(lote)} productos', file=sys.stderr, flush=True)
        if len(lote) < 250:
            break
        pag += 1
    return todos


def foto(pr):
    src = (pr.get('images') or [{}])[0].get('src', '')
    if not src:
        return ''
    src = 'https:' + src if src.startswith('//') else src
    return src + ('&' if '?' in src else '?') + 'width=600&height=600&pad_color=ffffff'


def construir():
    todos = catalogo()
    p = {h: x for h, x in ((h, precio(pr)) for h, pr in todos.items()) if x}
    r = {}
    orden_col = {}
    for clave, (col, n) in REJILLAS.items():
        if col not in orden_col:
            orden_col[col] = [x['handle'] for x in get(f'{TIENDA}/collections/{col}/products.json?limit={n + 26}')['products']]
        tarjetas = []
        for h in FIJOS.get(clave, []) + orden_col[col]:
            if h in p and h in todos and foto(todos[h]) and h not in [t['h'] for t in tarjetas]:
                pr = todos[h]
                tarjetas.append(dict(h=h, n=recorta(pr['title']), m=pr['vendor'].upper(), f=foto(pr), **p[h]))
            if len(tarjetas) == n:
                break
        r[clave] = tarjetas
    return {'v': 1, 'ts': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%MZ'), 'n': len(p), 'p': p, 'r': r}


def comprobar(feed, anterior=None):
    """Lista de motivos para NO publicar (vacía = se puede publicar)."""
    mal = []
    if feed.get('n', 0) < MIN_PRODUCTOS:
        mal.append(f"solo {feed.get('n')} productos con stock (mínimo {MIN_PRODUCTOS})")
    for clave, (_, n) in REJILLAS.items():
        if len(feed.get('r', {}).get(clave, [])) != n:
            mal.append(f'rejilla {clave} con {len(feed.get("r", {}).get(clave, []))} de {n} tarjetas')
    num = lambda v: float(v.replace(',', '.'))
    def raro(x):
        return (not re.fullmatch(r'\d+(,\d\d)?', x.get('d', '')) or num(x['d']) <= 0
                or (x.get('t') and (not re.fullmatch(r'\d+(,\d\d)?', x['t']) or num(x['t']) <= num(x['d'])))
                or not isinstance(x.get('x'), int) or not 0 <= x['x'] < 100)
    malos = [h for h, x in feed.get('p', {}).items() if raro(x)]
    malos += [f"{k}:{t.get('h')}" for k, ts in feed.get('r', {}).items() for t in ts if raro(t) or not t.get('f') or not t.get('h')]
    if malos:
        mal.append(f'{len(malos)} precios raros, p. ej. {malos[:3]}')
    if anterior and anterior.get('n') and feed.get('n', 0) < anterior['n'] * (1 - MAX_CAIDA):
        mal.append(f"caída de productos: {anterior['n']} → {feed.get('n')}")
    tam = len(json.dumps(feed, ensure_ascii=False, separators=(',', ':')).encode())
    if tam > MAX_BYTES:
        mal.append(f'{tam} B (máximo {MAX_BYTES})')
    return mal


def publicar_gist(gist, texto):
    cuerpo = json.dumps({'files': {FICHERO_GIST: {'content': texto}}}).encode()
    tok = os.environ.get('GIST_TOKEN')
    if tok:
        req = urllib.request.Request(f'https://api.github.com/gists/{gist}', data=cuerpo, method='PATCH',
                                     headers={'Authorization': f'Bearer {tok}', 'Accept': 'application/vnd.github+json'})
        urllib.request.urlopen(req, timeout=30).read()
    else:
        subprocess.run(['gh', 'api', '-X', 'PATCH', f'gists/{gist}', '--input', '-'], input=cuerpo, check=True,
                       stdout=subprocess.DEVNULL)


def leer_gist(gist):
    """El feed publicado ahora (para comparar), o None."""
    try:
        h = {'User-Agent': UA['User-Agent'], 'Accept': 'application/vnd.github+json'}
        if os.environ.get('GIST_TOKEN'):
            h['Authorization'] = 'Bearer ' + os.environ['GIST_TOKEN']
        with urllib.request.urlopen(urllib.request.Request(f'https://api.github.com/gists/{gist}', headers=h), timeout=20) as r:
            raw = json.loads(r.read().decode())['files'][FICHERO_GIST]['raw_url']
        with urllib.request.urlopen(urllib.request.Request(raw, headers={'User-Agent': UA['User-Agent']}), timeout=20) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def mercados(feed_path, n=6):
    """Comprueba que el «Desde» de los mercados de idioma (/en-en, /fr-fr…) es el MISMO que el del feed (raíz, ES).
    Si alguno difiere, el feed único no vale para ese idioma: hay que publicar un feed por mercado."""
    feed = json.load(open(feed_path))
    hs = [t['h'] for t in feed['r']['c3_m2']] + list(feed['p'])[:: max(1, len(feed['p']) // n)][:n] + sys.argv[sys.argv.index('--mercados') + 2:]
    dif = 0
    for h in hs:
        base = feed['p'].get(h, {}).get('d')
        for m in ('', '/en-en', '/fr-fr', '/de-de', '/it-it', '/pt-pt'):   # '' = la web en español (raíz)
            d = get(f'{TIENDA}{m}/products/{h}.js')
            disp = [v['price'] for v in d['variants'] if v.get('available')]
            web = fmt(min(disp) / 100) if disp else None
            ok = web == base
            dif += not ok
            print(f"{'OK ' if ok else 'DIF'} {m:7} {h[:50]:50} feed {base} · mercado {web} {d.get('currency', '')}")
    print('mercados con precio distinto:', dif)
    return dif


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--salida', default='precios-select.json')
    ap.add_argument('--gist', help='id del gist donde se publica (sin él, solo escribe en local)')
    ap.add_argument('--comprobar', help='valida un feed ya escrito y sale')
    ap.add_argument('--mercados', help='compara el «Desde» del feed con /en-en, /fr-fr, /de-de, /it-it, /pt-pt y sale')
    a, _extra = ap.parse_known_args()   # tras --mercados <feed> pueden ir handles extra a comprobar
    if a.mercados:
        sys.exit(1 if mercados(a.mercados) else 0)
    if a.comprobar:
        mal = comprobar(json.load(open(a.comprobar)))
        print('OK' if not mal else '\n'.join(mal))
        sys.exit(1 if mal else 0)
    try:
        feed = construir()
    except Exception as e:
        print('NO SE PUBLICA:', e, file=sys.stderr)
        sys.exit(2)
    anterior = leer_gist(a.gist) if a.gist else (json.load(open(a.salida)) if os.path.exists(a.salida) else None)
    if a.gist and anterior is None:
        print('NO SE PUBLICA: no pude leer el feed publicado para comparar', file=sys.stderr)
        sys.exit(4)
    mal = comprobar(feed, anterior)
    texto = json.dumps(feed, ensure_ascii=False, separators=(',', ':'))
    if mal:
        print('NO SE PUBLICA:\n  ' + '\n  '.join(mal), file=sys.stderr)
        open(a.salida + '.rechazado', 'w').write(texto)
        sys.exit(3)
    open(a.salida, 'w').write(texto)
    print(f"{feed['ts']} · {feed['n']} productos con stock · {len(texto.encode()) // 1024} KB → {a.salida}")
    for clave, ts in feed['r'].items():
        print(f'  {clave}: ' + ' | '.join(f"{t['n'][:28]} desde {t['d']} ({t['t'] or '—'}) −{t['x']}%" for t in ts))
    if a.gist:
        publicar_gist(a.gist, texto)
        print(f'  publicado en el gist {a.gist}')


if __name__ == '__main__':
    main()
