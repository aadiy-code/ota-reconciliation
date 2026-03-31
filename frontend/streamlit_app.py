"""
OTA Reconciliation System - Streamlit Frontend
Calls the FastAPI backend at http://localhost:8000
"""

import time
import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from typing import Optional, List, Dict, Any

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────
import os
API_BASE = os.environ.get("API_BASE_URL", "http://localhost:8000/api/v1")

st.set_page_config(
    page_title="OTA Reconciliation System",
    page_icon="🏨",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
# Session State Initialization
# ─────────────────────────────────────────────
if "page" not in st.session_state:
    st.session_state.page = "Upload & Run"
if "selected_run_id" not in st.session_state:
    st.session_state.selected_run_id = None
if "api_base" not in st.session_state:
    st.session_state.api_base = API_BASE


# ─────────────────────────────────────────────
# API Helpers
# ─────────────────────────────────────────────
def api_get(path: str, params: dict = None) -> Optional[Dict]:
    try:
        r = requests.get(f"{st.session_state.api_base}{path}", params=params, timeout=30)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        st.error("Cannot connect to backend API. Make sure the FastAPI server is running on port 8000.")
        return None
    except Exception as e:
        st.error(f"API error: {str(e)}")
        return None


def api_post(path: str, data: dict = None, files=None) -> Optional[Dict]:
    try:
        if files:
            r = requests.post(f"{st.session_state.api_base}{path}", files=files, data=data, timeout=60)
        else:
            r = requests.post(f"{st.session_state.api_base}{path}", json=data, timeout=60)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        st.error("Cannot connect to backend API. Make sure the FastAPI server is running on port 8000.")
        return None
    except Exception as e:
        st.error(f"API error: {str(e)}")
        return None


def api_delete(path: str) -> Optional[Dict]:
    try:
        r = requests.delete(f"{st.session_state.api_base}{path}", timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        st.error("Cannot connect to backend API.")
        return None
    except Exception as e:
        st.error(f"API error: {str(e)}")
        return None


def check_api_health() -> bool:
    try:
        r = requests.get(f"{st.session_state.api_base}/health", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


# ─────────────────────────────────────────────
# Status Color Helpers
# ─────────────────────────────────────────────
STATUS_COLORS = {
    "matched": "#27ae60",
    "matched_with_minor_variance": "#f39c12",
    "missing_in_pms": "#e74c3c",
    "missing_in_ota": "#c0392b",
    "duplicate_in_pms": "#e67e22",
    "duplicate_in_ota": "#d35400",
    "cancellation_mismatch": "#8e44ad",
    "modification_mismatch": "#2980b9",
    "amount_mismatch": "#e74c3c",
    "source_mismatch": "#7f8c8d",
    "pending_review": "#f39c12",
}

STATUS_LABELS = {
    "matched": "Matched",
    "matched_with_minor_variance": "Minor Variance",
    "missing_in_pms": "Missing in PMS",
    "missing_in_ota": "Missing in OTA",
    "duplicate_in_pms": "Duplicate PMS",
    "duplicate_in_ota": "Duplicate OTA",
    "cancellation_mismatch": "Cancellation Mismatch",
    "modification_mismatch": "Modification Mismatch",
    "amount_mismatch": "Amount Mismatch",
    "source_mismatch": "Source Mismatch",
    "pending_review": "Pending Review",
}


def status_badge(status: str) -> str:
    color = STATUS_COLORS.get(status, "#7f8c8d")
    label = STATUS_LABELS.get(status, status)
    return f'<span style="background:{color};color:white;padding:2px 8px;border-radius:4px;font-size:12px;">{label}</span>'


# ─────────────────────────────────────────────
# Sidebar Navigation
# ─────────────────────────────────────────────
def render_sidebar():
    with st.sidebar:
        st.title("OTA Reconciliation")
        st.markdown("---")

        pages = [
            "Upload & Run",
            "Dashboard",
            "Exception Review",
            "Results Explorer",
            "Mapping Rules",
            "Audit Log",
        ]

        for page in pages:
            if st.button(page, use_container_width=True,
                         type="primary" if st.session_state.page == page else "secondary"):
                st.session_state.page = page
                st.rerun()

        st.markdown("---")

        # API Status
        healthy = check_api_health()
        if healthy:
            st.success("API: Connected")
        else:
            st.error("API: Disconnected")

        st.markdown("---")
        st.caption("OTA Reconciliation v1.0.0")

        # API Base URL config
        with st.expander("Settings"):
            new_base = st.text_input("API Base URL", value=st.session_state.api_base)
            if new_base != st.session_state.api_base:
                st.session_state.api_base = new_base
                st.rerun()


# ─────────────────────────────────────────────
# Page 1: Upload & Run
# ─────────────────────────────────────────────
def page_upload_run():
    st.title("Upload Files & Start Reconciliation")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Booking.com Files")
        bc_files = st.file_uploader(
            "Upload Booking.com export files",
            type=["csv", "xlsx", "xls"],
            accept_multiple_files=True,
            key="bc_uploader",
        )

        st.subheader("Expedia Files")
        exp_files = st.file_uploader(
            "Upload Expedia export files",
            type=["csv", "xlsx", "xls"],
            accept_multiple_files=True,
            key="exp_uploader",
        )

    with col2:
        st.subheader("PMS File")
        pms_files = st.file_uploader(
            "Upload PMS export file",
            type=["csv", "xlsx", "xls"],
            accept_multiple_files=True,
            key="pms_uploader",
        )

        st.subheader("Configuration")
        hotel_id = st.text_input("Hotel ID (optional)", placeholder="e.g. HOTEL001")
        triggered_by = st.text_input("Triggered By", value="user")

    st.markdown("---")

    all_files = list(bc_files or []) + list(exp_files or []) + list(pms_files or [])

    if all_files:
        st.subheader(f"Files Ready ({len(all_files)} files)")

    if st.button("Start Reconciliation", type="primary", disabled=len(all_files) == 0):
        if not all_files:
            st.warning("Please upload at least one file before starting.")
            return

        with st.spinner("Uploading files..."):
            uploaded_file_ids = []
            upload_results = []

            for f in all_files:
                files_payload = [("files", (f.name, f.getvalue(), "application/octet-stream"))]
                result = api_post("/files/upload", files=files_payload)
                if result and isinstance(result, list) and len(result) > 0:
                    file_info = result[0]
                    uploaded_file_ids.append(file_info["file_id"])
                    upload_results.append(file_info)
                elif result:
                    st.warning(f"Unexpected response for {f.name}")

        if upload_results:
            st.subheader("Detected Platforms")
            for info in upload_results:
                platform_color = {
                    "booking_com": "#003580",
                    "expedia": "#FFC72C",
                    "pms": "#27ae60",
                    "unknown": "#7f8c8d",
                }.get(info.get("source_platform", "unknown"), "#7f8c8d")

                col_a, col_b, col_c, col_d = st.columns(4)
                with col_a:
                    st.write(f"**{info.get('file_name', 'Unknown')}**")
                with col_b:
                    st.markdown(
                        f'<span style="background:{platform_color};color:white;padding:3px 8px;border-radius:4px;">'
                        f'{info.get("source_platform", "unknown").upper()}</span>',
                        unsafe_allow_html=True,
                    )
                with col_c:
                    conf = info.get("classifier_confidence", 0) * 100
                    st.write(f"Confidence: {conf:.0f}%")
                with col_d:
                    st.write(f"Rows: {info.get('row_count', 0)}")

        if uploaded_file_ids:
            with st.spinner("Starting reconciliation run..."):
                run_payload = {
                    "file_ids": uploaded_file_ids,
                    "hotel_id": hotel_id or None,
                    "triggered_by": triggered_by or "user",
                }
                run_result = api_post("/reconciliation/start", run_payload)

            if run_result:
                run_id = run_result.get("id")
                st.success(f"Reconciliation started! Run ID: `{run_id}`")
                st.session_state.selected_run_id = run_id

                # Poll for completion
                with st.spinner("Running reconciliation... (this may take a moment)"):
                    for _ in range(30):
                        time.sleep(1)
                        run_status = api_get(f"/reconciliation/runs/{run_id}")
                        if run_status and run_status.get("status") in ("completed", "failed"):
                            break

                if run_status:
                    if run_status.get("status") == "completed":
                        st.success("Reconciliation completed!")
                        summary = run_status.get("summary_json", {})
                        if summary:
                            c1, c2, c3, c4, c5 = st.columns(5)
                            c1.metric("Match Rate", f"{summary.get('match_rate_percent', 0):.1f}%")
                            c2.metric("Matched", summary.get("matched", 0))
                            c3.metric("Missing in PMS", summary.get("missing_in_pms", 0))
                            c4.metric("Missing in OTA", summary.get("missing_in_ota", 0))
                            c5.metric("Pending Review", summary.get("pending_review", 0))

                        if st.button("View Full Dashboard"):
                            st.session_state.page = "Dashboard"
                            st.rerun()
                    else:
                        st.error("Reconciliation failed. Check the logs.")


# ─────────────────────────────────────────────
# Page 2: Dashboard
# ─────────────────────────────────────────────
def page_dashboard():
    st.title("Reconciliation Dashboard")

    # Run selector
    runs_data = api_get("/reconciliation/runs", {"limit": 50})
    if not runs_data:
        st.info("No reconciliation runs found. Go to Upload & Run to start one.")
        return

    run_options = {
        f"Run {r['id'][:8]}... | {r['status'].upper()} | {r.get('run_started_at', '')[:16]}": r["id"]
        for r in runs_data
    }

    if not run_options:
        st.info("No runs available.")
        return

    selected_label = st.selectbox("Select Reconciliation Run", list(run_options.keys()))
    run_id = run_options[selected_label]

    if run_id != st.session_state.selected_run_id:
        st.session_state.selected_run_id = run_id

    run_detail = api_get(f"/reconciliation/runs/{run_id}")
    if not run_detail:
        return

    if run_detail.get("status") != "completed":
        st.warning(f"Run status: {run_detail.get('status', 'unknown').upper()}")
        if st.button("Refresh"):
            st.rerun()
        return

    summary = run_detail.get("summary_json", {})
    if not summary:
        st.info("No summary data available.")
        return

    # Summary metrics
    st.subheader("Summary")
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    match_rate = summary.get("match_rate_percent", 0)

    col1.metric("Match Rate", f"{match_rate:.1f}%",
                delta="Good" if match_rate >= 80 else "Needs Attention")
    col2.metric("Total OTA", summary.get("total_ota_bookings", 0))
    col3.metric("Total PMS", summary.get("total_pms_bookings", 0))
    col4.metric("Matched", summary.get("matched", 0) + summary.get("matched_with_minor_variance", 0))
    col5.metric("Exceptions", summary.get("missing_in_pms", 0) + summary.get("missing_in_ota", 0) +
                summary.get("amount_mismatch", 0) + summary.get("cancellation_mismatch", 0))
    col6.metric("Pending Review", summary.get("pending_review", 0))

    st.markdown("---")

    # Charts
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("Results Breakdown")
        chart_data = {
            "Matched": summary.get("matched", 0),
            "Minor Variance": summary.get("matched_with_minor_variance", 0),
            "Missing in PMS": summary.get("missing_in_pms", 0),
            "Missing in OTA": summary.get("missing_in_ota", 0),
            "Dup PMS": summary.get("duplicate_in_pms", 0),
            "Dup OTA": summary.get("duplicate_in_ota", 0),
            "Cancel Mismatch": summary.get("cancellation_mismatch", 0),
            "Amt Mismatch": summary.get("amount_mismatch", 0),
            "Pending Review": summary.get("pending_review", 0),
        }
        chart_data = {k: v for k, v in chart_data.items() if v > 0}

        if chart_data:
            df_chart = pd.DataFrame(list(chart_data.items()), columns=["Category", "Count"])
            colors = ["#27ae60", "#f39c12", "#e74c3c", "#c0392b",
                      "#e67e22", "#d35400", "#8e44ad", "#e74c3c", "#f39c12"]
            fig = px.bar(df_chart, x="Category", y="Count",
                         color="Category",
                         color_discrete_sequence=colors[:len(chart_data)],
                         title="Reconciliation Results by Category")
            fig.update_layout(showlegend=False, xaxis_tickangle=-30)
            st.plotly_chart(fig, use_container_width=True)

    with col_right:
        st.subheader("Match Status Distribution")
        matched_total = summary.get("matched", 0) + summary.get("matched_with_minor_variance", 0)
        exceptions_total = (
            summary.get("missing_in_pms", 0) + summary.get("missing_in_ota", 0) +
            summary.get("duplicate_in_pms", 0) + summary.get("duplicate_in_ota", 0) +
            summary.get("cancellation_mismatch", 0) + summary.get("modification_mismatch", 0) +
            summary.get("amount_mismatch", 0) + summary.get("pending_review", 0)
        )

        pie_labels = ["Matched", "Exceptions"]
        pie_values = [matched_total, exceptions_total]
        pie_colors = ["#27ae60", "#e74c3c"]

        fig2 = go.Figure(data=[go.Pie(
            labels=pie_labels,
            values=pie_values,
            marker=dict(colors=pie_colors),
            hole=0.4,
        )])
        fig2.update_layout(title="Overall Match Rate")
        st.plotly_chart(fig2, use_container_width=True)

    st.markdown("---")

    # Detailed breakdown table
    st.subheader("Detailed Breakdown")
    breakdown = [
        {"Status": "Matched (Perfect)", "Count": summary.get("matched", 0), "Action Required": "No"},
        {"Status": "Matched with Minor Variance", "Count": summary.get("matched_with_minor_variance", 0), "Action Required": "Optional Review"},
        {"Status": "Missing in PMS", "Count": summary.get("missing_in_pms", 0), "Action Required": "Yes - Investigate"},
        {"Status": "Missing in OTA", "Count": summary.get("missing_in_ota", 0), "Action Required": "Yes - Investigate"},
        {"Status": "Duplicate in PMS", "Count": summary.get("duplicate_in_pms", 0), "Action Required": "Yes - Resolve Duplicate"},
        {"Status": "Duplicate in OTA", "Count": summary.get("duplicate_in_ota", 0), "Action Required": "Yes - Resolve Duplicate"},
        {"Status": "Cancellation Mismatch", "Count": summary.get("cancellation_mismatch", 0), "Action Required": "Yes - Critical"},
        {"Status": "Modification Mismatch", "Count": summary.get("modification_mismatch", 0), "Action Required": "Yes - Review"},
        {"Status": "Amount Mismatch", "Count": summary.get("amount_mismatch", 0), "Action Required": "Yes - Financial Impact"},
        {"Status": "Pending Review", "Count": summary.get("pending_review", 0), "Action Required": "Yes - Review Queue"},
    ]
    df_breakdown = pd.DataFrame(breakdown)
    st.dataframe(df_breakdown, use_container_width=True, hide_index=True)

    # Export buttons
    st.markdown("---")
    st.subheader("Export")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Download CSV Report"):
            try:
                r = requests.get(f"{st.session_state.api_base}/reconciliation/runs/{run_id}/export",
                                 params={"format": "csv"}, timeout=30)
                st.download_button("Save CSV", r.content, f"reconciliation_{run_id[:8]}.csv", "text/csv")
            except Exception as e:
                st.error(f"Export failed: {e}")
    with c2:
        if st.button("Download Excel Report"):
            try:
                r = requests.get(f"{st.session_state.api_base}/reconciliation/runs/{run_id}/export",
                                 params={"format": "xlsx"}, timeout=30)
                st.download_button("Save Excel", r.content, f"reconciliation_{run_id[:8]}.xlsx",
                                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            except Exception as e:
                st.error(f"Export failed: {e}")


# ─────────────────────────────────────────────
# Page 3: Exception Review
# ─────────────────────────────────────────────
def page_exception_review():
    st.title("Exception Review Queue")

    run_id = st.session_state.selected_run_id
    if not run_id:
        runs_data = api_get("/reconciliation/runs", {"limit": 10})
        if runs_data:
            options = {f"{r['id'][:8]}... {r.get('status', '')}": r["id"] for r in runs_data}
            sel = st.selectbox("Select a run", list(options.keys()))
            run_id = options[sel]
        else:
            st.info("No runs found. Please run reconciliation first.")
            return

    # Filters
    st.subheader("Filters")
    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        filter_status = st.selectbox("Status", ["All", "missing_in_pms", "missing_in_ota",
                                                 "amount_mismatch", "cancellation_mismatch",
                                                 "duplicate_in_pms", "duplicate_in_ota",
                                                 "pending_review", "modification_mismatch"])
    with fc2:
        min_conf = st.slider("Min Confidence", 0, 100, 0)
    with fc3:
        max_conf = st.slider("Max Confidence", 0, 100, 100)

    params = {
        "min_confidence": min_conf,
        "max_confidence": max_conf,
    }
    if filter_status != "All":
        params["status"] = filter_status

    exceptions_data = api_get(f"/reconciliation/runs/{run_id}/exceptions", params)
    if not exceptions_data:
        st.info("No exceptions found for this run.")
        return

    exceptions = exceptions_data.get("exceptions", [])
    total = exceptions_data.get("total", 0)

    st.write(f"**{total} exception(s) found**")

    if not exceptions:
        st.success("No exceptions match the current filters.")
        return

    for i, exc in enumerate(exceptions):
        status = exc.get("reconciliation_status", "unknown")
        color = STATUS_COLORS.get(status, "#7f8c8d")
        label = STATUS_LABELS.get(status, status)
        conf = exc.get("confidence_score", 0)

        ota = exc.get("ota_booking") or {}
        pms = exc.get("pms_booking") or {}

        ota_guest = ota.get("guest_name_raw", "—")
        pms_guest = pms.get("guest_name_raw", "—")
        ota_ref = ota.get("external_reservation_id", "—")
        pms_ref = pms.get("channel_reference_id", pms.get("pms_reservation_id", "—"))

        with st.expander(
            f"[{i+1}] {label} | OTA: {ota_guest} ({ota_ref}) | Confidence: {conf:.0f}%"
        ):
            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown(f"**OTA Booking** (Platform: {ota.get('source_platform', '—')})")
                if ota:
                    st.json({
                        "Reservation ID": ota.get("external_reservation_id", "—"),
                        "Guest": ota.get("guest_name_raw", "—"),
                        "Check-in": ota.get("check_in_date", "—"),
                        "Check-out": ota.get("check_out_date", "—"),
                        "Room Type": ota.get("room_type_raw", "—"),
                        "Status": ota.get("booking_status", "—"),
                        "Amount": f"INR {ota.get('gross_amount', 0):,.2f}" if ota.get("gross_amount") else "—",
                        "Payment": ota.get("payment_type", "—"),
                    })
                else:
                    st.write("No OTA booking data")

            with col_b:
                st.markdown("**PMS Booking**")
                if pms:
                    st.json({
                        "PMS ID": pms.get("pms_reservation_id", "—"),
                        "OTA Reference": pms.get("channel_reference_id", "—"),
                        "Guest": pms.get("guest_name_raw", "—"),
                        "Check-in": pms.get("check_in_date", "—"),
                        "Check-out": pms.get("check_out_date", "—"),
                        "Room Type": pms.get("room_type_raw", "—"),
                        "Status": pms.get("booking_status", "—"),
                        "Amount": f"INR {pms.get('gross_amount', 0):,.2f}" if pms.get("gross_amount") else "—",
                        "Net Amount": f"INR {pms.get('net_amount', 0):,.2f}" if pms.get("net_amount") else "—",
                    })
                else:
                    st.write("No PMS booking data")

            st.markdown("**Explanation:**")
            st.info(exc.get("explanation_text", "No explanation available."))

            reason_codes = exc.get("reason_codes", [])
            if reason_codes:
                st.markdown("**Reason Codes:** " + ", ".join(f"`{rc}`" for rc in reason_codes))

            if exc.get("review_decision"):
                st.success(f"Already reviewed: {exc['review_decision']}")
            else:
                st.markdown("**Review Decision:**")
                rc1, rc2, rc3 = st.columns(3)
                notes = st.text_area("Review Notes", key=f"notes_{exc['id']}", height=60)
                create_rule = st.checkbox("Create mapping rule from this decision", key=f"rule_{exc['id']}")

                with rc1:
                    if st.button("Accept", key=f"accept_{exc['id']}", type="primary"):
                        result = api_post(f"/review/{exc['id']}", {
                            "decision": "accepted",
                            "notes": notes,
                            "create_rule": create_rule,
                            "actor": "reviewer",
                        })
                        if result:
                            st.success("Accepted!")
                            st.rerun()

                with rc2:
                    if st.button("Mark Variance", key=f"variance_{exc['id']}"):
                        result = api_post(f"/review/{exc['id']}", {
                            "decision": "marked_variance",
                            "notes": notes,
                            "create_rule": create_rule,
                            "actor": "reviewer",
                        })
                        if result:
                            st.success("Marked as variance!")
                            st.rerun()

                with rc3:
                    if st.button("Reject", key=f"reject_{exc['id']}"):
                        result = api_post(f"/review/{exc['id']}", {
                            "decision": "rejected",
                            "notes": notes,
                            "create_rule": False,
                            "actor": "reviewer",
                        })
                        if result:
                            st.warning("Rejected.")
                            st.rerun()


# ─────────────────────────────────────────────
# Page 4: Results Explorer
# ─────────────────────────────────────────────
def page_results_explorer():
    st.title("Results Explorer")

    run_id = st.session_state.selected_run_id
    runs_data = api_get("/reconciliation/runs", {"limit": 50})
    if not runs_data:
        st.info("No runs found.")
        return

    options = {f"{r['id'][:8]}... | {r['status']} | {r.get('run_started_at', '')[:16]}": r["id"]
               for r in runs_data}

    current_label = next((k for k, v in options.items() if v == run_id), list(options.keys())[0])
    selected = st.selectbox("Select Run", list(options.keys()), index=list(options.keys()).index(current_label))
    run_id = options[selected]
    st.session_state.selected_run_id = run_id

    # Filters
    col1, col2, col3 = st.columns(3)
    with col1:
        status_filter = st.selectbox("Filter by Status", [
            "All", "matched", "matched_with_minor_variance",
            "missing_in_pms", "missing_in_ota", "amount_mismatch",
            "cancellation_mismatch", "duplicate_in_pms", "duplicate_in_ota",
            "pending_review", "modification_mismatch",
        ])
    with col2:
        limit = st.selectbox("Show", [50, 100, 200, 500], index=1)
    with col3:
        search_guest = st.text_input("Search Guest Name", "")

    params = {"limit": limit}
    if status_filter != "All":
        params["status"] = status_filter

    data = api_get(f"/reconciliation/runs/{run_id}/results", params)
    if not data:
        st.info("No results found.")
        return

    results = data.get("results", [])
    total = data.get("total", 0)

    st.write(f"Showing {len(results)} of {total} total results")

    if not results:
        st.info("No results match the filters.")
        return

    # Build flat table
    rows = []
    for r in results:
        ota = r.get("ota_booking") or {}
        pms = r.get("pms_booking") or {}
        guest = ota.get("guest_name_raw") or pms.get("guest_name_raw") or ""

        if search_guest and search_guest.lower() not in guest.lower():
            continue

        rows.append({
            "Status": STATUS_LABELS.get(r["reconciliation_status"], r["reconciliation_status"]),
            "Confidence": f"{r.get('confidence_score', 0):.0f}%",
            "OTA Ref": ota.get("external_reservation_id", "—"),
            "PMS Ref": pms.get("channel_reference_id", pms.get("pms_reservation_id", "—")),
            "Guest (OTA)": ota.get("guest_name_raw", "—"),
            "Guest (PMS)": pms.get("guest_name_raw", "—"),
            "Platform": ota.get("source_platform", "—"),
            "Check-in": ota.get("check_in_date", pms.get("check_in_date", "—")),
            "OTA Amount": ota.get("gross_amount", "—"),
            "PMS Amount": pms.get("gross_amount", "—"),
            "Rule": r.get("matched_rule", "—"),
            "Review": r.get("review_decision", "—"),
            "result_id": r["id"],
        })

    if rows:
        df = pd.DataFrame(rows)
        display_df = df.drop(columns=["result_id"])

        # Color code the Status column
        def highlight_status(val):
            status_key = {v: k for k, v in STATUS_LABELS.items()}.get(val, "")
            color = STATUS_COLORS.get(status_key, "")
            if color:
                return f"background-color: {color}20; color: {color}; font-weight: bold;"
            return ""

        styled = display_df.style.applymap(highlight_status, subset=["Status"])
        st.dataframe(styled, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("Export")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Export CSV"):
            try:
                r = requests.get(f"{st.session_state.api_base}/reconciliation/runs/{run_id}/export",
                                 params={"format": "csv"}, timeout=30)
                st.download_button("Download CSV", r.content, f"results_{run_id[:8]}.csv", "text/csv")
            except Exception as e:
                st.error(f"Export failed: {e}")
    with c2:
        if st.button("Export Excel"):
            try:
                r = requests.get(f"{st.session_state.api_base}/reconciliation/runs/{run_id}/export",
                                 params={"format": "xlsx"}, timeout=30)
                st.download_button("Download Excel", r.content, f"results_{run_id[:8]}.xlsx",
                                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            except Exception as e:
                st.error(f"Export failed: {e}")


# ─────────────────────────────────────────────
# Page 5: Mapping Rules
# ─────────────────────────────────────────────
def page_mapping_rules():
    st.title("Mapping Rules")

    # Filters
    col1, col2 = st.columns(2)
    with col1:
        rule_type_filter = st.selectbox("Filter by Type", ["All", "room_type", "status", "guest_name",
                                                            "column_mapping", "amount_tolerance"])
    with col2:
        platform_filter = st.selectbox("Filter by Platform", ["All", "booking_com", "expedia", "pms"])

    params = {}
    if rule_type_filter != "All":
        params["rule_type"] = rule_type_filter
    if platform_filter != "All":
        params["source_platform"] = platform_filter

    rules_data = api_get("/mapping-rules", params)
    if rules_data is None:
        return

    st.write(f"**{len(rules_data)} rule(s) found**")

    if rules_data:
        df_rules = pd.DataFrame([{
            "ID": r["id"][:8] + "...",
            "Type": r["rule_type"],
            "Platform": r.get("source_platform", "All"),
            "Source Value": r["source_value"],
            "Target Value": r["target_value"],
            "Confidence": f"{r.get('confidence', 1.0):.0%}",
            "Created From": r.get("created_from", "—"),
            "Created At": r.get("created_at", "")[:10],
            "_id": r["id"],
        } for r in rules_data])

        display_df = df_rules.drop(columns=["_id"])
        st.dataframe(display_df, use_container_width=True, hide_index=True)

        # Delete rule
        st.markdown("---")
        st.subheader("Delete a Rule")
        rule_options = {f"{r['rule_type']} | {r['source_value']} -> {r['target_value']}": r["id"]
                        for r in rules_data}
        selected_rule = st.selectbox("Select rule to delete", list(rule_options.keys()))
        if st.button("Delete Selected Rule", type="secondary"):
            rule_id = rule_options[selected_rule]
            result = api_delete(f"/mapping-rules/{rule_id}")
            if result:
                st.success("Rule deleted successfully.")
                st.rerun()

    st.markdown("---")
    st.subheader("Add New Mapping Rule")
    with st.form("add_rule_form"):
        c1, c2 = st.columns(2)
        with c1:
            new_type = st.selectbox("Rule Type", ["room_type", "status", "guest_name", "column_mapping"])
            new_platform = st.selectbox("Platform (optional)", ["", "booking_com", "expedia", "pms"])
            new_source = st.text_input("Source Value", placeholder="e.g. dlx dbl")
        with c2:
            new_target = st.text_input("Target Value", placeholder="e.g. deluxe_double")
            new_confidence = st.slider("Confidence", 0.0, 1.0, 1.0, 0.05)
            new_hotel = st.text_input("Hotel ID (optional)", placeholder="e.g. HOTEL001")

        submitted = st.form_submit_button("Add Rule")
        if submitted:
            if not new_source or not new_target:
                st.error("Source Value and Target Value are required.")
            else:
                result = api_post("/mapping-rules", {
                    "rule_type": new_type,
                    "source_platform": new_platform or None,
                    "source_value": new_source,
                    "target_value": new_target,
                    "confidence": new_confidence,
                    "hotel_id": new_hotel or None,
                    "created_from": "user_feedback",
                })
                if result:
                    st.success(f"Rule added successfully! ID: {result.get('id', '')[:8]}...")
                    st.rerun()


# ─────────────────────────────────────────────
# Page 6: Audit Log
# ─────────────────────────────────────────────
def page_audit_log():
    st.title("Audit Log")

    # Filters
    col1, col2, col3 = st.columns(3)
    with col1:
        run_filter = st.text_input("Filter by Run ID (first 8 chars)", "")
    with col2:
        actor_filter = st.text_input("Filter by Actor", "")
    with col3:
        action_filter = st.text_input("Filter by Action", "")

    limit = st.selectbox("Show entries", [50, 100, 200], index=0)

    params = {"limit": limit}
    if run_filter:
        params["run_id"] = run_filter
    if actor_filter:
        params["actor"] = actor_filter
    if action_filter:
        params["action"] = action_filter

    logs = api_get("/audit-logs", params)
    if logs is None:
        return

    st.write(f"**{len(logs)} log entries**")

    if not logs:
        st.info("No audit log entries found.")
        return

    rows = []
    for log in logs:
        rows.append({
            "Timestamp": log.get("created_at", "")[:19].replace("T", " "),
            "Action": log.get("action", "—"),
            "Actor": log.get("actor", "—"),
            "Run ID": (log.get("reconciliation_run_id") or "")[:8] + "..." if log.get("reconciliation_run_id") else "—",
            "Result ID": (log.get("result_id") or "")[:8] + "..." if log.get("result_id") else "—",
        })

    df_logs = pd.DataFrame(rows)
    st.dataframe(df_logs, use_container_width=True, hide_index=True)

    # Detail view
    if logs:
        st.markdown("---")
        st.subheader("Log Entry Details")
        log_idx = st.selectbox("Select entry to view details", range(len(logs)),
                               format_func=lambda i: f"{logs[i].get('created_at', '')[:16]} - {logs[i].get('action', '')}")
        log_entry = logs[log_idx]
        col_b, col_a = st.columns(2)
        with col_b:
            st.write("**Before State:**")
            st.json(log_entry.get("before_state_json") or {})
        with col_a:
            st.write("**After State:**")
            st.json(log_entry.get("after_state_json") or {})


# ─────────────────────────────────────────────
# Main App
# ─────────────────────────────────────────────
def main():
    render_sidebar()

    page = st.session_state.page

    if page == "Upload & Run":
        page_upload_run()
    elif page == "Dashboard":
        page_dashboard()
    elif page == "Exception Review":
        page_exception_review()
    elif page == "Results Explorer":
        page_results_explorer()
    elif page == "Mapping Rules":
        page_mapping_rules()
    elif page == "Audit Log":
        page_audit_log()


if __name__ == "__main__":
    main()
