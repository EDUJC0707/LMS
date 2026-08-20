/**
 * /admin/classes — 반 목록 · 커리와 반 만들기.
 *
 * API
 *   GET  /api/admin/classes   커리로 묶은 반 목록(진행 주차·수강생 수)
 *   POST /api/admin/classes   {course_id | course_name+total_weeks, name, start_date,
 *                              uses_payssam}
 *   GET  /api/admin/classes/{id}                       주차 + 명단
 *   POST /api/admin/classes/{id}/sessions              주차 추가
 *   PATCH/DELETE .../sessions/{week_no}                날짜 수정 · 주차 삭제
 *   POST /api/admin/classes/{id}/students              반 이동
 *   PUT  /api/admin/clinic/courses/{id}/hours          커리 클리닉 시간대
 *
 * 화면 설계
 * - 커리로 묶어 한 표에 둔다. 커리명은 그 묶음의 첫 줄에만 적는다 — 같은 커리를
 *   목반·화반이 같이 듣기 때문에(FLOW 1-1) 줄마다 반복하면 반이 안 읽힌다.
 *   그래서 이 표는 정렬을 열지 않는다(정렬하면 묶음이 흩어진다).
 * - 커리와 반은 한 화면에서 만든다(FLOW 1-2). 만드는 자리가 하나뿐이라 새
 *   커리를 여는 것과 이미 있는 커리에 반을 더하는 것이 같은 폼이고, 커리 칸을
 *   무엇으로 두느냐만 다르다.
 * - 개강일은 브라우저 날짜 칸(type=date)이다. 요일은 여기서 얻고(FLOW 1-2)
 *   회차 날짜는 서버가 주 단위로 채운다(FLOW 1-3).
 * - 과목은 고르기와 새로 적기가 둘 다 되어야 해서(FLOW 1-2) datalist 를 단
 *   입력 칸이다. 구분은 늘지 않으므로 그냥 select 다.
 * - 반을 누르면 그 반의 주차와 명단이 열린다. **날짜 칸을 고치는 것이 미는
 *   방법이다**(FLOW 1-3) — 밀기 버튼을 따로 두지 않는다. 뒤 주차가 따라
 *   움직이므로 저장 뒤에는 서버가 준 목록으로 통째로 갈아 끼운다.
 * - 주차 삭제는 **마지막 줄에만** 붙는다. 가운데를 지우면 번호에 구멍이 나고,
 *   번호를 다시 매기는 것은 FLOW 1-3 이 기각한 것이다.
 * - 반 이동은 명단 줄의 반 칸이다(FLOW 3-9). 고를 수 있는 것은 같은 커리의
 *   다른 반뿐이라 목록에서 이미 받은 묶음을 그대로 쓴다.
 * - **클리닉 시간대는 커리의 것이다**(FLOW 1-1) — 반 표 아래 커리 단위로 둔다.
 *   여기서 고치면 슬롯이 한 시간 단위로 다시 서고, 고친 날 이후부터만
 *   적용된다(FLOW 3-7). 반 줄에 붙이면 같은 커리를 듣는 목반·화반에 같은 칸이
 *   두 번 생겨 어느 쪽을 고쳐야 하는지 알 수 없다.
 */
import { FormEvent, useState } from "react";

import { http, useApi, useApiAction } from "../../../api";
import {
  Alert,
  Button,
  Card,
  ErrorState,
  Field,
  Input,
  Loading,
  Modal,
  Select,
  Table,
} from "../../../components";
import "./manage.css";
import type {
  ClassDetail,
  ClassList,
  ClassRow,
  ClassSessionRow,
  ClassStudentRow,
  CourseGroup,
  SubjectRow,
} from "./types";

/** 표에 깔 한 줄 — 반에 그 반이 속한 커리와 "묶음의 첫 줄인가"를 얹는다. */
interface Line extends ClassRow {
  course: CourseGroup;
  first: boolean;
}

function toLines(courses: CourseGroup[]): Line[] {
  return courses.flatMap((course) =>
    course.classes.map((klass, index) => ({ ...klass, course, first: index === 0 })),
  );
}

