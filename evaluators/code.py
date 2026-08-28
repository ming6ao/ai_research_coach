import json
import os
import subprocess
import sys
import tempfile
import textwrap
from evaluators.base import Evaluator, EvaluationResult

HARNESS = """
import os, json, importlib.util, math

def _to_list(a):
    if hasattr(a, "tolist"):
        return a.tolist()
    return a

def approx(a, b, tol):
    a = _to_list(a)
    b = _to_list(b)
    if isinstance(b, (int, float)):
        return abs(a - b) <= tol
    if isinstance(b, list):
        return len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b))
    return a == b

spec = importlib.util.spec_from_file_location("solution", os.environ["SOL_PATH"])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
fn = mod.__dict__[os.environ["FN"]]
inp = json.loads(os.environ["INP"])
exp = json.loads(os.environ["EXP"])
tol = float(os.environ["TOL"])
out = fn(*inp)
ok = approx(out, exp, tol)
print(json.dumps({"ok": ok, "out": repr(out)}))
"""


class CodeEvaluator(Evaluator):
    def evaluate(self, task: dict, answer: str) -> EvaluationResult:
        max_score = task.get("max_score", 5)
        tests = task.get("tests", [])
        tolerance = task.get("tolerance", 1e-3)
        fn = task.get("function_name")

        if not tests:
            return EvaluationResult(task["id"], task["skill"], 0, max_score, "No tests defined")

        results = [self._run_one(fn, answer, t, tolerance) for t in tests]
        passed = sum(1 for r in results if r["ok"])
        score = round(max_score * passed / len(tests), 3)
        rationale = "; ".join(f"test{i+1}:{'pass' if r['ok'] else 'fail'} {r['msg']}" for i, r in enumerate(results))
        return EvaluationResult(task["id"], task["skill"], score, max_score, rationale)

    def _run_one(self, fn, code, test, tol):
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write(code)
            sol_path = f.name
        env = dict(os.environ)
        env.update({
            "SOL_PATH": sol_path,
            "FN": fn,
            "INP": json.dumps(test.get("input")),
            "EXP": json.dumps(test.get("expected")),
            "TOL": str(tol),
        })
        try:
            proc = subprocess.run(
                [sys.executable, "-c", HARNESS],
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
            )
            if proc.returncode != 0:
                return {"ok": False, "msg": f"error: {proc.stderr.strip()[:200]}"}
            payload = json.loads(proc.stdout.strip().splitlines()[-1])
            return {"ok": payload["ok"], "msg": f"out={payload['out']}"}
        except subprocess.TimeoutExpired:
            return {"ok": False, "msg": "timeout"}
        except Exception as e:
            return {"ok": False, "msg": str(e)[:200]}
        finally:
            os.unlink(sol_path)
