# Decisions

Real choices made while building ForensiQ: what I chose, what I rejected, and why. Dated when I made them.

## 2026-10-18 · Split of work: Python for the evidence, the model for the meaning
**Chose:** Python reads, validates, converts to UTC and sorts the CSV (`timeline.py`); the model only decides whether a sequence looks related and explains it. **Rejected:** letting the model read the raw CSV and sort it. **Why:** ordering and timestamps must be right every time and an LLM could silently drop or reorder an event in evidence. This is the split in section 7 of my brief, and it also means every bad file is rejected before a paid call is made.

## 2026-10-18 · First provider plan: Gemini 2.5 Flash through its OpenAI-compatible endpoint
**Chose:** `LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/`, `LLM_MODEL=gemini-2.5-flash`, so the unchanged course `client.py` works. This is the model named in my brief. **Rejected:** a LiteLLM proxy, and Ollama. **Why:** option 1 of the guide needs nothing extra to start; the proxy is a second program to run for no gain, and a local model is slow on my laptop. **Outcome:** this plan did not survive; see the 2026-10-21 entry below.

## 2026-10-18 · Floor item 6: documents, not tools
**Chose:** the "documents" side: the CSV is untrusted text, guarded on the way in and checked on the way out. **Rejected:** inventing a lookup tool. **Why:** my brief says no external tool calls are needed. A tool added only to pass a check would be an extra attack surface that does not serve the user.

## 2026-10-18 · Only `timestamp` and `event` are required columns
**Chose:** `user`, `source` and `details` are optional and default to empty. **Rejected:** requiring all five. **Why:** the brief said "fields such as", and public forensic exports often lack a user column. Refusing them would shut out real data. The model is told fields may be empty.

## 2026-10-18 · ISO 8601 only, no timezone means UTC, day-first dates rejected
**Chose:** accept ISO 8601; convert everything to UTC; treat a missing offset as UTC; reject `14/03/2026`. **Rejected:** guessing day-first or month-first. **Why:** `03/04/2026` is ambiguous and a wrong guess puts evidence in the wrong order without any sign. A refusal is visible; a wrong order is not. This is a known failure (EVAL row 6). Assuming UTC for naive times is also a guess; I accepted it because refusing every file without an offset would reject most exports, and the README says so.

## 2026-10-18 · Limits: 200,000 bytes and 1,000 events
**Chose:** 200,000 bytes, 1,000 events. **Rejected:** 1 MB, and no event cap. **Why:** the brief expects 5 to 100 KB and 50 to 500 events, so 200 KB is twice the largest expected file. A smaller limit keeps the prompt cheap and short, and the check script's 1 MB file is far over it.

## 2026-10-18 · What the input guard does with an instruction: remove the cell and warn
**Chose:** replace the whole offending cell with a placeholder, log `guardrail_input` and `instruction_ignored`, and show the investigator a warning. **Rejected:** (a) rejecting the whole file with exit 2; (b) asking the model to flag tampering. **Why:** (a) lets anyone who can plant one phrase stop the analysis entirely, and the investigator still wants a result from the rest; (b) puts the reporting of an attack in the hands of the thing being attacked. The warning is computed in Python and sits outside the model's schema. **Accepted cost:** a harmless cell that contains a trigger phrase is also removed (EVAL row 5), and a removed cell takes its genuine content with it.

## 2026-10-18 · Warnings and event ids live outside the model's schema
**Chose:** the model returns exactly the six fields in my brief (`schema.Analysis`); `input_warnings` and `events_analyzed` are added by Python in `Result.report`. **Rejected:** a seventh model field for tampering. **Why:** see above. Events are numbered `E001`... only so that warnings can point at a row; the model cites events by timestamp, as the brief's output asks.

## 2026-10-18 · The output guard rejects; it does not repair
**Chose:** a reply that cites a timestamp not in the input, or states a legal conclusion, is `invalid_output` (and is retried once). **Rejected:** deleting the bad event or sentence and showing the rest. **Why:** a reply with one invented event is evidence the model is unreliable on this input; patching it would present partly trusted output as a finding. This follows the brief: no legal conclusions or attribution. I accepted that regex lists are crude (SECURITY.md).

