#!/usr/bin/env bash
# Gera images/capa.jpg (1600×2500, padrão da casa) a partir de images/capa.html
# usando o Chrome headless. As fontes são carregadas de ../fonts/ pelo próprio
# capa.html (@font-face), então não precisam estar instaladas no sistema.
#
# Uso:  ./code/make_cover.sh
#       CHROME=/caminho/para/chromium ./code/make_cover.sh   # Linux / outro binário
#       CHROME_FLAGS="--no-sandbox" ./code/make_cover.sh         # em contêiner rodando como root
# Nota: no modo --headless=new do Chrome, --window-size pode incluir a moldura
# da janela e cortar a base da capa; se isso acontecer, use o binário
# headless_shell do Playwright/Chromium (CHROME=.../headless_shell).
set -euo pipefail
cd "$(dirname "$0")/../images"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
CHROME_FLAGS="${CHROME_FLAGS:-}"
"$CHROME" $CHROME_FLAGS --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=1 \
  --allow-file-access-from-files \
  --window-size=1600,2500 --screenshot="capa.png" "file://$PWD/capa.html" 2>/dev/null
if command -v sips >/dev/null 2>&1; then
  sips -s format jpeg -s formatOptions 88 capa.png --out capa.jpg >/dev/null
  rm -f capa.png
  echo "capa.jpg: $(sips -g pixelWidth -g pixelHeight capa.jpg | tail -2 | tr -s ' \n' ' ')"
else
  python3 - <<'PY'
from PIL import Image
im = Image.open("capa.png").convert("RGB")
im.save("capa.jpg", "JPEG", quality=88, optimize=True)
print("capa.jpg:", im.size)
PY
  rm -f capa.png
fi
