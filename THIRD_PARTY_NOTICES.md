# Third-party notices

AI CAD Copilot is licensed under the MIT License. This file records third-party code,
runtime dependencies, and license caveats that users and distributors should review.

This is not legal advice. If your use case involves redistribution, SaaS, or a commercial
product, verify the obligations with your legal/compliance team.

## 1. Adapted source code: freecad-mcp

Parts of the FreeCAD object serialization, property mapping, post-recompute validation,
viewport capture, GUI-dispatch health design, and selected operation patterns are adapted
from [`neka-nat/freecad-mcp`](https://github.com/neka-nat/freecad-mcp), reviewed at commit
`0ff3dd380f0deb13677affb4d9a0c94fae326c44a`.

The upstream project is MIT-licensed. Its notice is retained below.

```text
MIT License

Copyright (c) 2025 Shirokuma (k tanaka)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

Adapted files are not a verbatim copy of the upstream repository. The project-specific
CadPlan schema, design engine, drawing layout/validator, inspection pipeline, and web UI are
original work unless otherwise stated.

## 2. Runtime: FreeCAD / OpenCascade

- **FreeCAD** — <https://github.com/FreeCAD/FreeCAD> — LGPL-2.1-or-later.
- **OpenCascade Technology (OCCT)** — <https://dev.opencascade.org/> — LGPL-2.1 with
  additional notices, as distributed with FreeCAD.

This repository does **not** bundle FreeCAD or OCCT binaries. Users install FreeCAD separately.
The FreeCAD Add-on runs inside the user's FreeCAD process and uses its public Python API.
Refer to the FreeCAD distribution for the exact license texts and third-party notices.

## 3. Python dependencies

The default `requirements.txt` installs the following packages (or newer compatible versions
at install time). Licenses are those declared by the upstream projects at the time of the
v0.2.0 release; always re-check the installed package metadata.

| Package | License | Upstream |
|---|---|---|
| fastapi | MIT | <https://github.com/fastapi/fastapi> |
| uvicorn | BSD-3-Clause | <https://github.com/encode/uvicorn> |
| python-multipart | Apache-2.0 | <https://github.com/Kludex/python-multipart> |
| requests | Apache-2.0 | <https://github.com/psf/requests> |
| openai | Apache-2.0 | <https://github.com/openai/openai-python> |
| langchain | MIT | <https://github.com/langchain-ai/langchain> |
| langchain-core | MIT | <https://github.com/langchain-ai/langchain> |
| langchain-openai | MIT | <https://github.com/langchain-ai/langchain> |
| langgraph | MIT | <https://github.com/langchain-ai/langgraph> |
| langchain-mcp-adapters | MIT | <https://github.com/langchain-ai/langchain-mcp-adapters> |
| fastmcp | Apache-2.0 | <https://github.com/jlowin/fastmcp> |
| pydantic | MIT | <https://github.com/pydantic/pydantic> |
| ezdxf | MIT | <https://github.com/mozman/ezdxf> |
| streamlit | Apache-2.0 | <https://github.com/streamlit/streamlit> |
| pandas | BSD-3-Clause | <https://github.com/pandas-dev/pandas> |
| python-dotenv | BSD-3-Clause | <https://github.com/theskumar/python-dotenv> |
| PyYAML | MIT | <https://github.com/yaml/pyyaml> |
| pytest (development) | MIT | <https://github.com/pytest-dev/pytest> |

No license text is reproduced here for these packages; the installed distributions include
their own license files. If you redistribute a bundled environment, include those notices.

## 4. Frontend dependencies

| Package | License | Upstream |
|---|---|---|
| vue | MIT | <https://github.com/vuejs/core> |
| vite | MIT | <https://github.com/vitejs/vite> |
| @vitejs/plugin-vue | MIT | <https://github.com/vitejs/vite-plugin-vue> |

`frontend/dist` is a compiled artifact of this repository's Vue source. It contains no
third-party runtime beyond the above build-time packages.

## 5. Optional dependency with AGPL: PyMuPDF

`inspection/reviewer.py` can parse PDF drawings with **PyMuPDF**. PyMuPDF is dual-licensed:

- **GNU Affero General Public License v3.0 (AGPL-3.0)**, or
- a commercial license from Artifex Software.

Because AGPL can impose source-disclosure and network-use obligations, PyMuPDF is **not** in
`requirements.txt`. It is only installed by explicit opt-in:

```powershell
python -m pip install -r requirements-pdf.txt
```

If you enable PDF review, you are responsible for determining whether your use and
distribution comply with AGPL-3.0 or whether you need a commercial license. The rest of the
project does not require PyMuPDF.

## 6. Datasets and standards

`knowledge_base/gbt.py` and `knowledge_base/rules_data.py` contain a small, manually curated
subset of GB/T dimensional/tolerance/material data for demonstration. Standards documents
themselves are not redistributed. Verify values against the current official standards before
engineering use.

## 7. No warranty

The project is a research/teaching prototype. It is provided “as is”, without warranty of any
kind. See `LICENSE`.
