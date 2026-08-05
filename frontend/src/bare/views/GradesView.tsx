/** 성적 목록·추이 공용 뷰 — 학생/학부모 동일(PRD 3.2.1 성적 현황). */
/* eslint-disable @typescript-eslint/no-explicit-any */
import { Link } from "react-router-dom";

export default function GradesView({
  data,
  reportPath,
}: {
  data: any;
  reportPath: (examId: number) => string;
}) {
  return (
    <div>
      <p>
        <strong>{data.student.name}</strong> (원번 {data.student.matching_key} ·{" "}
        {data.student.school || "학교 미입력"})
      </p>
      <h3>시험 목록</h3>
      <table>
        <thead>
          <tr>
            <th>회차</th>
            <th>시험명</th>
            <th>시험일</th>
            <th>응시</th>
            <th>내 점수</th>
            <th>전체 평균</th>
            <th>성적표</th>
          </tr>
        </thead>
        <tbody>
          {data.exams.length === 0 && (
            <tr>
              <td colSpan={7} className="muted">
                성적 없음
              </td>
            </tr>
          )}
          {data.exams.map((exam: any) => (
            <tr key={exam.exam_id}>
              <td>{exam.round_no ?? "-"}</td>
              <td>{exam.name}</td>
              <td>{exam.exam_date}</td>
              <td>{exam.is_taken ? "응시" : "미응시"}</td>
              <td>
                {exam.my_score ?? "-"} / {exam.max_score ?? "-"}
              </td>
              <td>{exam.average ?? "-"}</td>
              <td>
                <Link to={reportPath(exam.exam_id)}>상세</Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3>회차별 추이</h3>
      <table>
        <thead>
          <tr>
            <th>회차</th>
            <th>내 점수</th>
            <th>백분위</th>
            <th>전체 평균</th>
            <th>상위 30%</th>
            <th>최고점</th>
          </tr>
        </thead>
        <tbody>
          {data.trend.map((point: any) => (
            <tr key={point.exam_id}>
              <td>
                {point.round_no ?? "-"}회 ({point.exam_date})
              </td>
              <td>{point.my_score ?? "-"}</td>
              <td>{point.percentile ?? "-"}</td>
              <td>{point.average ?? "-"}</td>
              <td>{point.top30_score ?? "-"}</td>
              <td>{point.highest_score ?? "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
