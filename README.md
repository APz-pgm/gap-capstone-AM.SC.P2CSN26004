# ForensiQ

LLM-assisted forensic timeline analysis for a junior digital-forensic investigator. Upload a CSV of timestamped events (files, USB devices, user activity, browser activity). ForensiQ checks and sorts it with plain Python, then asks a language model to point out event sequences that may be related (for example USB connected, confidential file opened, file copied to the USB, USB removed), explain why in plain words, and list questions to check by hand. It highlights what to look at. It proves nothing and gives no legal conclusion.

Roll number AM.SC.P2CSN26004 · 26SN601 Generative AI with Python · capstone

## Setup

Python 3.10 or newer.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
cp .env.example .env               # then put your Gemini API key in .env
```

`.env` needs three lines (the example already has the right URL and model):

```
LLM_API_KEY=<key from https://aistudio.google.com/apikey>
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
LLM_MODEL=gemini-2.5-flash
```

No second program is needed. To work offline with the course stub instead, set `LLM_BASE_URL=local://stub` and `LLM_MODEL=stub:ok`.

## Run

```bash
python main.py samples/inputs/sample_ok.csv     # no UI; the last line is the status
streamlit run app.py                            # the UI
```

`main.py` prints the report, then one last line: `ok`, `invalid_output`, `refused`, `error` (exit code 1 for the last three) or `rejected` (exit code 2, the input was refused before any model call). Messages for the person go to stderr.

## Input format

A `.csv`, up to 200,000 bytes and 1,000 events, UTF-8, with a header row. Required columns: `timestamp` (ISO 8601, e.g. `2026-03-14T14:02:11Z`; no timezone means UTC) and `event`. Optional: `user`, `source`, `details`. See `samples/inputs/`; the data is synthetic and `python samples/make_samples.py` regenerates it.

## Check, test, evaluate

```bash
python check_capstone.py .                  # the course check script (uses only the stub)
python -m unittest discover -s tests -v     # offline tests
python eval_run.py                          # the EVAL.md rows against your real model
```

## Files

| File | What it is |
|---|---|
| `main.py`, `app.py` | The two doors: command line and Streamlit. Both call `pipeline.run` |
| `pipeline.py` | The one pipeline: load, guard, model call with retry, validate, result |
| `timeline.py` | Deterministic half: parse, validate, convert to UTC, sort. No model |
| `schema.py` | Pydantic model of a valid reply |
| `prompts.py` | The system prompt and the evidence block |
| `security.py` | Input guard, output guard, `security_log.jsonl` |
| `observability.py` | `run_log.jsonl`, one line per model call, cost |
| `client.py`, `stub_client.py` | Supplied by the course; not edited |
| `SPEC.md`, `SECURITY.md`, `EVAL.md`, `DECISIONS.md` | The documents marked by a person |

## Known limitations

The short version of EVAL.md's known failures:

- Only ISO 8601 dates are read. Day-first dates like `14/03/2026` are rejected, not guessed (EVAL row 6).
- The prompt-injection guard is a list of phrasings. A reworded instruction gets through to the model (row 10), and a harmless note that contains a trigger phrase is wrongly removed (row 5).
- A model that is persuaded to say "nothing found" about a timeline that does contain a real sequence is not detected. The checks only catch invented evidence and legal claims.
- Timestamps with no timezone are assumed to be UTC.
- The timeline is sent to Google. On the free tier, that data may be used to improve Google's products, so use synthetic or non-sensitive data only.
- Tested on small synthetic timelines (up to 51 events), not on 500-event or real case data.
