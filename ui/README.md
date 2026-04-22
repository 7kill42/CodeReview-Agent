# UI Demo

The Streamlit app in this directory is a **minimal demo client**, not the center of the project.

Its purpose is to demonstrate the framework end-to-end:

- submit a GitHub PR URL
- inspect recent review tasks
- read the aggregated report and raw findings

## Run

```bash
cd /root/project/CodeReview-Agent
source .venv/bin/activate
streamlit run ui/app.py
```

The demo assumes the framework API is already running on `API_BASE` (default: `http://127.0.0.1:8000`).
