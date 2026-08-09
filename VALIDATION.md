# Validating a model on the target infrastructure

One page runbook to decide whether a model and an endpoint are usable, without any
customer document. A synthetic specification ships inside the package.

## Measured on the target infrastructure, Qwen3.6-27B

First run on the endpoint this is meant for, `iagen-proxy-api-r-wdep` behind the corporate
proxy, both roles on `Qwen3.6-27B`:

| | Value | Read |
|---|---|---|
| Verdict | **USABLE** | the chain runs end to end on the target |
| Coverage | 16/16, 100 % | every requirement of the sample covered |
| Volume | 21 tests, 57 steps, **1.6 per scenario** | a third of the target of 5, see below |
| Duration | 13 scenarios in 19 s, 1 s each | faster than the reference model |
| Waste | 0 % of calls, 0 truncated | no retry, nothing cut off |
| Coverage pass | not called | the generator covered everything on its own |
| Reasoning switch | sent on all 14 calls | the endpoint accepts it, so `TGI_DISABLE_THINKING=true` works |
| `/models` | 404 | model ids cannot be checked, they must match exactly |
| TLS | verification disabled | see below, this one is worth fixing |

**The volume is the one thing to watch.** 1.6 tests per scenario against a target of 5 is not a
failure by itself, since the whole point of this pipeline is fewer tests each proving more, and
here coverage held at 100 percent with no gap to close. But fewer tests proving *less* looks
exactly the same from the outside, and only the requirement axis on a real document tells them
apart. `tgi-validate` now says so rather than staying silent.

**TLS verification is disabled.** `TGI_LLM_VERIFY_SSL=false` makes the corporate proxy work and
gives up on checking who answers, which is not a setting to keep for a client's functional
specification. Ask the network team for the proxy certificate and swap it for:

```
TGI_LLM_CA_BUNDLE=C:\chemin\vers\certificat.pem
```


## 1. Install

Any of the three, whichever fits the target infrastructure.

```bash
# from the wheel, nothing else needed
pip install test_generation_interface-0.1.0-py3-none-any.whl

# or as an isolated tool
uv tool install test_generation_interface-0.1.0-py3-none-any.whl

# or from the repository
make sync
```

## 2. Point it at the endpoint

The client always speaks the OpenAI compatible API, so any server exposing
`/v1/chat/completions` works (vLLM, SGLang, a gateway).

```bash
export TGI_LLM_BASE_URL="http://your-inference-server:8000/v1"
export TGI_LLM_API_KEY="whatever-the-server-expects"   # any non empty value if it needs none
```

## 3. Validate

```bash
tgi-validate --model Qwen/Qwen3.6-27B          # installed
make validate ARGS="--model Qwen/Qwen3.6-27B"  # from the repository
```

It runs the real pipeline (extraction, generation, judging) on the bundled sample
and prints a verdict. Exit code is 0 when usable, 1 otherwise, so it can gate a
deployment.

Expected shape of a healthy run:

```
Reasoning switch: never sent (7 calls), TGI_DISABLE_THINKING is off

Sample run : 1 scénario(s) in 101 s (101 s per scénario)
Projection : about 0.5 h for a 90 scénario document at 5 scénarios in parallel
Statuses   : done=1
Coverage   : median 91%  min 91%  max 91%
Output     : 22 rules, 60 tests (2.7 tests per rule)
Wasted     : 0% of calls, 0 truncated

Per role:
  extractor     1 calls    0% wasted  median     0 s
  generator     3 calls    0% wasted  median    29 s
  judge         3 calls    0% wasted  median     5 s

VERDICT: USABLE
```

## 4. Read the verdict

| Line | What it tells you |
|---|---|
| `Reasoning switch` | whether `chat_template_kwargs.enable_thinking=false` reached the server, was never sent, or was refused |
| `Projection` | wall clock for a whole specification at the measured rate, the number that decides feasibility |
| `Wasted` | share of calls that produced nothing usable, and how many were cut off by the output budget |
| `Coverage` | rule coverage the judge measured, compared against `TGI_JUDGE_PASS_SCORE` |
| `Per role` | which of extractor, generator or judge is the slow or wasteful one |
| `Logs` / `Traces` | where the run wrote them, always inside `TGI_LOGS`, kept even when the verdict fails |

