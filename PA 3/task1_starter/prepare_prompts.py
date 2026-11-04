"""Prepare exact course prompts locally; no GPU, model downloads, or API calls."""
from pathlib import Path
from task1.prompts import prepare_prompts

if __name__ == "__main__":
    rows = prepare_prompts(Path(__file__).resolve().parent / "inputs/first_plot_questions.yaml")
    print(f"Prepared {len(rows)} prompts; {sum(r['annotate'] for r in rows)} flagged per condition.")
    print("Annotation questions:", ", ".join(dict.fromkeys(r["question_id"] for r in rows if r["annotate"])))
    print("JSON system roles preserved. Judge/sample-count metadata is not executed.")