export default function ClassesPage() {
  const [creating, setCreating] = useState(false);
  const [opened, setOpened] = useState<Line | null>(null);

  const list = useApi(async () => {
    const { data } = await http.get<ClassList>("/admin/classes");
    return data;
  }, []);

  const courses = list.data?.courses ?? [];

  return (
    <>
      <Card
        title="반"
        actions={
          <Button variant="primary" onClick={() => setCreating(true)}>
            반 만들기
          </Button>
        }
        padding="none"
      >
        {list.loading ? (
          <Loading label="반을 불러오는 중…" />
        ) : list.error ? (
          <ErrorState description={list.error} onRetry={list.reload} />
        ) : (
          <Table<Line>
            rows={toLines(courses)}
            rowKey={(row) => row.class_id}
            onRowClick={(row) => setOpened(row)}
            dense
            caption="커리별 반 목록"
            columns={[
              {
                key: "subject",
                header: "과목",
                cell: (row) => (row.first ? (row.course.subject ?? "") : ""),
              },
              {
                key: "course",
                header: "커리",
                cell: (row) => (row.first ? row.course.name : ""),
              },
              { key: "name", header: "수강반명", cell: (row) => row.name },
              {
                key: "week",
                header: "주차",
                numeric: true,
                width: "8rem",
                cell: (row) => `${row.current_week}/${row.week_count}주차`,
              },
              {
                key: "students",
                header: "학생",
                numeric: true,
                width: "6rem",
                cell: (row) => `${row.student_count}명`,
              },
            ]}
          />
        )}
      </Card>

      <ClinicHoursCard courses={courses} onChanged={list.reload} />

      <ClassDetailModal
        line={opened}
        onClose={() => setOpened(null)}
        onChanged={() => void list.reload()}
      />

      <CreateClassModal
        open={creating}
        courses={courses}
        tracks={list.data?.tracks ?? []}
        subjects={list.data?.subjects ?? []}
        onClose={() => setCreating(false)}
        onCreated={() => {
          setCreating(false);
          void list.reload();
        }}
      />
    </>
  );
}

/* ── 커리 + 반 만들기 ───────────────────────────────────────────────── */

/** 커리 칸에서 "새 커리"를 고른 상태. course_id 와 섞이지 않는 값이면 된다. */
const NEW_COURSE = "new";

