from evaluators.base import Evaluator, EvaluationResult


class MCQEvaluator(Evaluator):
    def evaluate(self, task: dict, answer: str) -> EvaluationResult:
        correct = str(answer).strip().lower() == str(task.get("answer", "")).strip().lower()
        max_score = task.get("max_score", 1)
        return EvaluationResult(
            task_id=task["id"],
            skill=task["skill"],
            score=max_score if correct else 0,
            max_score=max_score,
            rationale="Correct" if correct else f"Expected {task.get('answer')}, got {answer}",
        )