## 2026-10-18 · Consistency rule in the schema
**Chose:** `no_significant_sequence` must have `risk_level: low` and no events; `potentially_significant` must list events. **Rejected:** only type checks. **Why:** a reply that says "no significant sequence, high risk" is shaped correctly but contradicts itself, and the investigator would not know which half to believe. Extra keys the model adds are ignored rather than rejected, because they cost nothing and rejecting them would waste a call.

## 2026-10-18 · Retry policy: one retry for `error` and `invalid_output`; none for `refused`
**Chose:** two attempts at most. Each attempt writes its own `run_log.jsonl` line. No retry for HTTP 400, 401, 403 or 404, and at most a 5 second wait. **Rejected:** retrying on refusals, and a longer backoff loop. **Why:** a refusal will not change; a bad key will not fix itself; real models do sometimes return broken JSON once and a second try is cheap. A longer loop would burn a free quota in a rate limit.

## 2026-10-18 · Model text is shown with `st.text` and `st.json`, never markdown
**Chose:** `app.py` never renders the model's words as markdown or HTML. **Why:** model text was produced from untrusted cells, and a markdown link or image is a way to carry data out.

## 2026-10-18 · Extra modules instead of one big file
**Chose:** `timeline.py` (the deterministic half), `schema.py`, `prompts.py`, `security.py`, `observability.py`, `pipeline.py` (the one function `run()`), and `main.py` and `app.py` as two thin doors. **Why:** each file has one job I can explain, and the UI and `main.py` share `pipeline.run`, so the check script tests what a person sees.

## 2026-10-21 · Provider changed: Groq with `openai/gpt-oss-120b`
**What happened:** my first real call returned a 404: Google said `gemini-2.5-flash` is no longer available to new users. Its suggested replacement worked, but the 429 error then showed a free limit of 20 requests per day per project for that model, with about 20 hours to wait. The evaluation needs at least 7 model calls, and testing and the UI use more, so that limit was too tight with the deadline close. **Chose:** Groq, through its OpenAI-compatible endpoint (`LLM_BASE_URL=https://api.groq.com/openai/v1`), with `LLM_MODEL=openai/gpt-oss-120b`. The unchanged course `client.py` works with it, so no code changed. **Why this model:** it is the largest chat model my key can list. The task needs the model to link several events, copy exact timestamps and return strict JSON, and a bigger model does that more reliably. **Rejected:** `gemini-flash-latest` (a moving alias, so results could not be reproduced, and its price could not be looked up); `qwen/qwen3.8-27b` (smaller; kept as the backup); the whisper and orpheus models (speech); the prompt-guard and safeguard models (classifiers, not analysis models). **Cost of the choice:** the evidence still leaves my machine, so I must read Groq's data policy before any real case data is used; the samples are synthetic. **Evidence it works:** on the final evaluation the model passed rows 1 to 4 and 9, and the only failures are the three known ones (EVAL.md).

## 2026-10-21 · Cost comes from a price table, and a missing entry silently logged $0
**What happened:** the first evaluation run on Groq reported a cost of $0.00000 per run, because `PRICES` in `observability.py` had no entry for the new model and unknown models are logged as free (that is right for the stub, wrong for a real model). **Chose:** add `"gpt-oss-120b": (0.15, 0.60)` (USD per million input and output tokens), then clear the logs and run the evaluation again so every logged cost is real. The key is the model name without the `openai/` prefix, because the code strips it. **Rejected:** working out the cost by hand from the token counts, because then `run_log.jsonl` and the sample log would still say $0. **Why:** the cost in EVAL.md must match what the log says. The rate is Groq's list price as I found it on 21 October 2026; sources differed slightly on the output price, so I check it against my Groq console.

## 2026-10-21 · The sample log now comes from the real evaluation run
**Chose:** `samples/run_log_sample.jsonl` is the last 20 lines of the `run_log.jsonl` written by the final `python eval_run.py` against `openai/gpt-oss-120b`. **Why:** the guide asks for a sample of the real log. Earlier I had generated it from stub runs, so the repository would pass the check before I had run the real model; that was only a placeholder.
