# CLI Regression Report

Run timestamp: 2026-04-13T14:42:48+08:00

## 1. Executive Summary

The new `run_code.py` terminal runner is usable for real regression conversations and does exercise the shared `ChatSessionService.process_turn()` path. It successfully handled file-path upload, session persistence across turns, tool execution, terminal artifact summaries, debug blocks, and JSONL trace capture.

The multi-pollutant workflow is not fully fixed. The highest-priority failure still reproduces: replying `全部` to the pollutant clarification repeats the same clarification instead of executing multi-pollutant dispersion. Generic dispersion requests also hit a meteorology confirmation before pollutant clarification, which makes the intended clarification flow harder to reach.

The strongest pass is scenario inheritance: after an explicit NOx dispersion with wind direction/speed/stability, `CO2的呢？` inherited the same scenario parameters and changed only the pollutant. Hotspot binding also passed when both NOx and CO2 dispersion results were actually created with explicit meteorology.

## 2. Environment / Commands Used

Dataset existence check:

```bash
ls -l test_data/1km_hd_irregular_changning_02.zip
```

Initial non-escalated runner attempt failed with LLM connection errors, then the same CLI path was rerun with network access:

```bash
python run_code.py --script tests/cli_flows/regression_scenario_1_2.yaml --debug --json-log docs/audits/cli_regression_scenario_1_2.jsonl --user-id cli-regression-s12
python run_code.py --script tests/cli_flows/regression_scenario_1_2.yaml --debug --json-log docs/audits/cli_regression_scenario_1_2.jsonl --user-id cli-regression-s12-net
python run_code.py --script tests/cli_flows/regression_scenario_1_2_continue_all.txt --debug --json-log docs/audits/cli_regression_scenario_1_2_continue_all.jsonl --user-id cli-regression-s12-net --session-id d504b211
python run_code.py --script tests/cli_flows/regression_scenario_3.yaml --debug --json-log docs/audits/cli_regression_scenario_3.jsonl --user-id cli-regression-s3
python run_code.py --script tests/cli_flows/regression_scenario_4.yaml --debug --json-log docs/audits/cli_regression_scenario_4.jsonl --user-id cli-regression-s4
python run_code.py --script tests/cli_flows/regression_scenario_4_with_start.yaml --debug --json-log docs/audits/cli_regression_scenario_4_with_start.jsonl --user-id cli-regression-s4-start
python run_code.py --script tests/cli_flows/regression_scenario_4_explicit_meteo.yaml --debug --json-log docs/audits/cli_regression_scenario_4_explicit_meteo.jsonl --user-id cli-regression-s4-explicit
python run_code.py --script tests/cli_flows/regression_scenario_5.yaml --debug --json-log docs/audits/cli_regression_scenario_5.jsonl --user-id cli-regression-s5
python run_code.py --script tests/cli_flows/regression_scenario_5_continue.txt --debug --json-log docs/audits/cli_regression_scenario_5_continue.jsonl --user-id cli-regression-s5 --session-id c0926873
```

## 3. Dataset Used

Exact requested path:

`/home/kirito/Agent1/emission_agent/test_data/1km_hd_irregular_changning_02.zip`

The file exists and was used. File grounding selected the shapefile inside the zip as the primary macro-emission dataset, with 125 road features and EPSG:4326 spatial metadata.

## 4. Scenario Results

### Scenario 1: Basic Emission -> Generic Dispersion Clarification

Status: **failed expectation**

Observed:
- Upload + emission worked.
- `calculate_macro_emission` ran successfully.
- Emission result contained CO2 and NOx.
- Generic request `请继续做大气扩散分析。` did not ask the expected pollutant clarification. It asked for meteorology confirmation first.
- No `calculate_dispersion` call ran on that turn.

Expected:
- Detect previous pollutants and ask which pollutant/all before defaulting.

Finding:
- The system did not silently default to NOx, which is good.
- It also did not surface the pollutant clarification at the expected point.

### Scenario 2: Clarification Answer = `全部`

Status: **failed**

Observed:
- After the generic dispersion turn, `全部` produced the pollutant clarification text:
  `上一轮排放结果包含：CO2、NOx。当前可直接做物理扩散分析的污染物有：CO2、NOx。您要看全部，还是先看某一个？`
- Continuing the same session with another `全部` repeated the same clarification.
- No `calculate_dispersion` tool call ran.
- No map/chart/table artifact was produced.

Finding:
- The `全部` loop is still reproducible in CLI. The pending clarification is not consumed as a valid all-pollutants selection.

### Scenario 3: Follow-Up Pollutant Switch Preserves Scenario

