/**
 * 자녀 교재 결제 — GET /api/parent/payments?student_id= ·
 * POST /api/parent/payments/bill (PRD 3.1.5 양측 결제, 3.4 학부모 액션)
 *
 * **등록 여부를 보지 않는다.** 다른 학부모 화면(성적·워크북·동보)은 예비등록
 * 자녀에게 PreEnrollNotice 를 띄우지만, 교재 구매는 예비등록생에게 열려 있는
 * 바로 그 기능이다(PRD §4). 여기서 막으면 신규생이 교재를 못 산다.
 *
 * 학생이 이미 눌렀으면 서버가 다시 보내지 않고 기존 청구서를 돌려준다
 * (중복 차단은 경로가 아니라 학생×교재 짝으로 판정 — billing.start_billing).
 */
import { Card, EmptyState, ScopeBar } from "../../components";
import { PaymentPanel } from "../../features/payments/PaymentPanel";
import { NO_CHILD_TITLE, useChild } from "./childContext";
import "./parent.css";

export default function ParentPaymentPage() {
  const { studentId, picker } = useChild();

  return (
    <>
      {picker && <ScopeBar>{picker}</ScopeBar>}

      {studentId === null ? (
        <Card padding="none">
          <EmptyState title={NO_CHILD_TITLE} />
        </Card>
      ) : (
        <PaymentPanel
          ordersPath="/parent/payments"
          billPath="/parent/payments/bill"
          studentId={studentId}
        />
      )}
    </>
  );
}
