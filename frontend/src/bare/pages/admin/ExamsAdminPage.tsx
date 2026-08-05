/** 관리자 시험·성적 처리 조회 — 목록/상세(학생 점수·문항 정답률). */
/* eslint-disable @typescript-eslint/no-explicit-any */
import { Link, useParams } from "react-router-dom";

import { api } from "../../api";
import { Msg, useLoad } from "../../ui";

export function ExamsAdminPage() {
  const { data, error, loading } = useLoad<any>(
    async () => (await api.get("/admin/exams")).data,
    [],
  );
  return (
    <section>
      <h2>시험 목록 (성적처리)</h2>
      <Msg error={error} />
      {loading && <p>불러오는 중…</p>}
      {data && (
        <table>
          <thead>
            <tr>
              <th>회차</th>
              <th>시험명</th>
              <th>시험일</th>
              <th>응시자</th>
              <th>성적 행</th>
              <th>평균</th>
              <th>처리 상태</th>
              <th>미대조 답안지</th>
              <th>상세</th>
            </tr>
          </thead>
          <tbody>
            {data.exams.map((exam: any) => (
              <tr key={exam.exam_id}>
                <td>{exam.round_no ?? "-"}</td>
                <td>{exam.name}</td>
                <td>{exam.exam_date}</td>
                <td>{exam.taker_count}</td>
                <td>{exam.score_count}</td>
                <td>{exam.average ?? "-"}</td>
                <td>{exam.processing_status}</td>
                <td>{exam.pending_sheet_count}</td>
                <td>
                  <Link to={`/bare/admin/exams/${exam.exam_id}`}>상세</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

export function ExamDetailAdminPage() {
  const { examId } = useParams();
  const { data, error, loading } = useLoad<any>(
    async () => (await api.get(`/admin/exams/${examId}`)).data,
    [examId],
  );
  return (
    <section>
      <h2>
        시험 상세 <Link to="/bare/admin/exams">(목록으로)</Link>
      </h2>
      <Msg error={error} />
      {loading && <p>불러오는 중…</p>}
      {data && (
        <>
          <p>
            <strong>{data.exam.name}</strong> ({data.exam.exam_date}) — 응시{" "}
            {data.stats.taker_count}명 · 평균 {data.stats.average ?? "-"} · 표준편차{" "}
            {data.stats.stddev ?? "-"} · 최고 {data.stats.highest_score ?? "-"} · 상위30%{" "}
            {data.stats.top30_score ?? "-"} · 처리 상태 {data.stats.processing_status}
          </p>
          <h3>학생별 점수 (석차순)</h3>
          <table>
            <thead>
              <tr>
                <th>석차</th>
                <th>학생</th>
                <th>원번</th>
                <th>반</th>
                <th>점수</th>
                <th>응시</th>
              </tr>
            </thead>
            <tbody>
              {data.students.map((row: any) => (
                <tr key={row.student_id}>
                  <td>{row.rank ?? "-"}</td>
                  <td>{row.name}</td>
                  <td>{row.matching_key}</td>
                  <td>{row.current_class ?? "-"}</td>
                  <td>
                    {row.total_score ?? "-"} / {row.max_score ?? "-"}
                  </td>
                  <td>{row.is_taken ? "응시" : "미응시"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h3>문항별 정답률·마킹 이상</h3>
          <table>
            <thead>
              <tr>
                <th>번호</th>
                <th>단원</th>
                <th>정답</th>
                <th>배점</th>
                <th>정답률</th>
                <th>오답</th>
                <th>무응답</th>
                <th>복수마킹</th>
              </tr>
            </thead>
            <tbody>
              {data.questions.map((question: any) => (
                <tr key={question.q_number}>
                  <td>{question.q_number}</td>
                  <td>
                    {question.unit_major}
                    {question.unit_minor ? ` > ${question.unit_minor}` : ""}
                  </td>
                  <td>{question.answer}</td>
                  <td>{question.points}</td>
                  <td>{question.correct_rate ?? "-"}%</td>
                  <td>{question.wrong_count}</td>
                  <td>{question.blank_count}</td>
                  <td>{question.multi_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
