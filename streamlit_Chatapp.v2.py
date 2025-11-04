# app.py
import streamlit as st
import json
import time
import re
import pandas as pd
from datetime import datetime
from snowflake.core import Root
from snowflake.snowpark.context import get_active_session
from snowflake.snowpark.functions import col
from snowflake.cortex import complete

# -------------------------------------------------
# Snowflake session & Cortex Search Service
# -------------------------------------------------
session = get_active_session()
root = Root(session)
database_name = session.get_current_database()
schema_name = session.get_current_schema()
service_name = "document_search_service"

# -------------------------------------------------
# Configuration
# -------------------------------------------------
MODEL_NAME = "claude-haiku-4-5"
NUM_RESULTS = 3
HISTORY_LENGTH = 5

DEFAULT_CARBON_PRICE = 78.54          # Oct 31 2025 market price
MIN_REQUEST_INTERVAL = 2.0
RETRY_DELAY = 5

# Recent EU ETS prices (Oct 2025) – source: tradingeconomics.com/commodity/carbon
RECENT_PRICES = {
    "2025-10-31": 78.54,
    "2025-10-01": 76.30,
    "2025-09-15": 74.80,
    "2025-09-01": 73.20,
}

DEFAULT_EMISSIONS = {
    "steel": 2.3,
    "aluminum": 8.6,
    "cement": 0.9,
    "fertilizer": 1.5,
    "electricity": 0.4,
    "glass": 0.8,
    "ceramics": 0.7,
    "hydrogen": 10.0,
}

# -------------------------------------------------
# Helper: write price file to @Documents stage
# -------------------------------------------------
def write_price_to_stage(carbon_price: float, is_manual: bool = False) -> bool:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    source = "Manual override" if is_manual else "Default market price"

    content = f"""Live EU ETS Carbon Price: €{carbon_price:.2f}/tonne CO₂
Updated: {timestamp}
Source: {source}
This price represents the current European Union Emissions Trading System (EU ETS) allowance price.
Use this for CBAM cost calculations unless overridden by official EU guidance.
CBAM Formula:
CBAM Cost = (Embedded Emissions in tCO₂e) × (EU ETS Price - Carbon Price Paid at Origin)
Note: Prices fluctuate daily. Update regularly for accurate calculations.
"""
    try:
        tmp_path = "/tmp/live_carbon_price.txt"
        with open(tmp_path, "w") as f:
            f.write(content)
        session.file.put(tmp_path, "@Documents", overwrite=True, auto_compress=False)
        return True
    except Exception as e:
        st.error(f"Failed to write price file: {e}")
        return False


# -------------------------------------------------
# OCR + re-indexing (runs only on first load)
# -------------------------------------------------
def process(file_name: str) -> pd.DataFrame:
    """Extract text with OCR from a file in @Documents."""
    query = """
        SELECT TO_VARCHAR(SNOWFLAKE.CORTEX.PARSE_DOCUMENT(?, ?, {'mode': 'OCR'}):content) AS OCR
    """
    try:
        row = session.sql(query, params=["@Documents", file_name]).collect()[0]
        return pd.DataFrame({"TEXT": [row["OCR"]], "FILE_NAME": [file_name]})
    except Exception:
        return pd.DataFrame({"TEXT": [""]}, {"FILE_NAME": [file_name]})


def reindex_documents() -> bool:
    """Re-index every file in @Documents into docs_text_table."""
    try:
        files = session.sql("LIST @Documents").collect()
        names = [f["name"].split("/")[-1] for f in files if f["name"].endswith((".pdf", ".png", ".jpg", ".jpeg"))]
        if not names:
            return False

        dfs = [process(n) for n in names if process(n)["TEXT"].iloc[0]]
        if not dfs:
            return False

        final_df = pd.concat(dfs, ignore_index=True)
        sp_df = session.create_dataframe(final_df).select(col("FILE_NAME"), col("TEXT"))
        sp_df.write.mode("overwrite").save_as_table("docs_text_table")
        return True
    except Exception:
        return False


