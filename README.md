# CBAM-GHG-Assistant
Documentation-grounded assistant for calculating carbon border adjustment costs under the EU CBAM framework. The assistant retrieves indexed regulatory documents, interprets policy language, and performs emissions-based cost calculations using default or user-specified parameters. Built with Snowflake Cortex, it combines real-time EU ETS carbon pricing fetch with embedded emissions logic to estimate CBAM liability across products and countries.

Disclamer: This project was forked from Snowflake-Labs, and modified for the use case CBAM-GHG Assistant:
site/sfguides/src/getting-started-with-anthropic-on-snowflake-cortex/getting-started-with-anthropic-on-snowflake-cortex.md


PROJECT STRUCTURE
├── README.md
├── CBAM-GHG-Chatbot.ipynb             # Notebooks file for CBAM-GHG Assistant (configured for Haiku )
├── streamlit_Chatapp.py               # Streamlit UI file for CBAM-GHG Assistant
├── Requirements.txt                   # Packages required for the environment
├── DBSCHEMA.sql                       # Anthropic RAG DB schema 
├── Setup ACCOUNTADMIN Role.sql        # Role setup script
├── EnableCrossRegion.sql              # Configuration for cross-region Snowflake access
├── Claude-snowflake-cortex.ipynb      # Notebooks file for any set of documents (add your own; configured for Sonnet 4)
├── streamlit_app.py                   # Streamlit UI file for any set of documents (add your own; configured for Sonnet 4)
├── assets/                            # Screenshots or visuals
    └──StreamlitChatUI.jpg                          # Streamlit interface for CBAM chatbot
    └──NotebookChatUI.jpg                           # Notebooks-based interface for chatbot testi
    └──IndexedDocumentLibrary.jpg        # Indexed CBAM policy documents library

    
# 🧠 CBAM GHG Assistant 

This project showcases a Retrieval-Augmented Generation (RAG) assistant built with Snowflake Cortex and Streamlit to support interpretation of the EU Carbon Border Adjustment Mechanism (CBAM). It indexes official policy documents and enables natural language queries on emissions rules, terminology, and compliance logic.

---

🚀 Features

- Retrieve and interpret CBAM policy documents using Cortex Search
- Query emissions guidance and reporting requirements in plain language
- Integrate live EU ETS carbon pricing from external sources
- Estimate CBAM costs using default or user-provided emissions data
- Interactive Streamlit interface for conversational exploration

⚠️ Note: Cost calculation logic is under refinement. Live carbon price retrieval is fully functional and document-based responses are grounded in indexed sources. See test results and use cases documentation.

---

📊 Streamlit UI

[[https://app.snowflake.com/.../#/streamlit-apps/HOL_DB.HOL_SCHEMA.NZC_RN57VD3SQK25](https://app.snowflake.com/pnaxlwn/ccb95517/#/streamlit-apps/ANTHROPIC_RAG.ANTHROPIC_RAG.M8YXJ_YUVLVZK8JS)

NOTE: Streamlit share features are not currently supported when using Streamlit in a Snowflake Native App: Custom components are not supported.Using Azure Private Link and Google Cloud Private Service Connect to access a Streamlit app is not supported.

---
