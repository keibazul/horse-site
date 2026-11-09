"""배당 사진 읽기 확인 (GitHub Actions): 사이트를 띄우고 예측 화면에 시험 사진을 넣어 결과를 출력"""
import subprocess, time, sys
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT = Path(__file__).resolve().parents[2]
srv = subprocess.Popen([sys.executable, "-m", "http.server", "8765"], cwd=ROOT / "site", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1)
try:
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page()
        pg.on("pageerror", lambda e: print("ERR", e))
        for img in ["light", "dark", "grid"]:
            pg.goto("http://localhost:8765/race.html?date=20261108&race=1"); pg.wait_for_timeout(1500)
            pg.click("#pasteBtn")
            t0 = time.time()
            pg.set_input_files("#ocrIn", str(ROOT / "pipeline" / "checks" / "ocr" / f"{img}.png"))
            pg.wait_for_function("() => /읽었|채웠|못|실패/.test(document.getElementById('pasteMsg').textContent)", timeout=120000)
            print(f"== {img} ({time.time() - t0:.1f}s)", pg.text_content("#pasteMsg"))
            print(pg.input_value("#pasteIn").replace("\n", " | "))
        b.close()
finally:
    srv.terminate()
