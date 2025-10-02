import signal
import sys
import os
import subprocess
from robot.api import logger
from robot.libraries.BuiltIn import BuiltIn

class RideGracefulStopListener:
    ROBOT_LISTENER_API_VERSION = 3

    def __init__(self):
        # Branche les signaux envoyés par RIDE
        signal.signal(signal.SIGINT, self._stop_handler)
        signal.signal(signal.SIGTERM, self._stop_handler)

        # RIDE/Robot passe le chemin du output.xml via la variable d'env
        self.output_xml = os.getenv("ROBOT_OUTPUT", "output.xml")
        self.log_html = os.getenv("ROBOT_LOG", "log.html")
        self.report_html = os.getenv("ROBOT_REPORT", "report.html")

    def _stop_handler(self, signum, frame):
        # Message qui apparaîtra aussi dans la console RIDE
        logger.warn("⚠️ Test interrompu depuis RIDE — génération du log.html en cours…")

        try:
            # On force Robot à clore proprement
            BuiltIn().fatal_error("Test interrompu manuellement depuis RIDE")
        except Exception:
            pass

        # Génération des rapports même si le test est stoppé
        if os.path.exists(self.output_xml):
            subprocess.call([
                "rebot",
                "--log", self.log_html,
                "--report", self.report_html,
                "--output", self.output_xml
            ])

        sys.exit(0)