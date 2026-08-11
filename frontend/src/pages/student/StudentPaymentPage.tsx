/**
 * 학생 교재 결제 — GET /api/student/payments · POST /api/student/payments/bill
 * (PRD 3.1.5 양측 결제, 3.2.5 교재 구매)
 *
 * **예비등록생에게도 열린다.** 신규 계정이 거의 bare 인 상태에서 유일하게
 * 쓸 수 있는 기능이 교재 구매다(PRD §4 상태 기반 노출) — 그래서 이 화면만
 * auth/nav.ts 에서 enrolled 게이트를 쓰지 않는다.
 */
import { PaymentPanel } from "../../features/payments/PaymentPanel";
import "./student.css";

export default function StudentPaymentPage() {
  return <PaymentPanel ordersPath="/student/payments" billPath="/student/payments/bill" />;
}
