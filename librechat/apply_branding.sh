#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INDEX_FILE="/app/client/dist/index.html"

docker cp "$APP_DIR/images/logo-app.png" librechat-api-local:/app/client/dist/assets/analitrics-logo.png
docker cp "$APP_DIR/images/logo-login.png" librechat-api-local:/app/client/dist/assets/analitrics-logo-login.png
docker cp "$APP_DIR/images/logo-app.png" librechat-api-local:/app/client/dist/assets/analitrics-favicon.png

docker exec librechat-api-local sh -lc "python - <<'PY'
from pathlib import Path
import re

path = Path('$INDEX_FILE')
html = path.read_text()

start = '<!-- ANALITRICS_BRANDING_START -->'
end = '<!-- ANALITRICS_BRANDING_END -->'

if start in html and end in html:
    before, rest = html.split(start, 1)
    _, after = rest.split(end, 1)
    html = before + after

html = html.replace('<title>LibreChat</title>', '<title>Analitrics | Chat de datos</title>')
html = html.replace('assets/favicon-32x32.png', 'assets/analitrics-favicon.png')
html = html.replace('assets/favicon-16x16.png', 'assets/analitrics-favicon.png')
html = html.replace('assets/apple-touch-icon-180x180.png', 'assets/analitrics-favicon.png')
html = re.sub(r'<script id="vite-plugin-pwa:register-sw" src="\./registerSW\.js"></script>', '', html)

injection = '''
<!-- ANALITRICS_BRANDING_START -->
<style>
  :root {
    --analitrics-bg: #f7f8fc;
    --analitrics-panel: #0b0327;
    --analitrics-panel-soft: #13073b;
    --analitrics-accent: #6d31f4;
    --analitrics-accent-2: #8a50ff;
    --analitrics-text: #111027;
    --analitrics-muted: #5c5771;
  }

  body {
    background: var(--analitrics-bg) !important;
    color: var(--analitrics-text) !important;
  }

  a[href^="/agents"],
  a[href^="/projects"],
  a[href^="/prompts"],
  a[href^="/bookmarks"],
  a[href^="/files"],
  a[href^="/skills"],
  a[href^="/mcp"],
  a[href^="/api-dashboard"],
  a[href^="/dashboard"] {
    display: none !important;
  }
</style>
<script>
  (function () {
    var applyBranding = function () {
      try {
        document.title = 'Analitrics | Chat de datos';

        document.querySelectorAll('img').forEach(function (img) {
          var src = img.getAttribute('src') || '';
          var alt = (img.getAttribute('alt') || '').toLowerCase();
          if (src.indexOf('logo.svg') !== -1 || alt.indexOf('librechat') !== -1) {
            img.setAttribute('src', '/assets/analitrics-logo.png');
            img.style.objectFit = 'contain';
            img.style.maxWidth = '180px';
            img.style.height = 'auto';
          }
        });

        document.querySelectorAll('a').forEach(function (link) {
          var href = link.getAttribute('href') || '';
          if (
            href.indexOf('/agents') === 0 ||
            href.indexOf('/projects') === 0 ||
            href.indexOf('/prompts') === 0 ||
            href.indexOf('/bookmarks') === 0 ||
            href.indexOf('/files') === 0 ||
            href.indexOf('/skills') === 0 ||
            href.indexOf('/mcp') === 0 ||
            href.indexOf('/api-dashboard') === 0 ||
            href.indexOf('/dashboard') === 0
          ) {
            var row = link.closest('a, button, li, div');
            if (row) {
              row.style.display = 'none';
            }
          }
        });

        var welcomeNodes = Array.from(document.querySelectorAll('h1,h2,h3,p,span,div'));
        welcomeNodes.forEach(function (node) {
          if (node.childElementCount > 4) return;
          if ((node.textContent || '').trim() === 'LibreChat listo para analizar CSV y Excel.') {
            node.textContent = 'Analitrics listo para analizar CSV y Excel.';
          }
        });
      } catch (err) {
        console.error('Branding error', err);
      }
    };

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', applyBranding, { once: true });
    } else {
      applyBranding();
    }
  })();
</script>
<!-- ANALITRICS_BRANDING_END -->
'''

html = html.replace('</head>', injection + '\n</head>')
path.write_text(html)
PY"
