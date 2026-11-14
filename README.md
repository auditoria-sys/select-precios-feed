# Select · precios de la web para los correos (Black Friday 2026)

Cada 20 minutos, `feed_precios.py` lee el catálogo público de selecteu.com y calcula, por producto con stock, el precio
«Desde» que muestra la web, el precio tachado y el % de descuento. El resultado (`precios-select.json`) lo descarga
Klaviyo como Web Feed (`SELECT_PRECIOS_WEB`) para que las tarjetas de producto de los correos enseñen el precio de la web
en el momento del envío. Si un pase sale raro, no se publica y queda la última versión buena.

Mantiene: Billber (agencia). Se apaga después del 1-dic-2026.
