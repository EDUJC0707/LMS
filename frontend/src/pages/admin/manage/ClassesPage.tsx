/**
 * /admin/classes — 반 목록 · 커리와 반 만들기.
 *
 * API
 *   GET  /api/admin/classes   커리로 묶은 반 목록(진행 주차·수강생 수)
 *   POST /api/admin/classes   {course_id | course_name+total_weeks, name, start_date}
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
import type { ClassList, ClassRow, CourseGroup } from "./types";

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
            dense
            caption="커리별 반 목록"
            columns={[
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

      <CreateClassModal
        open={creating}
        courses={courses}
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
  onClose,
  onCreated,
}: {
  open: boolean;
  courses: CourseGroup[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const [courseKey, setCourseKey] = useState<string>(NEW_COURSE);
  const [courseName, setCourseName] = useState("");
  const [totalWeeks, setTotalWeeks] = useState("");
  const [name, setName] = useState("");
  const [startDate, setStartDate] = useState("");

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
            course_name: courseName.trim(),
            total_weeks: Number(totalWeeks),
            name: name.trim(),
            start_date: startDate,
          }
        : { course_id: Number(courseKey), name: name.trim(), start_date: startDate },
    );
    if (!created) return;
    setCourseName("");
    setTotalWeeks("");
    setName("");
    setStartDate("");
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
      </form>
    </Modal>
  );
}
