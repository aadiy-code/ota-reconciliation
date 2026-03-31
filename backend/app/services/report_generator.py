import io
import csv
from datetime import datetime
from typing import Optional, List
from sqlalchemy.orm import Session

from ..models.db_models import ReconciliationResult, NormalizedBooking, ReconciliationRun
from .reconciliation_engine import ReconciliationSummary


class ReportGeneratorService:
    def _get_results_with_bookings(
        self,
        run_id: str,
        db: Session,
        exceptions_only: bool = False,
    ) -> List[dict]:
        EXCEPTION_STATUSES = {
            "missing_in_pms", "missing_in_ota", "duplicate_in_pms",
            "duplicate_in_ota", "cancellation_mismatch", "modification_mismatch",
            "amount_mismatch", "pending_review",
        }

        query = db.query(ReconciliationResult).filter(
            ReconciliationResult.reconciliation_run_id == run_id
        )
        if exceptions_only:
            query = query.filter(
                ReconciliationResult.reconciliation_status.in_(EXCEPTION_STATUSES)
            )

        results = query.all()
        rows = []
        for r in results:
            ota = db.query(NormalizedBooking).filter(NormalizedBooking.id == r.ota_booking_id).first() if r.ota_booking_id else None
            pms = db.query(NormalizedBooking).filter(NormalizedBooking.id == r.pms_booking_id).first() if r.pms_booking_id else None

            row = {
                "result_id": r.id,
                "reconciliation_status": r.reconciliation_status,
                "confidence_score": r.confidence_score,
                "matched_rule": r.matched_rule,
                "reason_codes": ", ".join(r.reason_codes_json or []),
                "explanation": r.explanation_text,
                "review_decision": r.review_decision,
                "reviewed_by": r.reviewed_by,
                "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else "",
                "review_notes": r.review_notes,
                "is_manual_override": r.is_manual_override,
                # OTA fields
                "ota_reservation_id": ota.external_reservation_id if ota else "",
                "ota_platform": ota.source_platform if ota else "",
                "ota_guest_name": ota.guest_name_raw if ota else "",
                "ota_check_in": ota.check_in_date.isoformat() if (ota and ota.check_in_date) else "",
                "ota_check_out": ota.check_out_date.isoformat() if (ota and ota.check_out_date) else "",
                "ota_room_type": ota.room_type_raw if ota else "",
                "ota_status": ota.booking_status if ota else "",
                "ota_gross_amount": ota.gross_amount if ota else "",
                "ota_net_amount": ota.net_amount if ota else "",
                "ota_commission": ota.commission_amount if ota else "",
                # PMS fields
                "pms_reservation_id": pms.pms_reservation_id if pms else "",
                "pms_ota_reference": pms.channel_reference_id if pms else "",
                "pms_guest_name": pms.guest_name_raw if pms else "",
                "pms_check_in": pms.check_in_date.isoformat() if (pms and pms.check_in_date) else "",
                "pms_check_out": pms.check_out_date.isoformat() if (pms and pms.check_out_date) else "",
                "pms_room_type": pms.room_type_raw if pms else "",
                "pms_status": pms.booking_status if pms else "",
                "pms_gross_amount": pms.gross_amount if pms else "",
                "pms_net_amount": pms.net_amount if pms else "",
            }
            rows.append(row)
        return rows

    def export_to_csv(
        self,
        run_id: str,
        db: Session,
        include_exceptions_only: bool = False,
    ) -> bytes:
        rows = self._get_results_with_bookings(run_id, db, include_exceptions_only)
        if not rows:
            return b""

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue().encode("utf-8")

    def export_to_xlsx(self, run_id: str, db: Session) -> bytes:
        try:
            import xlsxwriter
        except ImportError:
            raise ImportError("xlsxwriter is required for Excel export")

        rows = self._get_results_with_bookings(run_id, db)

        run = db.query(ReconciliationRun).filter(ReconciliationRun.id == run_id).first()
        summary = run.summary_json or {} if run else {}

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})

        # Formats
        header_fmt = workbook.add_format({
            "bold": True, "bg_color": "#1F4E79", "font_color": "white",
            "border": 1, "align": "center", "valign": "vcenter",
        })
        green_fmt = workbook.add_format({"bg_color": "#C6EFCE", "font_color": "#276221"})
        yellow_fmt = workbook.add_format({"bg_color": "#FFEB9C", "font_color": "#9C6500"})
        red_fmt = workbook.add_format({"bg_color": "#FFC7CE", "font_color": "#9C0006"})
        orange_fmt = workbook.add_format({"bg_color": "#FFDCA8", "font_color": "#833C00"})
        number_fmt = workbook.add_format({"num_format": "#,##0.00"})
        date_fmt = workbook.add_format({"num_format": "dd/mm/yyyy"})

        # --- Sheet 1: Summary ---
        ws_summary = workbook.add_worksheet("Summary")
        ws_summary.set_column(0, 0, 35)
        ws_summary.set_column(1, 1, 20)
        ws_summary.write(0, 0, "OTA Reconciliation Summary", workbook.add_format({"bold": True, "font_size": 14}))
        ws_summary.write(1, 0, f"Run ID: {run_id}")
        ws_summary.write(2, 0, f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")

        summary_rows = [
            ("Total OTA Bookings", summary.get("total_ota_bookings", 0)),
            ("Total PMS Bookings", summary.get("total_pms_bookings", 0)),
            ("Matched (Perfect)", summary.get("matched", 0)),
            ("Matched with Minor Variance", summary.get("matched_with_minor_variance", 0)),
            ("Missing in PMS", summary.get("missing_in_pms", 0)),
            ("Missing in OTA", summary.get("missing_in_ota", 0)),
            ("Duplicate in PMS", summary.get("duplicate_in_pms", 0)),
            ("Duplicate in OTA", summary.get("duplicate_in_ota", 0)),
            ("Cancellation Mismatch", summary.get("cancellation_mismatch", 0)),
            ("Modification Mismatch", summary.get("modification_mismatch", 0)),
            ("Amount Mismatch", summary.get("amount_mismatch", 0)),
            ("Pending Review", summary.get("pending_review", 0)),
            ("Match Rate %", f"{summary.get('match_rate_percent', 0):.1f}%"),
        ]
        for i, (label, value) in enumerate(summary_rows, start=4):
            ws_summary.write(i, 0, label)
            ws_summary.write(i, 1, value)

        # --- Sheet 2: All Results ---
        self._write_results_sheet(workbook, "All Results", rows, header_fmt, green_fmt, yellow_fmt, red_fmt, orange_fmt)

        # --- Sheet 3: Exceptions ---
        exception_rows = [r for r in rows if r["reconciliation_status"] not in ("matched", "matched_with_minor_variance")]
        self._write_results_sheet(workbook, "Exceptions", exception_rows, header_fmt, green_fmt, yellow_fmt, red_fmt, orange_fmt)

        # --- Sheet 4: Missing in PMS ---
        mip_rows = [r for r in rows if r["reconciliation_status"] == "missing_in_pms"]
        self._write_results_sheet(workbook, "Missing in PMS", mip_rows, header_fmt, green_fmt, yellow_fmt, red_fmt, orange_fmt)

        # --- Sheet 5: Missing in OTA ---
        mio_rows = [r for r in rows if r["reconciliation_status"] == "missing_in_ota"]
        self._write_results_sheet(workbook, "Missing in OTA", mio_rows, header_fmt, green_fmt, yellow_fmt, red_fmt, orange_fmt)

        workbook.close()
        output.seek(0)
        return output.read()

    def _write_results_sheet(self, workbook, sheet_name, rows, header_fmt, green_fmt, yellow_fmt, red_fmt, orange_fmt):
        ws = workbook.add_worksheet(sheet_name[:31])
        if not rows:
            ws.write(0, 0, "No data")
            return

        headers = list(rows[0].keys())
        for col, h in enumerate(headers):
            ws.write(0, col, h, header_fmt)
            ws.set_column(col, col, max(12, len(h) + 2))

        STATUS_FORMATS = {
            "matched": green_fmt,
            "matched_with_minor_variance": yellow_fmt,
            "missing_in_pms": red_fmt,
            "missing_in_ota": red_fmt,
            "cancellation_mismatch": red_fmt,
            "amount_mismatch": orange_fmt,
            "duplicate_in_pms": orange_fmt,
            "duplicate_in_ota": orange_fmt,
            "pending_review": yellow_fmt,
            "modification_mismatch": orange_fmt,
        }

        for row_idx, row in enumerate(rows, start=1):
            status = row.get("reconciliation_status", "")
            row_fmt = STATUS_FORMATS.get(status)
            for col_idx, key in enumerate(headers):
                val = row[key]
                if row_fmt:
                    ws.write(row_idx, col_idx, val, row_fmt)
                else:
                    ws.write(row_idx, col_idx, val)

    def generate_html_summary(self, summary: ReconciliationSummary) -> str:
        match_rate = summary.match_rate_percent
        color = "#27ae60" if match_rate >= 80 else "#f39c12" if match_rate >= 60 else "#e74c3c"

        html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Reconciliation Summary</title></head>
<body style="font-family: Arial, sans-serif; max-width: 700px; margin: 0 auto; padding: 20px;">
  <h2 style="color: #1F4E79;">OTA Reconciliation Summary</h2>
  <p>Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</p>
  <div style="background: {color}; color: white; padding: 15px; border-radius: 8px; text-align: center; margin: 20px 0;">
    <h1 style="margin: 0;">{match_rate:.1f}%</h1>
    <p style="margin: 5px 0;">Match Rate</p>
  </div>
  <table style="width: 100%; border-collapse: collapse;">
    <tr style="background: #1F4E79; color: white;">
      <th style="padding: 8px; text-align: left;">Category</th>
      <th style="padding: 8px; text-align: right;">Count</th>
    </tr>
    <tr><td style="padding: 8px; border-bottom: 1px solid #ddd;">Total OTA Bookings</td><td style="padding: 8px; text-align: right; border-bottom: 1px solid #ddd;">{summary.total_ota_bookings}</td></tr>
    <tr><td style="padding: 8px; border-bottom: 1px solid #ddd;">Total PMS Bookings</td><td style="padding: 8px; text-align: right; border-bottom: 1px solid #ddd;">{summary.total_pms_bookings}</td></tr>
    <tr style="background: #C6EFCE;"><td style="padding: 8px;">Matched</td><td style="padding: 8px; text-align: right;">{summary.matched}</td></tr>
    <tr style="background: #FFEB9C;"><td style="padding: 8px;">Matched with Minor Variance</td><td style="padding: 8px; text-align: right;">{summary.matched_with_minor_variance}</td></tr>
    <tr style="background: #FFC7CE;"><td style="padding: 8px;">Missing in PMS</td><td style="padding: 8px; text-align: right;">{summary.missing_in_pms}</td></tr>
    <tr style="background: #FFC7CE;"><td style="padding: 8px;">Missing in OTA</td><td style="padding: 8px; text-align: right;">{summary.missing_in_ota}</td></tr>
    <tr style="background: #FFDCA8;"><td style="padding: 8px;">Duplicates in PMS</td><td style="padding: 8px; text-align: right;">{summary.duplicate_in_pms}</td></tr>
    <tr style="background: #FFDCA8;"><td style="padding: 8px;">Duplicates in OTA</td><td style="padding: 8px; text-align: right;">{summary.duplicate_in_ota}</td></tr>
    <tr style="background: #FFC7CE;"><td style="padding: 8px;">Cancellation Mismatch</td><td style="padding: 8px; text-align: right;">{summary.cancellation_mismatch}</td></tr>
    <tr style="background: #FFDCA8;"><td style="padding: 8px;">Amount Mismatch</td><td style="padding: 8px; text-align: right;">{summary.amount_mismatch}</td></tr>
    <tr style="background: #FFEB9C;"><td style="padding: 8px;">Pending Review</td><td style="padding: 8px; text-align: right;">{summary.pending_review}</td></tr>
  </table>
  <p style="color: #666; font-size: 12px; margin-top: 20px;">This report was generated automatically by the OTA Reconciliation System.</p>
</body>
</html>"""
        return html