## 5. Fix the usual failures

**Slow, and `Wasted` shows truncations.** The model is reasoning. That is the single
most common cause and it costs 10x to 17x the output tokens.

```bash
# server side, the robust way
vllm serve Qwen/Qwen3.6-27B --reasoning-parser qwen3 \
  --default-chat-template-kwargs '{"enable_thinking": false}'

# or client side, per request
TGI_DISABLE_THINKING=true tgi-validate --model Qwen/Qwen3.6-27B
```

Then check the first line again: `sent on all N calls` means it reached the server.
`sent on X of N calls, then dropped, the endpoint refused it` means the gateway
strips the field, so turn reasoning off at the server instead.

**Truncations remain.** Raise the output budget or shrink each answer.

```bash
TGI_MAX_OUTPUT_TOKENS=32000 TGI_TESTS_PER_SCENARIO=4 tgi-validate --model ...
```

Note for reasoning models: Qwen documents 32768 output tokens as the floor for
thinking mode, so the 16000 default is not enough if reasoning stays on.

**`Connection error`, the request never reached the service.** This is transport, not
credentials. On a managed workstation the two usual causes are the outbound proxy and
TLS interception:

```powershell
$env:HTTPS_PROXY = "http://proxy.entreprise:8080"
$env:NO_PROXY    = "localhost,127.0.0.1,.entreprise.local"
```

For the certificate, the clean fix is to give the corporate bundle, in `.env`:

```
TGI_LLM_CA_BUNDLE=C:/chemin/vers/ca-entreprise.pem
```

If the bundle is not available, verification can be skipped. It unscénarioks the run and
exposes the traffic, so it is opt in and logged as a warning on every start, and the
verdict prints `TLS: verification DISABLED`:

```
TGI_LLM_VERIFY_SSL=false
```

Quick check outside the application, same machine:

```powershell
curl.exe -v "$env:TGI_LLM_BASE_URL/models" -H "Authorization: Bearer $env:TGI_LLM_API_KEY"
```

**`models seen: not listed by this endpoint`.** The gateway answered but does not
expose `/models`, which is common for a router. The run continues; just make sure
`TGI_MODEL_GENERATOR` and `TGI_MODEL_JUDGE` are exactly the ids the server expects,
since they cannot be checked automatically.

**Judge returns no score.** The model cannot hold the judging contract. Lower
`TGI_JUDGE_BATCH_RULES` (default 10) so each call covers fewer rules, or use a
different model for judging only:

```bash
tgi-validate --generator Qwen/Qwen3.6-27B --judge some-other-model
```

**Coverage below the threshold.** The generator and the judge disagree. Inspect the
generated tests with `--keep`, which preserves the temporary project and its logs.

## 6. Running on Windows

Same commands, through `uv run`. Two prerequisites: `uv`, and `git` on the PATH
because project history is created by calling the `git` executable.

```powershell
git clone <repo> ; cd test-generation-interface
uv sync

# put the configuration in .env, next to pyproject.toml
uv run tgi-validate --model Qwen/Qwen3.6-27B
uv run tgi                     # web application on http://localhost:8080
uv run python -m tgi.stats
```

**Run the commands from the project directory.** `.env` is read from the current
working directory, and so is the default `projects/` data directory. Launching from
elsewhere silently leaves every default in place; `tgi-validate` now reports that as
a problem rather than failing later with a 401.

Nothing else is Windows specific: paths go through `pathlib`, logs land in
`%LOCALAPPDATA%\tgi\logs` (override with `TGI_LOGS`), state writes retry the atomic
rename that Windows refuses while a reader holds the file, and `uvicorn[standard]`
skips `uvloop` by its own platform marker.

**Not verified**: this repository has only been executed on macOS and Linux. Run
`uv run tgi-validate` on the target to confirm the whole chain in one command.

## 7. Go further

```bash
tgi-stats                    # reads every *-otel.log in TGI_LOGS, including validations
tgi-stats --otel <path> --projects <dir>
```

`tgi-stats` reports per role latency and waste. Running it before any pipeline or
validation says so explicitly rather than printing empty tables. Bloc statistics need a
real project, so they stay empty until a document has been processed through `tgi`.

Full behaviour of the pipeline, thresholds and known model traps:
`README.md` and `.agent_docs/pipeline.md`.
