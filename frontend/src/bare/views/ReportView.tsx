/** 성적표 상세 공용 뷰 — PRD 3.2.1 전 섹션(요약·대단원·채점표·학습동선·테마 추이). */
/* eslint-disable @typescript-eslint/no-explicit-any */

export default function ReportView({ data }: { data: any }) {
  const report = data.report;
  return (
    <div>
      <p>
        <strong>{data.exam.name}</strong> ({data.exam.exam_date}
        {data.exam.round_no ? ` · ${data.exam.round_no}회` : ""}) — {data.student.name} (원번{" "}
        {data.student.unique_id} · {data.student.school || "학교 미입력"})
      </p>
      {data.exam.notice && <p>공지: {data.exam.notice}</p>}
      {!data.is_taken && (
        <p className="error">미응시 — 성적표 없음(PRD 3.1.1: 미응시는 성적표를 생성하지 않음)</p>
      )}
      {report && (
        <>
          <h3>성적 요약</h3>
          <table>
            <thead>
              <tr>
                <th>내 점수/만점</th>
                <th>전체 평균</th>
                <th>표준편차</th>
                <th>최고점</th>
                <th>상위 30%</th>
                <th>백분위</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>
                  {report.summary.my_score} / {report.summary.max_score}
                </td>
                <td>{report.summary.average}</td>
                <td>{report.summary.stddev}</td>
                <td>{report.summary.highest_score}</td>
                <td>{report.summary.top30_score}</td>
                <td>{report.summary.percentile}</td>
              </tr>
            </tbody>
          </table>

          <h3>대단원별 점수</h3>
          <table>
            <thead>
              <tr>
                <th>대단원</th>
                <th>문항 수</th>
                <th>정답(오답)</th>
                <th>내 점수/단원 만점</th>
                <th>정답률</th>
              </tr>
            </thead>
            <tbody>
              {report.units.map((unit: any) => (
                <tr key={unit.unit_major}>
                  <td>{unit.unit_major}</td>
                  <td>{unit.question_count}</td>
                  <td>
                    {unit.correct_count}({unit.wrong_count})
                  </td>
                  <td>
                    {unit.my_points} / {unit.unit_max_points}
                  </td>
                  <td>{unit.correct_rate}%</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3>문항 채점표</h3>
          <table>
            <thead>
              <tr>
                <th>번호</th>
                <th>단원</th>
                <th>배점</th>
                <th>정답</th>
                <th>내 마킹</th>
                <th>결과</th>
                <th>오답률</th>
              </tr>
            </thead>
            <tbody>
              {report.questions.map((question: any) => (
                <tr key={question.q_number}>
                  <td>{question.q_number}</td>
                  <td>
                    {question.unit_major}
                    {question.unit_minor ? ` > ${question.unit_minor}` : ""}
                  </td>
                  <td>{question.points}</td>
                  <td>{question.answer}</td>
                  <td>{question.marked ?? "-"}</td>
                  <td>{question.result ?? "-"}</td>
                  <td>{question.wrong_rate ?? "-"}%</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3>오답 문항 학습동선</h3>
          {report.wrong_answer_guides.length === 0 ? (
            <p className="muted">틀린 문항 없음 — 표시하지 않음(PRD 3.2.1)</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>문항</th>
                  <th>단원/테마</th>
                  <th>학습 가이드</th>
                  <th>가이드 영상</th>
                </tr>
              </thead>
              <tbody>
                {report.wrong_answer_guides.map((guide: any) => (
                  <tr key={guide.q_number}>
                    <td>{guide.q_number}번</td>
                    <td>
                      {guide.unit_major}
                      {guide.theme_tag ? ` · ${guide.theme_tag}` : ""}
                    </td>
                    <td>{guide.study_guide}</td>
                    <td>{guide.guide_video ? guide.guide_video.title : "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <h3>테마별 누적 정답률 추이</h3>
          {report.theme_trends.map((trend: any) => (
            <details key={trend.theme}>
              <summary>
                {trend.theme} — 최근 누적{" "}
                {trend.points.length > 0
                  ? `${trend.points[trend.points.length - 1].cumulative_rate}%`
                  : "-"}
              </summary>
              <table>
                <thead>
                  <tr>
                    <th>회차</th>
                    <th>이번 회차 정답/문항</th>
                    <th>회차 정답률</th>
                    <th>누적 정답률</th>
                  </tr>
                </thead>
                <tbody>
                  {trend.points.map((point: any) => (
                    <tr key={point.exam_id}>
                      <td>
                        {point.round_no ?? "-"}회 ({point.exam_date})
                      </td>
                      <td>
                        {point.correct}/{point.total}
                      </td>
                      <td>{point.rate}%</td>
                      <td>{point.cumulative_rate}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          ))}
        </>
      )}
    </div>
  );
}
