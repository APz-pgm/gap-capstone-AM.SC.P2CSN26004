"""app.py - the door a person uses. Calls the same run() as main.py, never client.py.

    python -m streamlit run app.py
"""
import tempfile
from pathlib import Path

import streamlit as st

from pipeline import InputRejected, run          # the same pipeline main.py calls

st.set_page_config(page_title="ForensiQ", page_icon="🔎")
st.title("ForensiQ")
st.caption("LLM-assisted forensic timeline analysis. It highlights event sequences for you to "
           "investigate; it does not prove anything and is not a legal conclusion.")

uploaded = st.file_uploader("Forensic timeline (.csv with timestamp, event, user, source, details)",
                            type=["csv"])

if uploaded is not None and st.button("Analyse timeline"):
    suffix = Path(uploaded.name).suffix or ".csv"          # the input check expects .csv
    with tempfile.NamedTemporaryFile("wb", suffix=suffix, delete=False) as tmp:
        tmp.write(uploaded.getvalue())
    try:
        with st.spinner("Analysing..."):
            result = run(tmp.name)
    except InputRejected as exc:                           # rejected before any model call
        st.warning("Not processed: the file was rejected before any analysis.")
        st.text(str(exc))                                  # plain text, not markdown
        st.stop()
    except Exception as exc:                               # never show a half answer
        st.error(f"No result (error: {type(exc).__name__}). Nothing below is an answer.")
        st.stop()
    finally:
        Path(tmp.name).unlink(missing_ok=True)

    for warning in result.warnings:                        # computed by Python, not the model
        st.warning(warning)

    if result.status != "ok":                              # invalid_output, refused or error
        st.error(f"No result ({result.status}). {result.message}")
        st.stop()

    out = result.output                                    # validated by run()
    # Model text is shown with st.text / st.json only, never as markdown (no links or images).
    st.subheader("Assessment")
    st.text(f"Overall: {out.overall_assessment.replace('_', ' ')}")
    st.text(f"Risk level: {out.risk_level}")
    st.text(f"Events analysed: {len(result.events)}")

    st.subheader("Explanation")
    st.text(out.explanation)
    st.subheader("Forensic relevance")
    st.text(out.forensic_relevance)

    if out.significant_events:
        st.subheader("Significant events")
        for e in out.significant_events:
            st.text(f"{e.timestamp}  {e.description}")

    if out.investigator_questions:
        st.subheader("Questions for the investigator")
        for question in out.investigator_questions:
            st.text(f"- {question}")

    with st.expander("Full validated output (JSON)"):
        st.json(result.report())
    with st.expander("Sorted timeline (UTC)"):
        for e in result.events:
            st.text(f"{e.iso}  {e.event} | {e.user} | {e.source} | {e.details}")