function CreateClassModal({
  open,
  courses,
  tracks,
  subjects,
  onClose,
  onCreated,
}: {
  open: boolean;
  courses: CourseGroup[];
  tracks: string[];
  subjects: SubjectRow[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const [courseKey, setCourseKey] = useState<string>(NEW_COURSE);
  const [track, setTrack] = useState("");
  const [subject, setSubject] = useState("");
  const [courseName, setCourseName] = useState("");
  const [totalWeeks, setTotalWeeks] = useState("");
  const [name, setName] = useState("");
  const [startDate, setStartDate] = useState("");
  // 교재값 수령처(FLOW 1-2 · 2-7). 장소로 자동 판정하지 않는다 — 러셀은 학원이
  // 따로 받으므로 결제선생이 나가면 학부모가 같은 값을 두 번 낸다.
  const [usesPayssam, setUsesPayssam] = useState("학원");

  const isNewCourse = courseKey === NEW_COURSE;

  const create = useApiAction(async (body: Record<string, unknown>) => {
    const { data } = await http.post<ClassRow>("/admin/classes", body);
    return data;
  });

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const created = await create.run(
      isNewCourse
        ? {
            track,
            subject: subject.trim(),
            course_name: courseName.trim(),
            total_weeks: Number(totalWeeks),
            name: name.trim(),
            start_date: startDate,
            uses_payssam: usesPayssam === "결제선생",
          }
        : {
            course_id: Number(courseKey),
            name: name.trim(),
            start_date: startDate,
            uses_payssam: usesPayssam === "결제선생",
          },
    );
    if (!created) return;
    setTrack("");
    setSubject("");
    setCourseName("");
    setTotalWeeks("");
    setName("");
    setStartDate("");
    setUsesPayssam("학원");
    onCreated();
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="반 만들기"
      footer={
        <>
          <Button onClick={onClose}>취소</Button>
          <Button variant="primary" type="submit" form="class-create" loading={create.pending}>
            만들기
          </Button>
        </>
      }
    >
      <form id="class-create" onSubmit={submit} className="ui-stack ui-stack--sm">
        {create.error && <Alert tone="danger">{create.error}</Alert>}

        <Field label="커리" required>
          {(props) => (
            <Select
              {...props}
              value={courseKey}
              onChange={(e) => setCourseKey(e.target.value)}
            >
              <option value={NEW_COURSE}>새 커리</option>
              {courses.map((course) => (
                <option key={course.course_id} value={course.course_id}>
                  {course.name}
                </option>
              ))}
            </Select>
          )}
        </Field>

        {isNewCourse && (
          <>
            <Field label="과목구분" required>
              {(props) => (
                <Select {...props} value={track} onChange={(e) => setTrack(e.target.value)}>
                  <option value="" />
                  {tracks.map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label="과목" required>
              {(props) => (
                <>
                  <Input
                    {...props}
                    list="class-create-subjects"
                    value={subject}
                    onChange={(e) => setSubject(e.target.value)}
                    autoComplete="off"
                  />
                  <datalist id="class-create-subjects">
                    {subjects
                      .filter((row) => row.track === track)
                      .map((row) => (
                        <option key={row.name} value={row.name} />
                      ))}
                  </datalist>
                </>
              )}
            </Field>
            <Field label="커리명" required>
              {(props) => (
                <Input
                  {...props}
                  value={courseName}
                  onChange={(e) => setCourseName(e.target.value)}
                  placeholder="2026 여름 N제"
                  autoComplete="off"
                />
              )}
            </Field>
            <Field label="총주차" required>
              {(props) => (
                <Input
                  {...props}
                  type="number"
                  min={1}
                  max={52}
                  value={totalWeeks}
                  onChange={(e) => setTotalWeeks(e.target.value)}
                  placeholder="10"
                />
              )}
            </Field>
          </>
        )}

        <Field label="수강반명" required>
          {(props) => (
            <Input
              {...props}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="목 6.5 대치러셀"
              autoComplete="off"
            />
          )}
        </Field>

        <Field label="개강일" required>
          {(props) => (
            <Input
              {...props}
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
          )}
        </Field>

        <Field label="교재값 수령처" required>
          {(props) => (
            <Select
              {...props}
              value={usesPayssam}
              onChange={(e) => setUsesPayssam(e.target.value)}
            >
              <option value="학원">학원</option>
              <option value="결제선생">결제선생</option>
            </Select>
          )}
        </Field>
      </form>
    </Modal>
  );
}

/* ── 반 하나 — 주차와 명단 ──────────────────────────────────────────── */

function ClassDetailModal({
  line,
  onClose,
  onChanged,
}: {
  line: Line | null;
  onClose: () => void;
  onChanged: () => void;
}) {
  const classId = line?.class_id ?? null;

  const detail = useApi(async () => {
    if (classId === null) return null;
    const { data } = await http.get<ClassDetail>(`/admin/classes/${classId}`);
    return data;
  }, [classId]);

  const sessions = detail.data?.sessions ?? [];
  const students = detail.data?.students ?? [];
  const siblings = (line?.course.classes ?? []).filter((k) => k.class_id !== classId);

  const edit = useApiAction(async (request: () => Promise<{ sessions: ClassSessionRow[] }>) => {
    const next = await request();
    detail.setData(detail.data ? { ...detail.data, sessions: next.sessions } : null);
    onChanged();
  });

  const move = useApiAction(async (studentId: number, toClassId: number) => {
    await http.post(`/admin/classes/${toClassId}/students`, { student_id: studentId });
    await detail.reload();
    onChanged();
  });

  const last = sessions.length ? sessions[sessions.length - 1].week_no : null;

  return (
    <Modal
      open={line !== null}
      onClose={onClose}
      title={line ? `${line.course.name} · ${line.name}` : ""}
      wide
      footer={<Button onClick={onClose}>닫기</Button>}
    >
      {detail.loading ? (
        <Loading label="반을 불러오는 중…" />
      ) : detail.error ? (
        <ErrorState description={detail.error} onRetry={detail.reload} />
      ) : (
        <div className="ui-stack">
          {edit.error && <Alert tone="danger">{edit.error}</Alert>}
          {move.error && <Alert tone="danger">{move.error}</Alert>}

          <Table<ClassSessionRow>
            rows={sessions}
            rowKey={(row) => row.week_no}
            dense
            caption="주차"
            columns={[
              {
                key: "week",
                header: "주차",
                numeric: true,
                width: "6rem",
                cell: (row) => `${row.week_no}주차`,
              },
              {
                key: "date",
                header: "날짜",
                width: "12rem",
                cell: (row) => (
                  <Input
                    type="date"
                    value={row.session_date}
                    onChange={(e) =>
                      void edit.run(async () => {
                        const { data } = await http.patch<{ sessions: ClassSessionRow[] }>(
                          `/admin/classes/${classId}/sessions/${row.week_no}`,
                          { session_date: e.target.value },
                        );
                        return data;
                      })
                    }
                  />
                ),
              },
              {
                key: "remove",
                header: "",
                width: "5rem",
                cell: (row) =>
                  row.week_no === last ? (
                    <Button
                      onClick={() =>
                        void edit.run(async () => {
                          const { data } = await http.delete<{ sessions: ClassSessionRow[] }>(
                            `/admin/classes/${classId}/sessions/${row.week_no}`,
                          );
                          return data;
                        })
                      }
                    >
                      삭제
                    </Button>
                  ) : null,
              },
            ]}
          />

          <Button
            loading={edit.pending}
            onClick={() =>
              void edit.run(async () => {
                const { data } = await http.post<{ sessions: ClassSessionRow[] }>(
                  `/admin/classes/${classId}/sessions`,
                );
                return data;
              })
            }
          >
            주차 추가
          </Button>

          <Table<ClassStudentRow>
            rows={students}
            rowKey={(row) => row.student_id}
            dense
            caption="명단"
            empty="학생이 없습니다"
            columns={[
              { key: "name", header: "이름", cell: (row) => row.name ?? "" },
              { key: "login", header: "원번", cell: (row) => row.login_id ?? "" },
              {
                key: "class",
                header: "반",
                width: "14rem",
                cell: (row) => (
                  <Select
                    value=""
                    disabled={move.pending || siblings.length === 0}
                    onChange={(e) => void move.run(row.student_id, Number(e.target.value))}
                  >
                    <option value="">{line?.name ?? ""}</option>
                    {siblings.map((k) => (
                      <option key={k.class_id} value={k.class_id}>
                        {k.name}
                      </option>
                    ))}
                  </Select>
                ),
              },
            ]}
          />
        </div>
      )}
    </Modal>
  );
}


/** 커리의 클리닉 시간대(FLOW 1-1). 비워 두면 그 커리는 클리닉을 안 연다. */
function ClinicHoursCard({
  courses,
  onChanged,
}: {
  courses: CourseGroup[];
  onChanged: () => void;
}) {
  // 입력 중인 값만 담는다 — 안 건드린 커리는 서버 값을 그대로 보여 준다.
  const [draft, setDraft] = useState<Record<number, { start: string; end: string }>>({});

  const save = useApiAction(async (courseId: number, start: string, end: string) => {
    await http.put(`/admin/clinic/courses/${courseId}/hours`, {
      clinic_start_time: start || null,
      clinic_end_time: end || null,
    });
    setDraft((prev) => {
      const next = { ...prev };
      delete next[courseId];
      return next;
    });
    onChanged();
  });

  const valueOf = (course: CourseGroup) =>
    draft[course.course_id] ?? {
      start: course.clinic_start_time ?? "",
      end: course.clinic_end_time ?? "",
    };

  const change = (course: CourseGroup, part: "start" | "end", value: string) =>
    setDraft((prev) => ({ ...prev, [course.course_id]: { ...valueOf(course), [part]: value } }));

  if (!courses.length) return null;

  return (
    <Card title="클리닉 시간대" padding="none">
      {save.error && <Alert tone="danger">{save.error}</Alert>}
      <Table<CourseGroup>
        rows={courses}
        rowKey={(row) => row.course_id}
        dense
        caption="커리별 클리닉 시간대"
        columns={[
          { key: "course", header: "커리", cell: (row) => row.name },
          {
            key: "start",
            header: "시작",
            width: "9rem",
            cell: (row) => (
              <Input
                type="time"
                step={3600}
                value={valueOf(row).start}
                onChange={(e) => change(row, "start", e.target.value)}
              />
            ),
          },
          {
            key: "end",
            header: "종료",
            width: "9rem",
            cell: (row) => (
              <Input
                type="time"
                step={3600}
                value={valueOf(row).end}
                onChange={(e) => change(row, "end", e.target.value)}
              />
            ),
          },
          {
            key: "save",
            header: "",
            width: "6rem",
            cell: (row) =>
              draft[row.course_id] ? (
                <Button
                  disabled={save.pending}
                  onClick={() =>
                    void save.run(row.course_id, valueOf(row).start, valueOf(row).end)
                  }
                >
                  저장
                </Button>
              ) : null,
          },
        ]}
      />
    </Card>
  );
}
