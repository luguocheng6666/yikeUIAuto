# CODEBUDDY.md

This file provides guidance to CodeBuddy Code when working with code in this repository.

## What this project is

`yikeUIAuto` is a **keyword-driven UI automation framework** (关键字驱动 UI 自动化测试框架). Test cases are NOT written in Python — they are authored in an Excel workbook (`Data/testdata.xlsx`) as rows of keywords, locators, and expected results. Python code reads that workbook, dynamically generates `unittest` test methods, executes the keywords against either a **web browser (Selenium)** or a **Windows desktop app (pywinauto)**, writes pass/fail back into the same Excel file, and produces an HTML report.

It is a legacy (2023) Python 3 project with mixed Chinese/English comments and several typos that are load-bearing (see "Naming gotchas" below).

## Commands

There is no build step and no linter/test framework beyond `unittest`.

### Python environment

A dedicated Python lives **inside the project** at `.python3/` (Python 3.10.11, Windows). Use it
so the environment travels with the repo and nothing is written to the system registry/PATH:

```bash
# Windows (VSCode terminal or Git Bash), from the repo root:
.python3/python.exe -m pip install -r requirements.txt
.python3/python.exe testsuites/TestRunner.py
```

VSCode is configured via `.vscode/settings.json` →
`python.defaultInterpreterPath = ${workspaceFolder}/.python3/python.exe`, so the
`Run`/`Debug` buttons and the integrated terminal pick it up automatically.
If VSCode still resolves another interpreter, run `Python: Select Interpreter` and choose the
one under `.python3`.

On Linux/CI there is no `.python3/` — use the system Python:

```bash
python3 -m pip install -r requirements.txt
python3 testsuites/TestRunner.py
```

Desktop-only packages are marked with `; sys_platform == "win32"` in `requirements.txt`, so they
are skipped on Linux instead of failing the install.

Run the full suite (the real entry point):

```bash
# From the repo root:
python testsuites/TestRunner.py
```

This:
1. Calls `__generateTestCases()` to read `Data/testdata.xlsx` and dynamically create `test_*` methods on the `Keyword` class.
2. Uses `unittest.TestLoader().discover("framework", "keywordsFrameword.py")` to build the suite.
3. Runs it through `tools/HTMLTestRunner_cn_echarts2.py` and writes `reports/result.html`.
4. Calls `framework.upload.backup()` which copies the report and `testdata.xlsx` into `BackUP/<year>/<month>/` (timestamped).

Run with the plain text runner (no HTML report) for quick debugging:

```bash
python framework/keywordsFrameword.py
```

There is **no CLI flag to run a single test case**. To select which cases run, edit `Data/testdata.xlsx`:
- `测试用例` sheet → column `是否需要执行` = `y`/`n` (case enabled).
- `TestDatas` sheet → column `Runmode` = `y`/`n` (data row enabled), and `Cycle` = number of times the case repeats (a `0` is auto-corrected to `1`).

**All filesystem paths are derived at runtime from `setting.BASE_DIR` (the directory containing
`setting.py`), never from the CWD and never hardcoded with a drive letter.** This is what makes the
repo portable to Linux: `os.path.join` picks the right separator, and `BASE_DIR` follows wherever
the repo is checked out. Do not reintroduce `'../tools/'`-style CWD-relative paths or `.ini`-driven
directories — the `[filepath]` section of `config.ini` is deprecated and no longer read.
Verified: running the suite from `C:\` (outside the repo) still resolves every path correctly.

Browser drivers live in `tools/`. `BrowserEngine` builds the path as
`setting.BASE_DIR + tools/ + <name>` and appends `.exe` **only on Windows**
(`_ext = ".exe" if IS_WINDOWS else ""`), so the same code finds `chromedriver` on Linux.

Driver version must match the installed Chrome major version. Current state: Chrome 152.0.7977.76 ↔ `tools/chromedriver.exe` 152.0.7977.75 (the old 116 driver failed with `SessionNotCreatedException: This version of ChromeDriver only supports Chrome version 116`; it is kept as `tools/chromedriver_116.bak.exe`).

## Linux deployment notes

The project is intended to run on Linux in CI. Points to keep in mind:

- `pywinauto` (and `comtypes`/`pywin32`) are Windows-only. `framework/browser_engine.py` imports
  them **conditionally** (`IS_WINDOWS = sys.platform.startswith("win")`, falling back to
  `Application = None`). Never move that import back to module top level — it would make the whole
  framework fail at import time on Linux. Desktop keywords (`start_app`, `get_win`, `mouse_click`,
  `Close_win`) are inherently unavailable off Windows.
- `BrowserEngine.open_browser()` already has a Linux branch: `platform.platform()` containing
  `Linux` → headless Chrome with `--no-sandbox --disable-gpu --disable-dev-shm-usage`.
- Linux needs its own `tools/chromedriver` (no extension) matching the installed Chrome/Chromium,
  plus Chrome/Chromium itself installed on the agent.
- `Data/testdata.xlsx` must be deployed with the code — it *is* the test source. Before running,
  make sure no Office process holds it open (on Windows this shows up as `~$testdata.xlsx` and
  causes `PermissionError` on write-back).
- `Logs/`, `Screenshot/`, `reports/`, `BackUP/` are created on demand and are gitignored.

## Architecture

### Data flow (the "big picture")

```
testsuites/TestRunner.py
   └─ framework/keywordsFrameword.py::__generateTestCases()
        ├─ reads Data/testdata.xlsx  (excelutil.py)
        ├─ dynamically setattr()'s test_* methods onto class Keyword
        └─ each method → Keyword.executeCase(case)
             ├─ getCaseStep()  → rows from the "TestSteps" sheet
             └─ big if/elif dispatch on the step "关键字" (keyword) string
                  └─ calls Action (keywordsDriver/keywordAction.py) methods
                       └─ Action extends BasicPage (framework/basepage.py)
                            └─ Selenium WebDriver  OR  pywinauto app/window
