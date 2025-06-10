import requests

class APIRequester:
    """Classe générique pour effectuer des requêtes GET authentifiées"""

    def __init__(self, ipserver, jwt_token, app_uuid):
        self.ipserver = ipserver
        self.jwt_token = jwt_token
        self.app_uuid = app_uuid

    def get(self, endpoint):
        """Effectue une requête GET avec les headers requis"""

        headers = {
            "Authorization": f"Bearer {self.jwt_token}",
            "Application-Uuid": self.app_uuid,
            "Accept": "application/json"
        }

        try:
            response = requests.get(
                f"https://{self.ipserver}{endpoint}",
                headers=headers,
                verify=False
            )
            print(f"[APIRequester] Requête GET vers {endpoint} : statut {response.status_code}")
            return response
        except Exception as e:
            print(f"[APIRequester] Erreur lors de la requête GET : {e}")
            return None



if __name__ == "__main__":
    ip = "monserveur.local"
    uuid = "your-uuid"

    cookie_getter = TbWeb_Cookie(ipserver=ip)
    cookie_getter.run()

    if cookie_getter.cookies:
        jwt_queue = Queue()
        stop_event = threading.Event()

        fetcher = JWTFetcher(
            ipserver=ip,
            cookies=cookie_getter.cookies,
            interval=10,
            result_queue=jwt_queue,
            stop_event=stop_event
        )
        fetcher.uuid = uuid
        fetcher.start()

        # Attente que le JWT soit disponible
        time.sleep(2)
        if not jwt_queue.empty():
            jwt_token = jwt_queue.get()

            # Requête GET authentifiée
            requester = APIRequester(ipserver=ip, jwt_token=jwt_token, app_uuid=uuid)
            response = requester.get("/api/exemple/endpoint")

            if response and response.ok:
                print(response.json())
        else:
            print("JWT non disponible.")
