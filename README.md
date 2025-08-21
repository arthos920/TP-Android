# ScreenshotOnKeywordFail.py
from robot.api import logger
from robot.libraries.BuiltIn import BuiltIn
import os, re
from datetime import datetime

class ScreenshotOnKeywordFail:
    ROBOT_LISTENER_API_VERSION = 2

    def __init__(self, outdir=None, prefix='kwfail'):
        # Ne PAS toucher à BuiltIn ici -> pas de contexte encore !
        self._outdir_arg = outdir
        self.prefix = prefix
        self.outdir = None
        self._bi = None  # BuiltIn lazy

    # utilitaires
    def _safe(self, s):
        s = (s or '').strip()
        s = re.sub(r'[\\/:"*?<>|]+', '_', s)
        s = re.sub(r'\s+', ' ', s)
        return s[:120]

    def _ensure_bi_and_outdir(self):
        # Obtenir BuiltIn uniquement quand le contexte existe
        if self._bi is None:
            try:
                self._bi = BuiltIn()
            except Exception:
                self._bi = None
        if self.outdir is None:
            if self._outdir_arg:
                self.outdir = self._outdir_arg
            else:
                try:
                    if self._bi:
                        self.outdir = self._bi.get_variable_value('${OUTPUT DIR}')
                except Exception:
                    self.outdir = None
            if not self.outdir:
                # dernier recours : cwd
                self.outdir = os.getcwd()

    # Hooks où le contexte est garanti
    def start_suite(self, name, attrs):
        self._ensure_bi_and_outdir()

    def start_test(self, name, attrs):
        self._ensure_bi_and_outdir()

    def end_keyword(self, name, attrs):
        if attrs.get('status') != 'FAIL':
            return
        self._ensure_bi_and_outdir()

        suite = self._safe(self._bi.get_variable_value('${SUITE NAME}', default='suite') if self._bi else 'suite')
        test  = self._safe(self._bi.get_variable_value('${TEST NAME}',  default='no-test') if self._bi else 'no-test')
        kw    = self._safe(attrs.get('kwname') or name)
        ts    = datetime.now().strftime('%Y%m%d-%H%M%S-%f')

        folder = os.path.join(self.outdir, 'screenshots', suite, test)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{self.prefix}-{kw}-{ts}.png")

        try:
            # tenter sans import, puis importer si besoin
            try:
                self._bi.run_keyword('Take Screenshot', path)
            except Exception:
                self._bi.run_keyword('Import Library', 'ScreenCapLibrary')
                self._bi.run_keyword('Take Screenshot', path)

            rel = os.path.relpath(path, self.outdir).replace('\\', '/')
            logger.info(f'Failure screenshot saved: {path}')
            logger.info(f'<a href="{rel}">Open screenshot</a>', html=True)
        except Exception as e:
            logger.warn(f'Listener failed to take screenshot: {e}')
