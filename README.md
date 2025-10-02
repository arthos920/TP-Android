import signal
import sys
import os
import subprocess
from robot.api import logger
from robot.libraries.BuiltIn import BuiltIn

class GracefulStopListener:
    ROBOT_LISTENER_API_VERSION = 3

    def __init__(self):
        signal.signal(signal.SIGINT, self._stop_handler)
        signal.signal(signal.SIGTERM, self._stop_handler)
        self.output_xml = os.getenv("ROBOT_OUTPUT", "output.xml")

    def _stop_handler(self, signum, frame):
        logger.warn("⚠️ Arrêt détecté, génération du log.html…")
        try:
            # on force Robot à arrêter proprement
            BuiltIn().fatal_error("Test interrompu manuellement")
        except Exception:
            pass

        # Génération manuelle des logs à partir du output.xml courant
        if os.path.exists(self.output_xml):
            subprocess.call([
                "rebot",
                "--log", "log.html",
                "--report", "report.html",
                "--output", self.output_xml
            ])
        sys.exit(0)