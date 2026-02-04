from concurrent.futures import ProcessPoolExecutor, as_completed
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


URL = "http://localhost:3000/..."  # <-- ton URL locale

INPUT_SELECTOR = (By.ID, "input-id")          # <-- à adapter
BUTTON_SELECTOR = (By.ID, "submit-id")        # <-- à adapter

# Un indicateur de blocage (rate limit / lockout) : à adapter à TON UI
# Exemples: "Too many attempts", "Réessayez plus tard", etc.
BLOCK_MESSAGE_SELECTOR = (By.ID, "rate-limit-message")  # <-- à adapter

# Si tu as un message de succès (optionnel)
SUCCESS_SELECTOR = (By.ID, "success-message")  # <-- à adapter

WAIT_SECS = 8


def make_driver():
    opts = Options()
    # opts.add_argument("--headless=new")  # si tu veux (souvent + rapide)
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--window-size=1200,800")
    return webdriver.Chrome(options=opts)


def is_present(wait: WebDriverWait, selector) -> bool:
    try:
        wait.until(EC.presence_of_element_located(selector))
        return True
    except Exception:
        return False


def worker(proc_id: int, start: int, end: int):
    driver = make_driver()
    wait = WebDriverWait(driver, WAIT_SECS)

    tested = 0
    blocked = False
    found_success = False
    t0 = time.perf_counter()

    try:
        driver.get(URL)
        print(f"[Process {proc_id}] plage {start:06d} → {end-1:06d}")

        for i in range(start, end):
            value = f"{i:06d}"

            # Remplir champ
            field = wait.until(EC.presence_of_element_located(INPUT_SELECTOR))
            field.clear()
            field.send_keys(value)

            # Cliquer
            btn = wait.until(EC.element_to_be_clickable(BUTTON_SELECTOR))
            btn.click()

            tested += 1

            # Détection "bloqué" (rate limit / lockout)
            if is_present(wait, BLOCK_MESSAGE_SELECTOR):
                blocked = True
                break

            # Optionnel: succès (utile pour valider la détection)
            if is_present(wait, SUCCESS_SELECTOR):
                found_success = True
                break

        elapsed = time.perf_counter() - t0
        avg = elapsed / tested if tested else None

        return {
            "proc": proc_id,
            "start": start,
            "end": end,
            "tested": tested,
            "blocked": blocked,
            "success": found_success,
            "elapsed_s": round(elapsed, 3),
            "avg_s_per_try": round(avg, 4) if avg is not None else None,
        }

    finally:
        driver.quit()


def main():
    # ✅ borne volontairement pour audit (tu peux mettre 200, 500, 2000, etc.)
    total = 2000
    nprocs = 4
    chunk = total // nprocs

    # Ton découpage, intégré tel quel
    ranges = []
    for p in range(nprocs):
        start = p * chunk
        end = (p + 1) * chunk if p < nprocs - 1 else total  # couvre le reste
        print(f"Process {p}: {start:06d} → {end-1:06d}")
        ranges.append((p, start, end))

    results = []
    with ProcessPoolExecutor(max_workers=nprocs) as ex:
        futs = [ex.submit(worker, p, s, e) for (p, s, e) in ranges]
        for f in as_completed(futs):
            results.append(f.result())

    print("\n--- Résultats ---")
    for r in sorted(results, key=lambda x: x["proc"]):
        print(r)


if __name__ == "__main__":
    main()