# md-to-slides 디자인 상수 & 헬퍼 코드

## 컬러 팔레트

```javascript
const C = {
  bg:      { r: 0.102, g: 0.122, b: 0.180 }, // #1a1f2e — 슬라이드 배경
  card:    { r: 0.161, g: 0.188, b: 0.267 }, // #293044 — 카드 배경
  code:    { r: 0.082, g: 0.098, b: 0.149 }, // #151926 — 코드 블록 배경
  blueDim: { r: 0.141, g: 0.231, b: 0.467 }, // #243b77 — 장식 도형
  blue:    { r: 0.310, g: 0.557, b: 0.973 }, // #4f8ef8 — 주 액센트
  orange:  { r: 1.000, g: 0.647, b: 0.196 }, // #FFA532 — 경고/기존 방식
  green:   { r: 0.180, g: 0.796, b: 0.529 }, // #2ECB87 — 성공/개선
  red:     { r: 0.957, g: 0.314, b: 0.314 }, // #F45050 — 문제/위험
  white:   { r: 1,     g: 1,     b: 1     },
  gray:    { r: 0.737, g: 0.769, b: 0.831 }, // #BCC4D4 — 본문
  muted:   { r: 0.502, g: 0.541, b: 0.616 }, // #808A9D — 부가 설명
};
```

## 헬퍼 함수 (모든 슬라이드 스크립트 상단에 포함)

```javascript
// 1. 폰트 로드 (반드시 가장 먼저)
await figma.loadFontAsync({ family: "Inter", style: "Regular" });
await figma.loadFontAsync({ family: "Inter", style: "Medium" });
await figma.loadFontAsync({ family: "Inter", style: "Bold" });
await figma.loadFontAsync({ family: "Inter", style: "Semi Bold" });

const W = 1920, H = 1080, PAD = 120;

// 2. 사각형 (appendChild 자동 포함)
function R(parent, x, y, w, h, color, radius) {
  const r = figma.createRectangle();
  parent.appendChild(r);  // 먼저 append
  r.x = x; r.y = y; r.resize(w, h);
  r.fills = [{ type: 'SOLID', color }];
  if (radius) r.cornerRadius = radius;
  return r;
}

// 3. 텍스트 (appendChild 자동 포함, width 지정 시 자동 줄바꿈)
function T(parent, str, x, y, size, color, style, width) {
  const t = figma.createText();
  parent.appendChild(t);  // 먼저 append
  t.fontName = { family: 'Inter', style: style || 'Regular' };
  t.fontSize = size;
  t.fills = [{ type: 'SOLID', color: color || C.white }];
  if (width) { t.textAutoResize = 'HEIGHT'; t.resize(width, 80); }
  t.x = x; t.y = y;
  t.characters = str;
  return t;
}
```

## 레이아웃 패턴

### 모든 슬라이드 공통

```javascript
R(s, 0, 0, W, H, C.bg);          // 배경
R(s, 0, 0, 8, H, accentColor);   // 좌측 액센트 바
T(s, '슬라이드 제목', PAD, 70, 52, C.white, 'Bold');
T(s, '부제목', PAD, 138, 22, C.muted, 'Regular', W-PAD*2);
// 콘텐츠 시작 y: ~220
```

### 표지 슬라이드

```javascript
R(s, 0, 0, W, H, C.bg);
R(s, 0, 0, 8, H, C.blue);
R(s, W-520, -80, 560, 560, C.blueDim, 280);  // 우상단 원
R(s, W-320, H-200, 380, 380, C.blueDim, 190); // 우하단 원

R(s, PAD, 370, 200, 36, C.blueDim, 8);        // 배지 배경
T(s, 'CATEGORY', PAD+16, 378, 14, C.blue, 'Semi Bold');

T(s, '메인 제목', PAD, 424, 88, C.white, 'Bold');
T(s, '부제목', PAD, 534, 36, C.gray, 'Medium');
T(s, '설명 한 줄', PAD, 586, 24, C.muted, 'Regular', 1100);
```

### 3-column 카드 (3개 항목 나열)

```javascript
const items = [ { title, desc, c: C.blue }, ... ]; // 3개
const cW = (W-PAD*2-60)/3;
items.forEach((item, i) => {
  const x = PAD + i*(cW+30), y = 230;
  R(s, x, y, cW, 640, C.card, 16);
  R(s, x, y, cW, 6, item.c);             // 상단 컬러 바
  T(s, item.no, x+28, y+36, 64, item.c, 'Bold');     // 번호 (01/02/03)
  T(s, item.title, x+28, y+118, 30, C.white, 'Bold', cW-56);
  T(s, item.desc, x+28, y+220, 22, C.gray, 'Regular', cW-56);
});
```

