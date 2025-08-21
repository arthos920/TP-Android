# ScreenshotOnKeywordFail.py
from robot.api import logger
from robot.libraries.BuiltIn import BuiltIn
import os, re
from datetime import datetime

class ScreenshotOnKeywordFail:
    ROBOT_LISTENER_API_VERSION = 2

    def __init__(self, outdir=None, prefix='kwfail'):
        self.builtin = BuiltIn()
        self.outdir = outdir or self.builtin.get_variable_value('${OUTPUT DIR}')
        self.prefix = prefix

    def _safe(self, s):
        # nettoie noms de suite/test/keyword pour chemins de fichiers
        s = s.strip()
        s = re.sub(r'[\\/:"*?<>|]+', '_', s)   # caractères interdits
        s = re.sub(r'\s+', ' ', s)            # espaces multiples
        return s[:120] if len(s) > 120 else s

    def end_keyword(self, name, attrs):
        if attrs.get('status') != 'FAIL':
            return
        suite = self._safe(self.builtin.get_variable_value('${SUITE NAME}', default='suite'))
        test  = self._safe(self.builtin.get_variable_value('${TEST NAME}',  default='no-test'))
        kw    = self._safe(attrs.get('kwname') or name)
        ts    = datetime.now().strftime('%Y%m%d-%H%M%S-%f')

        folder = os.path.join(self.outdir, 'screenshots', suite, test)
        os.makedirs(folder, exist_ok=True)
        fname = f"{self.prefix}-{kw}-{ts}.png"
        path  = os.path.join(folder, fname)

        try:
            try:
                self.builtin.run_keyword('Take Screenshot', path)
            except Exception:
                # importe ScreenCapLibrary au besoin
                self.builtin.run_keyword('Import Library', 'ScreenCapLibrary')
                self.builtin.run_keyword('Take Screenshot', path)

            rel = os.path.relpath(path, self.outdir).replace('\\', '/')
            logger.info(f'Failure screenshot saved: {path}')
            logger.info(f'<a href="{rel}">Open screenshot</a>', html=True)
        except Exception as e:
            logger.warn(f'Listener failed to take screenshot: {e}')