Status: **passed**

Observed:
- Emission with CO2 and NOx succeeded.
- NOx dispersion ran with custom scenario:
  - pollutant: NOx
  - wind_direction: 270
  - wind_speed: 2.5
  - stability_class: N1
- Follow-up `CO2的呢？` ran `calculate_dispersion` with:
  - pollutant: CO2
  - wind_direction: 270
  - wind_speed: 2.5
  - stability_class: N1
  - mixing_height: 800
  - roughness_height: 0.5
  - grid_resolution: 50
- CO2 map artifact was produced.

Finding:
- The pollutant switch inherited the scenario correctly in this run. The only observed parameter difference was explicit materialization of defaults/derived values in the follow-up tool arguments.

### Scenario 4: Hotspot Follow-Up Binds To Correct Pollutant

Status: **passed with caveat**

Initial default-meteorology script:
- `请做 NOx 扩散分析。` and `请做 CO2 扩散分析。` both stopped at meteorology confirmation and did not create prior dispersion outputs.
- `CO2的热点呢？` then ran CO2 dispersion and hotspot analysis in the same turn.
- This showed CO2 binding, but did not fully test stale NOx-vs-CO2 context because NOx dispersion never executed.

Explicit-meteorology script:
- NOx dispersion ran first.
- CO2 dispersion ran second with the same wind/stability scenario.
- `CO2的热点呢？` ran `analyze_hotspots` with `pollutant: CO2`.
- The hotspot artifact reported pollutant CO2.

Finding:
- With both dispersion contexts present, hotspot binding correctly selected CO2 rather than stale NOx.
- The default meteorology gate remains suspicious because it can prevent the intended prior-dispersion setup.

### Scenario 5: Unsupported / Skipped Pollutant Handling

Status: **partially failed**

Observed:
- Emission request for CO2, NOx, SO2 succeeded and reported SO2 emission.
- After confirmation, the system clearly stated:
  - previous result contains CO2, NOx, SO2
  - eligible physical dispersion pollutants are CO2 and NOx
  - SO2 is not auto-analyzed and is not silently dropped
- Replying `全部` repeated the clarification, same loop as Scenario 2.
- A fully explicit request `对所有已计算污染物逐个扩散，包括 CO2、NOx、SO2。` executed two `calculate_dispersion` calls with requested tool arguments `CO2` and `NOx`, and explained that SO2 is unsupported.
- However, both returned artifact summaries were CO2 contour maps. The second tool call had arguments `pollutant: NOx`, but the result summary and artifact were CO2.

Finding:
- Skipped SO2 is explained clearly.
- The all-pollutant execution path has a serious result/payload mismatch: user-visible text claims CO2 and NOx, but artifacts show CO2 twice.

## 5. Passed Behaviors

- `run_code.py` can run real scripted conversations through the shared session service.
- File-path upload worked with the exact requested zip.
- Emission calculation produced stable CO2/NOx outputs and table/download artifacts.
- JSONL traces include user input, final text, tool calls, trace stage, artifact summaries, and raw frontend payloads.
- Explicit pollutant follow-up `CO2的呢？` inherited NOx scenario parameters.
- CO2 hotspot follow-up bound to CO2 when a CO2 dispersion result existed.
- Unsupported SO2 was surfaced as skipped instead of silently dropped.

## 6. Failed Behaviors

- Generic dispersion after multi-pollutant emission asks for meteorology before pollutant selection.
- `全部` does not consume the pending pollutant clarification and repeats the clarification.
- `开始` after default meteorology can transition into pollutant clarification instead of executing the originally requested pollutant.
- Explicit all-pollutant dispersion with CO2/NOx/SO2 produced duplicate CO2 artifacts even though one tool call requested NOx.

## 7. Suspicious / Partially Verified Behaviors

- Some debug summaries show selected tools as a comma-joined string such as `calculate_dispersion, calculate_dispersion`, which is usable but harder to diff.
- Scenario 4 only fully passed when explicit meteorology avoided the default confirmation gate.
- The text synthesis in Scenario 5 claimed NOx results while artifacts showed CO2 twice; this may be a tool result, context-store, or payload extraction mismatch.

## 8. Recommended Next Fix

Prioritize the clarification state machine for dispersion:

1. Make `全部` / `all` / equivalent Chinese variants resolve the active pollutant-selection clarification and execute all eligible pollutants.
2. Ensure meteorology confirmation and pollutant-selection confirmation do not overwrite each other.
3. Add a regression test for all-pollutant expansion that asserts each `calculate_dispersion` output and frontend artifact keeps its requested pollutant.

