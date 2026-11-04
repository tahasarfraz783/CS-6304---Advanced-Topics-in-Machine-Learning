# Protocol sources

- User-provided assignment excerpt: `inputs/task3_requirements.txt`.
- Supplied dataset README: `inputs/README.MD`, obtained from the [assignment Drive folder](https://drive.google.com/drive/folders/1utX-Gfi9vvaoi1mi0pzNpDGL1o1fAh23).
- [Qwen inference documentation](https://qwen.readthedocs.io/en/v2.5/inference/chat.html): Transformers attention backends and cache-based generation.
- [Math-Verify source and API](https://github.com/huggingface/Math-Verify): pinned `math-verify==0.9.0`, parse/verify mathematical equivalence.
- [Math-Verify Windows timeout issue](https://github.com/huggingface/Math-Verify/issues/79): explains the local Windows-only timeout workaround.
- [Released MathVista testmini metadata](https://github.com/lupantech/MathVista/blob/main/data/testmini.json): bundled copy in `inputs/mathvista_testmini.json` with runtime hash provenance.
- [Released MathVista scoring code](https://github.com/lupantech/MathVista/blob/main/evaluation/calculate_score.py): choice/type/precision rules, saved as a reference in `inputs`.

No paid API, extra verifier model, or gold feedback is used during selection or live generation.