### Before/After 2-column 비교

```javascript
const hW = (W-PAD*2-40)/2;

// Before (왼쪽)
R(s, PAD, 220, hW, 700, C.card, 16);
R(s, PAD, 220, hW, 6, C.red);
T(s, 'BEFORE', PAD+28, 248, 20, C.red, 'Semi Bold');
R(s, PAD+20, 330, hW-40, 170, C.code, 8); // 코드 블록
T(s, '코드 내용', PAD+36, 346, 20, C.orange, 'Regular', hW-72);
T(s, '단점 설명', PAD+28, 526, 22, C.gray, 'Regular', hW-56);

// After (오른쪽)
const ax = PAD+hW+40;
R(s, ax, 220, hW, 700, C.card, 16);
R(s, ax, 220, hW, 6, C.green);
T(s, 'AFTER', ax+28, 248, 20, C.green, 'Semi Bold');
R(s, ax+20, 330, hW-40, 170, C.code, 8);
T(s, '코드 내용', ax+36, 346, 20, C.green, 'Regular', hW-72);
T(s, '장점 설명', ax+28, 526, 22, C.gray, 'Regular', hW-56);
```

### 수평 파이프라인 (단계별 흐름)

```javascript
const phases = [ { label, sub, c } ]; // 5~6개
const bW = 238, bH = 320;
const totalW = phases.length*bW + (phases.length-1)*48;
const sx = (W-totalW)/2;
phases.forEach((p, i) => {
  const x = sx + i*(bW+48), y = 220;
  R(s, x, y, bW, bH, C.card, 12);
  R(s, x, y, bW, 5, p.c);
  T(s, p.label, x+18, y+22, 20, p.c, 'Semi Bold');
  T(s, p.sub, x+18, y+60, 24, C.white, 'Medium', bW-36);
  if (i < phases.length-1) R(s, x+bW+4, y+bH/2-2, 40, 4, C.muted); // 화살표
});
```

### Full-width 행 (검증 계층, 타임라인 등)

```javascript
const layers = [ { name, c, title, sub, note } ];
const rH = 220;
layers.forEach((l, i) => {
  const y = 190 + i*(rH+24);
  R(s, PAD, y, W-PAD*2, rH, C.card, 12);
  R(s, PAD, y, 6, rH, l.c);            // 좌측 컬러 바

  // 컬러 배지
  R(s, PAD+24, y+rH/2-32, 72, 64, l.c, 10);
  const badge = figma.createText();
  s.appendChild(badge);
  badge.fontName = { family:'Inter', style:'Bold' };
  badge.fontSize = 28;
  badge.fills = [{ type:'SOLID', color: C.bg }];
  badge.textAlignHorizontal = 'CENTER';
  badge.textAlignVertical = 'CENTER';
  badge.textAutoResize = 'NONE';
  badge.resize(72, 64);
  badge.x = PAD+24; badge.y = y+rH/2-32;
  badge.characters = l.name;

  T(s, l.title, PAD+118, y+22, 28, C.white, 'Semi Bold');
  T(s, l.sub,   PAD+118, y+66, 20, C.gray,  'Regular', W-PAD*2-200);
  T(s, l.note,  PAD+118, y+104, 20, l.c,    'Regular', W-PAD*2-200);
});
```

### 테이블 (비교표)

```javascript
const tY = 400;
const colX = [PAD+16, PAD+500, PAD+900, PAD+1300]; // 열 x 좌표

// 헤더
R(s, PAD, tY, W-PAD*2, 50, { r:0.18, g:0.21, b:0.30 });
['열1', '열2', '열3', '열4'].forEach((h, i) =>
  T(s, h, colX[i], tY+14, 18, C.blue, 'Semi Bold')
);

// 데이터 행
rows.forEach((row, i) => {
  const ry = tY+50+i*62;
  R(s, PAD, ry, W-PAD*2, 62, i%2===0 ? C.card : { r:0.13, g:0.15, b:0.22 });
  // T(s, row.col1, colX[0], ry+18, 20, C.white, 'Regular');
});
```

## 타이포그래피 스케일

| 용도 | 크기 | 굵기 |
|------|------|------|
| 슬라이드 제목 | 52px | Bold |
| 대형 번호/강조 | 64–88px | Bold |
| 섹션/카드 제목 | 28–36px | Bold / Semi Bold |
| 본문 | 20–24px | Regular |
| 부가 설명 | 16–20px | Regular |
| 배지/레이블 | 14–18px | Semi Bold |
| 코드 | 20px | Regular (C.orange 또는 C.green) |
