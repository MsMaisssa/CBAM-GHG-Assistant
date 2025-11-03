import streamlit as st
import json
import time
import re
import requests
from snowflake.core import Root
from snowflake.snowpark.context import get_active_session
from snowflake.cortex import complete  # ✅ updated import

# Snowflake session setup
session = get_active_session()
root = Root(session)
database_name = session.get_current_database()
schema_name = session.get_current_schema()
service_name = 'document_search_service'

# Configuration
model_name = "claude-haiku-4-5"
num_results = 3
history_length = 5
DEFAULT_CARBON_PRICE = 80.0
MIN_REQUEST_INTERVAL = 2.0
RETRY_DELAY = 5

DEFAULT_EMISSIONS = {
    "steel": 2.3,
    "aluminum": 8.6,
    "cement": 0.9,
    "fertilizer": 1.5,
    "electricity": 0.4
}

def fetch_live_carbon_price():
    """Fetch EU carbon price using regex from Trading Economics HTML."""
    try:
        url = "https://tradingeconomics.com/commodity/carbon"
        response = requests.get(url, timeout=5)
        match = re.search(r'<td[^>]*>EU Carbon Permits<\/td>\s*<td[^>]*>(\d+\.\d+)', response.text)
        if match:
            return float(match.group(1))
    except Exception as e:
        st.warning(f"⚠️ Could not fetch live carbon price: {e}")
    return DEFAULT_CARBON_PRICE

def init_messages():
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "last_request_time" not in st.session_state:
        st.session_state.last_request_time = 0
    if "carbon_price" not in st.session_state:
        st.session_state.carbon_price = fetch_live_carbon_price()

def init_config_options():
    st.session_state.num_chat_messages = history_length
    col1, col2 = st.columns([3, 1])
    with col1:
        if st.button("Clear conversation"):
            st.session_state.messages = []
            st.rerun()
    with col2:
        new_price = st.number_input("EU ETS €/t", value=st.session_state.carbon_price, min_value=0.0, max_value=200.0, step=0.5)
        st.session_state.carbon_price = new_price

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

def get_chat_history():
    start_index = max(0, len(st.session_state.messages) - st.session_state.num_chat_messages)
    return st.session_state.messages[start_index : len(st.session_state.messages) - 1]

def extract_cbam_request(question):
    match = re.search(r"(\d+)\s+tons?\s+of\s+(\w+)", question, re.IGNORECASE)
    emissions_match = re.search(r"(\d+(\.\d+)?)\s*tCO2e", question, re.IGNORECASE)
    origin_price_match = re.search(r"(?:origin|paid).*?€?(\d+(\.\d+)?)", question, re.IGNORECASE)

    if match:
        quantity = int(match.group(1))
        product = match.group(2).lower()
    else:
        quantity = None
        product = None

    emissions = float(emissions_match.group(1)) if emissions_match else None
    origin_price = float(origin_price_match.group(1)) if origin_price_match else 0.0
    return product, quantity, emissions, origin_price

def calculate_cbam_cost(embedded_emissions, origin_carbon_price=0, eu_carbon_price=None):
    if eu_carbon_price is None:
        eu_carbon_price = st.session_state.carbon_price
    cbam_cost = embedded_emissions * (eu_carbon_price - origin_carbon_price)
    return max(0, cbam_cost)

def cortex_search(my_question):
    search_service = (root
        .databases[database_name]
        .schemas[schema_name]
        .cortex_search_services[service_name]
    )
    resp = search_service.search(
        query=my_question,
        columns=["text", "file_name"],
        limit=num_results
    )
    results = json.loads(resp.to_json())["results"]
    prompt_context = "\n\n".join([r["text"] for r in results]).replace("'", "")
    file_name = results[0]['file_name'] if results else "No source"
    return prompt_context[:8000], file_name

def format_chat_history(chat_history):
    return "\n".join([f"{m['role']}: {m['content']}" for m in chat_history[-3:]])

def create_prompt(user_question):
    chat_history = get_chat_history()
    history_str = format_chat_history(chat_history)
    prompt_context, file_name = cortex_search(user_question)

    prompt = f"""You are a CBAM (Carbon Border Adjustment Mechanism) specialist. Provide direct, concise answers using the provided documentation.

<context>
{prompt_context}
</context>

<chat_history>
{history_str}
</chat_history>

<question>
{user_question}
</question>

<instructions>
1. Answer directly from the provided documentation, including the indexed carbon price file.
2. Cite specific values, formulas, and guidance from the documents.
3. For CBAM calculations:
   - Use default emission values from context if actual emissions not provided
   - Formula: CBAM Cost = (Embedded Emissions tonnes CO2e) × (EU ETS price - Carbon Price Paid in Origin)
4. Keep responses under 150 words unless calculations require detail
5. Structure: Direct answer → Key requirements → Limitations (if any)
6. If info missing: State what's needed clearly
</instructions>

Response:"""
    return prompt, file_name

def complete_with_retry(model, prompt, retries=2):
    now = time.time()
    if now - st.session_state.last_request_time < MIN_REQUEST_INTERVAL:
        time.sleep(MIN_REQUEST_INTERVAL - (now - st.session_state.last_request_time))

    for attempt in range(retries):
        try:
            response = complete(model, prompt)  # ✅ updated call
            st.session_state.last_request_time = time.time()
            return response
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                st.error(f"❌ Request failed: {str(e)}")
                return None

def main():
    st.title("🌍 CBAM Calculator & Documentation Assistant")
    init_messages()
    init_config_options()
    icons = {"assistant": "❄️", "user": "👤"}

    if question := st.chat_input("Ask about CBAM calculations, emissions, or requirements..."):
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user", avatar=icons["user"]):
            st.markdown(question)

        product, quantity, emissions, origin_price = extract_cbam_request(question)
        if product and quantity:
            if emissions is None:
                emissions = DEFAULT_EMISSIONS.get(product)
            if emissions is not None:
                total_emissions = emissions * quantity
                cbam_cost = calculate_cbam_cost(total_emissions, origin_price)
                response_text = f"💶 Estimated CBAM cost: €{cbam_cost:.2f} for {quantity} tons of {product} (Emissions: {emissions} tCO₂e/ton, Origin price: €{origin_price}/t)"
                st.session_state.messages.append({"role": "assistant", "content": response_text})
                with st.chat_message("assistant", avatar=icons["assistant"]):
                    st.markdown(response_text)
                return

        with st.chat_message("assistant", avatar=icons["assistant"]):
            with st.spinner("Analyzing documentation..."):
                prompt, file_name = create_prompt(question)
                response = complete_with_retry(model_name, prompt)
                if response:
                    st.markdown(response)
                    st.caption(f"📄 Source: {file_name}")
                    st.session_state.messages.append({"role": "assistant", "content": response})

if __name__ == "__main__":
    main()