```

- `Action` extends `BasicPage` (all the low-level page operations: `find_element`, `click`, `type`, `select_by_*`, `screenshots`, `assert_*`, window/frame switching).
- `BasicPage` is shared between the two automation engines; it branches on `'selenium' in str(self.driver)` vs `'pywinauto' in str(self.driver)` (e.g. in `take_screenshot` and in the `finally`/`tearDownClass` cleanup logic).

### The Excel workbook (`Data/testdata.xlsx`) — the real test source

Sheet names and columns are declared as constants in `keywordsDriver/excelKey.py` (module-level, imported via `from keywordsDriver.excelKey import *`). Column headers are matched case-insensitively (`get_xls` lowercases header keys).

- **`测试用例`** (`SuitSheet`): the list of test cases — `TCID`, `用例名称`, `用例描述`, `是否需要执行`, `执行时间`, `结果`.
- **`TestDatas`** (`DataSheet`): one row per case's data/assertions — `TCID`, `Runmode`, `CaseId`, `Data_name`, `Summary`, `verifiedcodeXY`, `Type`, `Expression`, `ExpectedResult`, `Result`, `ErrMsg`, `StartTime`, `RunTime`, `Cycle`, plus `selector1/selector2...` and `Input1/Input2...` used by the `selectby*` and `input` keywords.
  - `Type`/`Expression`/`ExpectedResult` are comma-separated to support multiple assertions in a single case (consumed positionally by `assertnum`).
- **`TestSteps`** (`StepSheet`): the actual execution steps — `步骤序号`, `测试步骤描述`, `关键字`, `操作元素定位方式`, `操作元素定位表达式`, `操作值`, `是否需要执行`.

Results are written back into the same workbook: `Result` / `ErrMsg` / `StartTime` / `RunTime` cells get their exact coordinates from the `TestDatas` row (see `NeedXY` handling in `excelutil.get_xls`, which replaces those cell values with `"<row>,<col>"` coordinates). Cell font colors for pass/fail/error come from `keywordsDriver/ColorKey.py`.

### Keyword dispatch

Keyword name strings are constants in `keywordsDriver/keywordKey.py` (all lowercased, e.g. `open_browser`, `open_url`, `start_app`, `get_win`, `click`, `input`, `sleep`, `send_keys`, `screenshots`, `mouse_click`, `CodeSlide`, `selectbyindex/text/value`, `swith_window_handle_by_*`, `swith_frame`, `Exeucejs`, and the `assert*` family). `executeCase()` lowercases each step's `关键字` and matches it in a long `if/elif` chain — **the step value for a keyword is read from the Excel cell, not from a method signature**, so adding a new keyword means (a) add the constant in `keywordKey.py`, (b) add an `elif` branch in `keywordsFrameword.executeCase()`, and (c) implement/forward the method in `Action`/`BasicPage`.

### Element locator syntax

Locators use the `定位方式=>表达式` format (split on `=>`, not `=`), e.g. `id=>su`, `xpath=>//*[@id='u1']`. Supported prefixes (parsed in `BasicPage.find_element` / `get_element_value`): `i`/`id`, `n`/`name`, `cn`/`class_name`, `lt`/`link_text`, `plt`/`partial_link_text`, `tn`/`tag_name`, `x`/`xpath`, `cs`/`css_selector`. Steps carry the locator across two columns: `操作元素定位方式` + `操作元素定位表达式`, which are joined into `method=>expression` in `executeCase()`.

