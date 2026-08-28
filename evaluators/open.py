from evaluators.base import Evaluator, EvaluationResult
from judge.llm_judge import score_open


class OpenEvaluator(Evaluator):
    def evaluate(self, task: dict, answer: str) -> EvaluationResult:
        max_score = task.get("max_score", 5)
        score, rationale = score_open(task["prompt"], answer, task.get("rubric", ""), max_score)
        return EvaluationResult(
            task_id=task["id"],
            skill=task["skill"],
            score=score,
            max_score=max_score,
            rationale=rationale,
        )
