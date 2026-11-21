from __future__ import annotations

import html
import streamlit as st

from core.models import NuggetStatus, SharingScope


def inject_custom_styles() -> None:
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 2rem;
            padding-bottom: 3rem;
            max-width: 1120px;
        }
        .pka-header {
            padding: 1.15rem 1.4rem;
            border-radius: 12px;
            background: linear-gradient(135deg, #f8fafc 0%, #eef4ff 100%);
            border: 1px solid #dbe4f0;
            margin-bottom: 1.25rem;
        }
        .pka-header h1 {
            margin: 0 0 0.25rem 0;
            font-size: 1.65rem;
            font-weight: 700;
            color: #0f172a;
            letter-spacing: -0.02em;
        }
        .pka-header p {
            margin: 0;
            color: #475569;
            font-size: 0.94rem;
        }
        .pka-badge {
            display: inline-block;
            padding: 0.18rem 0.6rem;
            border-radius: 999px;
            font-size: 0.74rem;
            font-weight: 600;
            letter-spacing: 0.02em;
            border: 1px solid transparent;
            margin-right: 0.35rem;
        }
        .badge-pending { background: #fef3c7; color: #92400e; border-color: #fde68a; }
        .badge-review-risk { background: #ffedd5; color: #9a3412; border-color: #fdba74; }
        .badge-private { background: #e0f2fe; color: #075985; border-color: #bae6fd; }
        .badge-shared { background: #dcfce7; color: #166534; border-color: #bbf7d0; }
        .badge-rejected { background: #f1f5f9; color: #475569; border-color: #cbd5e1; }
        .badge-scope { background: #f3e8ff; color: #6b21a8; border-color: #e9d5ff; }
        .pka-tag {
            display: inline-block;
            padding: 0.14rem 0.5rem;
            border-radius: 6px;
            background: #f1f5f9;
            color: #334155;
            border: 1px solid #e2e8f0;
            font-size: 0.76rem;
            margin-right: 0.3rem;
            margin-bottom: 0.25rem;
        }
        .pka-provenance-strip {
            display: flex;
            flex-wrap: wrap;
            gap: 0.4rem;
            margin: 0.45rem 0 0.7rem 0;
            font-size: 0.76rem;
        }
        .prov-step-done {
            background: #ecfdf5;
            color: #065f46;
            border: 1px solid #a7f3d0;
            padding: 0.15rem 0.5rem;
            border-radius: 6px;
            font-weight: 500;
        }
        .prov-step-idle {
            background: #f8fafc;
            color: #64748b;
            border: 1px dashed #cbd5e1;
            padding: 0.15rem 0.5rem;
            border-radius: 6px;
        }
        .pka-metric-card {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 10px;
            padding: 0.9rem 1rem;
        }
        .pka-metric-label {
            font-size: 0.78rem;
            color: #64748b;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.03em;
        }
        .pka-metric-value {
            font-size: 1.6rem;
            font-weight: 700;
            color: #0f172a;
            margin-top: 0.15rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def status_badge_html(status: NuggetStatus) -> str:
    mapping = {
        NuggetStatus.PENDING_REVIEW: ("Awaiting Review", "badge-pending"),
        NuggetStatus.NEEDS_HUMAN_REVIEW: ("Risk / Careful Review Required", "badge-review-risk"),
        NuggetStatus.APPROVED_PRIVATE: ("Approved · Private", "badge-private"),
        NuggetStatus.APPROVED_SHARED: ("Approved · Shared", "badge-shared"),
        NuggetStatus.REJECTED: ("Rejected · Kept Private", "badge-rejected"),
    }
    label, cls = mapping[status]
    return f'<span class="pka-badge {cls}">{html.escape(label)}</span>'


def scope_badge_html(scope: SharingScope, prefix: str = "Enforced") -> str:
    cls = "badge-shared" if scope.is_shared else "badge-private"
    return f'<span class="pka-badge {cls}">{html.escape(prefix)}: {html.escape(scope.value)}</span>'


def tags_html(tags: list[str]) -> str:
    if not tags:
        return '<span class="pka-tag">untagged</span>'
    return "".join(f'<span class="pka-tag">#{html.escape(tag)}</span>' for tag in tags)