There is also an older XML element-repository mechanism (`Data/element.xml` + `Data/element.py`, activity→element→pathType/pathValue) that appears largely superseded by inline `=>` locators. It has a latent bug: `set_xml()` guards on `len(activity) == 0` but `activity` is the global dict, and it uses the deprecated `getchildren()`.

### Directory map

| Path | Purpose |
|------|---------|
| `testsuites/TestRunner.py` | Entry point: generate cases → discover → run → HTML report → backup |
| `framework/keywordsFrameword.py` | Core engine: reads Excel, generates test methods, dispatches keywords (note the misspelling `Frameword`) |
| `framework/basepage.py` | `BasicPage`: every page action + assertions + screenshots (Selenium & pywinauto) |
| `framework/browser_engine.py` | `BrowserEngine`: opens Chrome/Firefox/IE or a Windows exe via pywinauto |
| `framework/excelutil.py` | `excel_readWrite`: read/write `testdata.xlsx` (openpyxl for write, xlrd for legacy reads) |
| `framework/logger.py` | `Logger` (TimedRotatingFileHandler → `Logs/logs.log`) |
| `framework/send_email.py` | SMTP report-failure email (hardcoded QQ credentials; currently disabled in TestRunner) |
| `framework/upload.py` | `backup()` (local copy) and `upload()` (SFTP via paramiko; currently disabled) |
| `framework/exceltest.py`, `framework/myunittest.py` | Older/demo test scaffolding (`@ddt` example, browser setup base class) |
| `keywordsDriver/keywordKey.py` | Keyword name constants |
| `keywordsDriver/excelKey.py` | Excel sheet/column name constants |
| `keywordsDriver/ColorKey.py` | Result-cell RGB colors (pass=blue, fail=red, error=dark-red) |
| `keywordsDriver/keywordAction.py` | `Action` class (thin wrapper over `BasicPage`) |
| `config/config.ini` + `config/readconfig.py` | Browser/URL/path config; `read(section, option)` helper |
| `setting.py` | Absolute path constants (`BASE_DIR`, `LOG_PATH`, `DATA_PATH`, `reports_dir`, `backup_dir`) |
| `Data/` | `testdata.xlsx` (cases), `element.xml`/`element.py` (legacy locator repo) |
| `tools/` | Web drivers + `HTMLTestRunner*` report generators + `ddt` |
| `reports/result.html` | Generated HTML report output |
| `BackUP/` | Timestamped report + Excel backups (`<year>/<month>/`) |
| `test.py`, `test copy.py` | Scratch/experimental pywinauto scripts (desktop automation of 普通话分级考试系统 Teacher.exe) — not part of the suite |

## Naming and structural gotchas (do not "fix" without updating all references)

- The engine module is **`keywordsFrameword.py`** (misspelled "Frameword"). `TestRunner.py` depends on both this filename and the import `from framework.keywordsFrameword import __generateTestCases`. Renaming it will break discovery.
- `browser_engine.py` calls `readconfig.read('file' 'path', 'driverpath')` — this relies on Python's implicit adjacent-string concatenation to produce the section name `filepath`. Don't "correct" it into two separate args.
- `Selenium` is pinned to `3.141.0` in `requirements.txt`. The code uses `executable_path=` (deprecated/removed in Selenium 4) and other 3.x idioms — do not upgrade Selenium without also migrating `browser_engine.py`.
- The desktop-app vs web dispatch is string-based (`'pywinauto' in str(self.driver)`), and `open_browser` treats a value containing `C:` as a desktop app (`C:\path\to\app.exe,WindowTitle`) instead of a browser name.
- **Test discovery is fragile — do not drop `top_level_dir`.** `TestRunner.py` must call
  `unittest.TestLoader().discover("framework", "keywordsFrameword.py", top_level_dir=rootPath)`.
  Without it, unittest defaults `top_level_dir` to `start_dir` and re-imports the module *without*
  the package prefix, yielding a second `Keyword` class that has none of the `test_*` methods
  injected by `__generateTestCases()`. Result: the suite silently runs **0 tests** while still
  exiting 0 and writing an empty report. Symptom in output: `run=0 errors=0 failures=0`.
- `config.ini`'s `[filepath]` section is **deprecated** — its `../xxx/` values are CWD-relative and are no longer read by any code (paths come from `setting.py`). Only `[browserType]`/`[testserver]` still matter, and even those are largely overridden by the Excel `open_browser`/`open_url` steps. `[Name]` is unused.
- `take_screenshot()` must keep using `os.path.join` and normalising `\`/`/` to `os.sep`. The old
  code did `setting.Screenshot_Path + str(*kw)`, which produced `...ScreenshotFail\` on Windows and
  would embed a literal backslash in the filename on Linux.