# -------------------------------------------------
# Session-state initialisation
# -------------------------------------------------
def init_session_state():
    defaults = {
        "messages": [],
        "last_request_time": 0,
        "carbon_price": DEFAULT_CARBON_PRICE,
        "is_manual_price": False,
        "selected_historic_date": None,
        "manual_override_price": None,
        "initialized": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # Run once per deployment
    if not st.session_state.initialized:
        write_price_to_stage(DEFAULT_CARBON_PRICE, is_manual=False)
        reindex_documents()
        st.session_state.initialized = True


# -------------------------------------------------
# UI – price controls + chat history
# -------------------------------------------------
def render_config_ui():
    st.session_state.num_chat_messages = HISTORY_LENGTH

    # ---- Top row -------------------------------------------------
    col_price, col_reset, col_clear = st.columns([3, 1, 1])

    with col_price:
        st.metric("Current EU ETS Price", f"€{DEFAULT_CARBON_PRICE:.2f}/tCO₂e")
        # status caption
        if st.session_state.manual_override_price is not None:
            st.caption(f"Manual price active: €{st.session_state.manual_override_price:.2f}")
        elif st.session_state.selected_historic_date is not None:
            hp = RECENT_PRICES[st.session_state.selected_historic_date]
            st.caption(f"Historic price active ({st.session_state.selected_historic_date}): €{hp:.2f}")
        else:
            st.caption("Using default market price – 2025-10-31")

    with col_reset:
        if st.session_state.manual_override_price is not None or st.session_state.selected_historic_date is not None:
            if st.button("Reset", use_container_width=True):
                st.session_state.carbon_price = DEFAULT_CARBON_PRICE
                st.session_state.manual_override_price = None
                st.session_state.selected_historic_date = None
                write_price_to_stage(DEFAULT_CARBON_PRICE, False)
                st.rerun()

    with col_clear:
        if st.button("Clear Chat", use_container_width=True):
            st.session_state.messages = []
            st.rerun()

    st.markdown("---")
    st.subheader("Update Carbon Price")

    # ---- Historic price buttons ----------------------------------
    st.write("**Historical Prices**")
    cols = st.columns(len(RECENT_PRICES))
    for idx, (date, price) in enumerate(sorted(RECENT_PRICES.items(), reverse=True)):
        with cols[idx]:
            selected = st.session_state.selected_historic_date == date
            if st.button(
                f"{date}\n€{price:.2f}",
                key=f"hist_{date}",
                type="primary" if selected else "secondary",
                use_container_width=True,
            ):
                st.session_state.carbon_price = price
                st.session_state.selected_historic_date = date
                st.session_state.manual_override_price = None
                write_price_to_stage(price, False)
                st.rerun()

    st.divider()

    # ---- Manual price entry --------------------------------------
    st.write("**Manual Price Entry**")
    disabled = st.session_state.selected_historic_date is not None
    default_val = st.session_state.manual_override_price or 0.0

    col_in, col_btn = st.columns([3, 1])
    with col_in:
        new_price = st.number_input(
            "Enter price (€/tCO₂e)",
            min_value=0.0,
            max_value=500.0,
            value=float(default_val),
            step=0.5,
            disabled=disabled,
            key="manual_price_input",
        )
    with col_btn:
        st.write("")  # spacer
        if st.button("Update Price", use_container_width=True, disabled=disabled):
            if new_price > 0:
                st.session_state.carbon_price = new_price
                st.session_state.manual_override_price = new_price
                st.session_state.selected_historic_date = None
                write_price_to_stage(new_price, True)
                st.rerun()
            else:
                st.warning("Price must be > 0")

    st.markdown("---")

    # ---- Default emission factors --------------------------------
    with st.expander("Default Emission Factors"):
        df = pd.DataFrame(
            [{"Product": k.title(), "tCO₂e/tonne": v} for k, v in DEFAULT_EMISSIONS.items()]
        )
        st.dataframe(df, hide_index=True, use_container_width=True)
        st.caption("Used when actual emissions are not supplied")

    # ---- Chat history --------------------------------------------
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"], avatar="user" if msg["role"] == "user" else "assistant"):
            st.markdown(msg["content"])


# -------------------------------------------------
# Chat helpers
# -------------------------------------------------
def get_recent_history():
    start = max(0, len(st.session_state.messages) - HISTORY_LENGTH)
    return st.session_state.messages[start:-1]  # exclude the newest user message


def extract_cbam_request(text: str):
    qty_pat = re.search(r"(\d+(?:,\d{3})*)\s+tons?\s+(?:of\s+)?(\w+)", text, re.IGNORECASE)
    em_pat = re.search(r"(\d+(?:\.\d+)?)\s*tCO2e?(?:/ton)?", text, re.IGNORECASE)
    origin_pat = re.search(r"(?:origin|paid|cost).*?€?(\d+(?:\.\d+)?)", text, re.IGNORECASE)

    quantity = int(qty_pat.group(1).replace(",", "")) if qty_pat else None
    product = qty_pat.group(2).lower() if qty_pat else None
    emissions = float(em_pat.group(1)) if em_pat else None
    origin_price = float(origin_pat.group(1)) if origin_pat else 0.0
    return product, quantity, emissions, origin_price


def calculate_cbam_cost(embedded_emissions: float, origin_price: float = 0.0, eu_price: float | None = None):
    eu_price = eu_price or st.session_state.carbon_price
    return max(0.0, embedded_emissions * (eu_price - origin_price))


def cortex_search(query: str):
    try:
        svc = (
            root.databases[database_name]
            .schemas[schema_name]
            .cortex_search_services[service_name]
        )
        resp = svc.search(query=query, columns=["text", "file_name"], limit=NUM_RESULTS)
        results = json.loads(resp.to_json())["results"]
        context = "\n\n".join(r["text"] for r in results).replace("'", "")
        src = results[0]["file_name"] if results else "No source"
        return context[:8000], src
    except Exception as e:
        st.error(f"Cortex search error: {e}")
        return "", "Error"


def format_history(history):
    return "\n".join(f"{m['role']}: {m['content']}" for m in history[-3:])


def build_prompt(user_question: str):
    history = get_recent_history()
    hist_str = format_history(history)
    ctx, src = cortex_search(user_question)
    price = st.session_state.carbon_price

    prompt = f"""You are a CBAM specialist. Answer concisely using the supplied docs.
<context>
{ctx}
Current EU ETS Carbon Price: €{price:.2f}/tonne CO₂e
</context>
<chat_history>
{hist_str}
</chat_history>
<question>
{user_question}
</question>
<instructions>
1. Cite values/formulas from the docs.
2. For calculations:
   - Default emission factors: {DEFAULT_EMISSIONS}
   - Formula: CBAM Cost = (Embedded Emissions tCO₂e) × (EU ETS €{price:.2f} – Origin price)
3. Keep < 150 words unless calculation needs detail.
4. Structure: Answer → Requirements → Calculation → Limitations
5. If data missing, say what is needed.
</instructions>
Response:"""
    return prompt, src


def llm_complete(model: str, prompt: str, retries: int = 2):
    now = time.time()
    elapsed = now - st.session_state.last_request_time
    if elapsed < MIN_REQUEST_INTERVAL:
        time.sleep(MIN_REQUEST_INTERVAL - elapsed)

    for attempt in range(retries):
        try:
            resp = complete(model, prompt)
            st.session_state.last_request_time = time.time()
            return resp
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                st.error(f"LLM request failed: {e}")
                return None


# -------------------------------------------------
# Main
# -------------------------------------------------
def main():
    st.set_page_config(page_title="CBAM Calculator", layout="centered")
    st.title("CBAM Calculator & Documentation Assistant")
    st.caption("Calculate CBAM costs & query official guidance")

    init_session_state()
    render_config_ui()

    icons = {"user": "user", "assistant": "assistant"}

    if question := st.chat_input("Ask about CBAM, emissions, or calculations…"):
        # ---- store user message -------------------------------------------------
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user", avatar=icons["user"]):
            st.markdown(question)

        # ---- quick CBAM calculation --------------------------------------------
        prod, qty, em, origin = extract_cbam_request(question)
        if prod and qty:
            if em is None:
                em = DEFAULT_EMISSIONS.get(prod)
            if em is not None:
                total_em = em * qty
                cost = calculate_cbam_cost(total_em, origin)
                eu_p = st.session_state.carbon_price

                resp = f"""**CBAM Cost Calculation**
**Product:** {prod.title()} | **Quantity:** {qty:,} tonnes
**Emission factor:** {em} tCO₂e/tonne
**Total emissions:** {total_em:,.2f} tCO₂e
**EU ETS price:** €{eu_p:.2f} | **Origin price:** €{origin:.2f}

**Estimated CBAM cost: €{cost:,.2f}**

*Calculation:* {total_em:,.2f} × (€{eu_p:.2f} – €{origin:.2f}) = €{cost:,.2f}
> *Estimate only – use verified emissions for official filing.*"""
                st.session_state.messages.append({"role": "assistant", "content": resp})
                with st.chat_message("assistant", avatar=icons["assistant"]):
                    st.markdown(resp)
                return

        # ---- documentation / LLM answer ----------------------------------------
        with st.chat_message("assistant", avatar=icons["assistant"]):
            with st.spinner("Searching docs…"):
                prompt, src = build_prompt(question)
                answer = llm_complete(MODEL_NAME, prompt)
                if answer:
                    st.markdown(answer)
                    st.caption(f"Source: {src}")
                    st.session_state.messages.append({"role": "assistant", "content": answer})


if __name__ == "__main__":
    main()