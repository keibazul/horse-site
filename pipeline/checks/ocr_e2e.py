"""배당판 사진 읽기 확인 (GitHub Actions): 사이트를 띄우고 예측 화면에 시험 사진을 넣어 읽은 값을 정답과 비교

시험 사진 (pipeline/checks/ocr/, 모두 만든 그림):
  board_win.png   현장 배당판 단승 판만 (배당 왼쪽·마번 오른쪽, 흰색·하늘색 글자)
  board_photo.jpg 비스듬히 찍힌 화면 전체 (단승·연승·복연승 판이 같이 있음) → 단승 판만 끌어서 고름
  light.png       표 모양 (마번·말 이름·단승·연승)
"""
import subprocess, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
IMG = ROOT / "pipeline" / "checks" / "ocr"
BOARD = {1: 204.4, 2: 21.7, 3: 12.3, 4: 1.9, 5: 18.6, 6: 50.7, 7: 4.9, 8: 7.0, 9: 7.7, 10: 30.8}
TABLE = {1: 3.2, 2: 12.5, 3: 4.1, 4: 8.8, 5: 27.0, 6: 6.4, 7: 15.3, 8: 9.9, 9: 41.2, 10: 5.6, 11: 103.4}
# (사진, 경주, 끌어서 고를 범위(사진 좌표) 또는 None, 정답 또는 None=못 읽어야 정상)
CASES = [("board_win.png", 7, None, BOARD), ("board_photo.jpg", 7, (255, 215, 455, 680), BOARD),
         ("board_photo.jpg", 7, (255, 215, 665, 680), BOARD), ("board_photo.jpg", 7, None, None), ("light.png", 1, None, TABLE)]

srv = subprocess.Popen([sys.executable, "-m", "http.server", "8765"], cwd=ROOT / "site", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1)
fails = 0
try:
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 412, "height": 900})
        pg.on("pageerror", lambda e: print("ERR", e))
        for img, race, sel, truth in CASES:
            pg.goto(f"http://localhost:8765/race.html?date=20261108&race={race}"); pg.wait_for_timeout(1500)
            pg.click("#pasteBtn")
            pg.set_input_files("#ocrIn", str(IMG / img))
            pg.wait_for_selector("#ocrStage:not([hidden])")
            pg.wait_for_timeout(300)
            if sel:
                pg.locator("#ocrCanvas").scroll_into_view_if_needed(); pg.wait_for_timeout(200)
                box = pg.locator("#ocrCanvas").bounding_box()
                from PIL import Image
                iw, ih = Image.open(IMG / img).size
                fx, fy = box["width"] / iw, box["height"] / ih
                x0, y0, x1, y1 = sel
                pg.mouse.move(box["x"] + x0 * fx, box["y"] + y0 * fy); pg.mouse.down()
                pg.mouse.move(box["x"] + (x0 + x1) / 2 * fx, box["y"] + (y0 + y1) / 2 * fy, steps=4)
                pg.mouse.move(box["x"] + x1 * fx, box["y"] + y1 * fy, steps=4); pg.mouse.up()
            t0 = time.time()
            pg.click("#ocrRun")
            pg.wait_for_function("() => /읽었|못했|실패|받지/.test(document.getElementById('pasteMsg').textContent)", timeout=180000)
            msg = pg.text_content("#pasteMsg")
            got = {}
            for ln in pg.input_value("#pasteIn").splitlines():
                a = ln.split()
                if len(a) == 2:
                    got[int(a[0])] = float(a[1])
            if truth is None:
                ok = len(got) < 6            # 판이 여러 개 섞인 사진 전체는 못 읽는 것이 정상 (고르라고 안내)
            else:
                ok = got == truth
            fails += not ok
            print(f"{'OK  ' if ok else 'FAIL'} {img} {race}R {'선택 ' + str(sel) if sel else '전체'} ({time.time() - t0:.1f}s) 읽음 {len(got)} | {msg}")
            if not ok and truth:
                print("     틀린 값:", {k: (got.get(k), v) for k, v in truth.items() if got.get(k) != v})
        # 읽은 값을 '넣기' 로 배당 칸에 넣기까지
        pg.goto("http://localhost:8765/race.html?date=20261108&race=7"); pg.wait_for_timeout(1500)
        pg.click("#pasteBtn"); pg.set_input_files("#ocrIn", str(IMG / "board_win.png"))
        pg.wait_for_selector("#ocrStage:not([hidden])"); pg.click("#ocrRun")
        pg.wait_for_function("() => /읽었/.test(document.getElementById('pasteMsg').textContent)", timeout=180000)
        pg.click("#pasteApply"); pg.wait_for_timeout(400)
        vals = pg.eval_on_selector_all("[data-odds]", "xs => xs.map(x => [x.dataset.odds, x.value])")
        ok = {int(k): float(v) for k, v in vals if v} == BOARD
        fails += not ok
        print(f"{'OK  ' if ok else 'FAIL'} 넣기 후 배당 칸: {vals} | 기준 {pg.text_content('#srcPill')}")
        b.close()
finally:
    srv.terminate()
sys.exit(1 if fails else 0)
