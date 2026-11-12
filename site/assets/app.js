/* 공통 화면 틀: 상단 바(PC 메뉴) · 휴대폰 하단 탭 · 바닥글 · 홈 화면 앱 등록
   사용: <body data-page="home|live|race|plan|review|bets|results|guide"> 바로 뒤에 <script src="assets/app.js"></script> */
(() => {
  const page = document.body.dataset.page || "";
  const I = {
    home: '<path d="M4 10.5 12 4l8 6.5V20a1 1 0 0 1-1 1h-4.5v-6h-5v6H5a1 1 0 0 1-1-1z"/>',
    live: '<circle cx="12" cy="13.5" r="7"/><path d="M12 13.5V10M10 3.5h4M12 3.5v3M18 7.5l1.3-1.3"/>',
    race: '<path d="M6.5 4.5v6.8a5.5 5.5 0 0 0 11 0V4.5"/><path d="M4.5 4.5h4M15.5 4.5h4"/><circle cx="8.6" cy="12" r=".6"/><circle cx="15.4" cy="12" r=".6"/><circle cx="9.6" cy="15.6" r=".6"/><circle cx="14.4" cy="15.6" r=".6"/>',
    review: '<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M8 3v4M16 3v4M4 10h16"/><path d="m9 15 2 2 4-4"/>',
    bets: '<path d="M4 7a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v2.2a2.8 2.8 0 0 0 0 5.6V17a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-2.2a2.8 2.8 0 0 0 0-5.6z"/><path d="M14 5.5v13" stroke-dasharray="2 2"/>',
    results: '<path d="M4 20h16"/><path d="M6.5 16v-4M11 16V8M15.5 16v-6M20 16V5" />',
    plan: '<rect x="3.5" y="6" width="17" height="13" rx="2.5"/><path d="M3.5 10h17"/><circle cx="16" cy="14.5" r="1.2"/><path d="M7 3.5h10"/>',
    guide: '<circle cx="12" cy="12" r="8.5"/><path d="M9.6 9.4a2.5 2.5 0 1 1 3.4 2.3c-.6.3-1 .8-1 1.5v.6"/><circle cx="12" cy="16.9" r=".7"/>'
  };
  const svg = k => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${I[k]}</svg>`;
  const items = [["home", "./", "홈"], ["live", "live.html", "현장"], ["race", "race.html", "경주 예측"], ["plan", "plan.html", "베팅 계획"], ["bets", "bets.html", "내 마권"]];
  const more = [["review", "review.html", "주간 복기"], ["results", "results.html", "수익 검증"], ["guide", "guide.html", "사용법"]];
  const cur = k => (k === page || (page === "sim" && k === "race")) ? ' aria-current="page"' : "";
  const logo = `<svg viewBox="0 0 32 32" aria-hidden="true"><path d="M7 5.5h18a1.5 1.5 0 0 1 1.5 1.5v13.2c0 3.4-2.2 5.3-5.4 6L16 27.4l-5.1-1.2c-3.2-.7-5.4-2.6-5.4-6V7A1.5 1.5 0 0 1 7 5.5z" fill="#f5f8f6"/><text x="16" y="21.3" text-anchor="middle" font-size="15" font-weight="800" fill="#0f3a2a" font-family="Pretendard Variable,Pretendard,Noto Sans KR,sans-serif">1</text></svg>`;
  document.body.insertAdjacentHTML("afterbegin",
    `<a class="sr" href="#main">본문으로 건너뛰기</a>
     <header class="appbar"><div class="wrap">
       <a class="logo" href="./">${logo}<span>서울 경주 예측</span></a>
       <nav class="nav" aria-label="주요 메뉴">${[...items, ...more].map(([k, h, t]) => `<a href="${h}"${cur(k)}>${t}</a>`).join("")}</nav>
       <a class="helpbtn" href="guide.html" aria-label="사용법"${cur("guide")}>${svg("guide")}</a>
     </div></header>`);
  document.body.insertAdjacentHTML("beforeend",
    `<nav class="tabbar" aria-label="주요 메뉴">${items.map(([k, h, t]) => `<a href="${h}"${cur(k)}>${svg(k)}<span>${t}</span></a>`).join("")}</nav>`);
  addEventListener("DOMContentLoaded", () => {
    if (document.body.dataset.foot === "none") return;
    document.body.insertAdjacentHTML("beforeend",
      `<footer class="site-foot"><div class="wrap">
        <p>경주 자료: 한국마사회 공공데이터(출전표·경주성적·확정배당), 당일 마체중은 한국마사회 경마 홈페이지. 예측은 렛츠런파크 서울만 다룹니다.</p>
        <p>이 사이트는 경주를 이해하기 위한 도구입니다. 과거 검증에서 꾸준히 이익을 낸 마권 구입 방법은 없었습니다. <a href="guide.html">사용법과 한계</a></p>
      </div></footer>`);
  });
  if ("serviceWorker" in navigator) addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {}));
})();
