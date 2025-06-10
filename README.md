import threading
import requests
import time
from queue import Queue

class TbWeb_Cookie:
    """Récupère et renvoie le cookie pour accès"""

    def __init__(self, ipserver):
        self.cookies = None
        self.ipserver = ipserver

    def run(self):
        data = {
            "J_username": "your_username",  # À remplacer
            "J_password": "your_password"   # À remplacer
        }

        try:
            response = requests.post(
                f"https://{self.ipserver}/login",
                data=data,
                verify=False
            )

            cookies_value = response.cookies.get('tbw-server-credential')
            if cookies_value:
                self.cookies = f"tbw-server-credential={cookies_value}"
                print(f"[Cookie] Cookie récupéré : {self.cookies}")
            else:
                print("[Cookie] Cookie introuvable dans la réponse.")

        except Exception as e:
            print(f"[Cookie] Erreur lors de la récupération du cookie : {e}")


class JWTFetcher(threading.Thread):
    """Thread de récupération cyclique du Token JWT (Basé sur son délai d'expiration)"""

    def __init__(self, ipserver, cookies, token=None, interval=30, result_queue=None, stop_event=None):
        super().__init__()
        self.ipserver = ipserver
        self.cookies = cookies
        self.interval = interval
        self.result_queue = result_queue or Queue()
        self.stop_event = stop_event or threading.Event()
        self.uuid = "your-uuid"  # À remplacer
        self.jwt = None
        self.expiry = 0

    def run(self):
        print(f"\033[32m[Thread JWT] Cookie récupéré : {self.cookies}\033[0m")
        while not self.stop_event.is_set():
            now = time.time()

            if self.jwt is None or now >= self.expiry:
                try:
                    headers = {
                        "Application-Uuid": self.uuid,
                        "cookie": self.cookies,
                        "Accept": "application/json, text/plain, */*"
                    }

                    response = requests.get(
                        f"https://{self.ipserver}/api/auth/jwt",
                        headers=headers,
                        verify=False
                    )

                    self.jwt = response.json().get("jwt")
                    periodSec = response.json().get("periodSec", 30)
                    self.expiry = now + periodSec - 1
                    self.result_queue.put(self.jwt)

                    print(f"\033[32m[Thread JWT] Nouveau JWT récupéré : {self.jwt[:30]}...{self.jwt[-10:]} (expire dans {periodSec}s)\033[0m")

                except Exception as e:
                    print(f"[Thread JWT] Erreur récupération JWT : {e}")

            if self.stop_event.wait(self.interval):
                break


if __name__ == "__main__":
    ip = "monserveur.local"  # Remplace par l’adresse de ton serveur

    cookie_getter = TbWeb_Cookie(ipserver=ip)
    cookie_getter.run()

    if cookie_getter.cookies:
        fetcher = JWTFetcher(ipserver=ip, cookies=cookie_getter.cookies)
        fetcher.start()
    else:
        print("Impossible de démarrer le fetcher sans cookie.")
