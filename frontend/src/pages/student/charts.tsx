/**
 * 학생 화면 전용 인라인 SVG 차트. 외부 라이브러리 없음.
 *
 * 색 규약: 잠긴 네이비 토큰만 쓴다. 여러 계열을 색으로 구분하지 않는다 —
 * 초점 계열(내 점수)만 액센트 실선이고, 참조선(평균·상위 30%)은 굵기·점선·
 * 끝 라벨로 구분한다(색만으로 정체를 나르지 않는다). 최고점~평균 사이는
 * 선이 아니라 아주 연한 면(밴드)으로 깔아 "반 전체가 어디에 있는지"를 배경
 * 정보로 내린다.
 */
import { ReactNode } from "react";

export interface TrendDatum {
  label: string; // x축 라벨(예: "3회")
  mine: number | null;
  average: number | null;
  top30: number | null;
  highest: number | null;
}

const PAD = { top: 18, right: 46, bottom: 30, left: 34 };

function niceMax(value: number): number {
  if (value <= 0) return 100;
  const step = value > 200 ? 50 : 20;
  return Math.ceil(value / step) * step;
}

/**
 * 회차별 점수 추이. 내 점수 = 액센트 실선 + 값 라벨,
 * 평균·상위 30% = 가는 참조선, 평균~최고점 = 연한 밴드.
 */
export function TrendChart({ data, maxScore }: { data: TrendDatum[]; maxScore: number }) {
  if (data.length < 2) return null;

  const width = 640;
  const height = 240;
  const innerW = width - PAD.left - PAD.right;
  const innerH = height - PAD.top - PAD.bottom;
  const top = niceMax(
    Math.max(maxScore, ...data.map((d) => Math.max(d.highest ?? 0, d.mine ?? 0))),
  );

  const x = (index: number) =>
    PAD.left + (data.length === 1 ? innerW / 2 : (innerW * index) / (data.length - 1));
  const y = (value: number) => PAD.top + innerH - (innerH * value) / top;

  const line = (pick: (d: TrendDatum) => number | null) => {
    const points = data
      .map((d, i) => ({ v: pick(d), i }))
      .filter((p): p is { v: number; i: number } => p.v !== null);
    if (points.length === 0) return null;
    return points.map((p, n) => `${n === 0 ? "M" : "L"}${x(p.i)},${y(p.v)}`).join(" ");
  };

  // 평균~최고점 밴드(반 전체 분포의 배경). 두 값이 다 있는 구간만 그린다.
  const bandPoints = data
    .map((d, i) => ({ i, hi: d.highest, lo: d.average }))
    .filter((p): p is { i: number; hi: number; lo: number } => p.hi !== null && p.lo !== null);
  const band =
    bandPoints.length >= 2
      ? `${bandPoints.map((p, n) => `${n === 0 ? "M" : "L"}${x(p.i)},${y(p.hi)}`).join(" ")} ` +
        `${[...bandPoints]
          .reverse()
          .map((p) => `L${x(p.i)},${y(p.lo)}`)
          .join(" ")} Z`
      : null;

  const gridValues = [0, top / 2, top];
  const last = data[data.length - 1];

  return (
    <svg
      className="st-chart"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`회차별 점수 추이. 마지막 회차 내 점수 ${last.mine ?? "미응시"}점, 전체 평균 ${last.average ?? "-"}점.`}
    >
      {gridValues.map((value) => (
        <g key={value}>
          <line
            x1={PAD.left}
            x2={width - PAD.right}
            y1={y(value)}
            y2={y(value)}
            className="st-chart__grid"
          />
          <text x={PAD.left - 8} y={y(value) + 4} className="st-chart__axis" textAnchor="end">
            {value}
          </text>
        </g>
      ))}

      {band && <path d={band} className="st-chart__band" />}

      {(["highest", "top30", "average"] as const).map((key) => {
        const d = line((row) => row[key]);
        return d ? <path key={key} d={d} className={`st-chart__ref st-chart__ref--${key}`} /> : null;
      })}

      {(() => {
        const d = line((row) => row.mine);
        return d ? <path d={d} className="st-chart__mine" /> : null;
      })()}

      {data.map((row, i) =>
        row.mine === null ? null : (
          <g key={row.label}>
            <circle cx={x(i)} cy={y(row.mine)} r={4.5} className="st-chart__dot" />
            {/* 첫 점의 값 라벨은 y축 눈금과 겹치므로 오른쪽으로 정렬한다 */}
            <text
              x={i === 0 ? x(i) + 4 : x(i)}
              y={y(row.mine) - 11}
              className="st-chart__value"
              textAnchor={i === 0 ? "start" : "middle"}
            >
              {row.mine}
            </text>
          </g>
        ),
      )}

      {/* 끝 라벨 — 색이 아니라 글자로 계열을 식별한다 */}
      {last.highest !== null && (
        <text x={width - PAD.right + 6} y={y(last.highest) + 4} className="st-chart__endlabel">
          최고
        </text>
      )}
      {last.average !== null &&
        (last.highest === null || Math.abs(y(last.highest) - y(last.average)) > 13) && (
          <text x={width - PAD.right + 6} y={y(last.average) + 4} className="st-chart__endlabel">
            평균
          </text>
        )}

      {data.map((row, i) => (
        <text key={`x-${row.label}`} x={x(i)} y={height - 8} className="st-chart__axis" textAnchor="middle">
          {row.label}
        </text>
      ))}
    </svg>
  );
}

/** 차트 범례 — 계열 이름을 반드시 글자로 적는다. */
export function ChartLegend({ items }: { items: { kind: string; label: ReactNode }[] }) {
  return (
    <ul className="st-legend">
      {items.map((item) => (
        <li key={item.kind} className="st-legend__item">
          <span className={`st-legend__mark st-legend__mark--${item.kind}`} aria-hidden="true" />
          {item.label}
        </li>
      ))}
    </ul>
  );
}

/** 작은 추이선 — 테마별 누적 정답률처럼 표 옆에 붙는 용도. */
export function Sparkline({ values, label }: { values: number[]; label: string }) {
  if (values.length < 2) return null;
  const width = 108;
  const height = 30;
  const pad = 3;
  const x = (i: number) => pad + ((width - pad * 2) * i) / (values.length - 1);
  const y = (v: number) => height - pad - ((height - pad * 2) * v) / 100;
  const d = values.map((v, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(v)}`).join(" ");
  const lastIndex = values.length - 1;

  return (
    <svg className="st-spark" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}>
      <line x1={pad} x2={width - pad} y1={y(50)} y2={y(50)} className="st-spark__mid" />
      <path d={d} className="st-spark__line" />
      <circle cx={x(lastIndex)} cy={y(values[lastIndex])} r={3} className="st-spark__dot" />
    </svg>
  );
}

/** 정답률 막대 — 단일 색(크기 = 값). 값은 항상 글자로도 적는다. */
export function RateBar({ rate, caption }: { rate: number; caption?: string }) {
  const clamped = Math.max(0, Math.min(100, rate));
  return (
    <span className="st-ratebar" role="img" aria-label={caption ?? `정답률 ${rate}%`}>
      <span className="st-ratebar__track">
        <span className="st-ratebar__fill" style={{ width: `${clamped}%` }} />
      </span>
    </span>
  );
}
