from evaluators.base import Evaluator
from evaluators.mcq import MCQEvaluator
from evaluators.open import OpenEvaluator
from evaluators.code import CodeEvaluator

_REGISTRY = {
    "mcq": MCQEvaluator(),
    "open": OpenEvaluator(),
    "code": CodeEvaluator(),
}


def get_evaluator(task_type: str) -> Evaluator:
    if task_type not in _REGISTRY:
        raise ValueError(f"No evaluator for task type: {task_type}")
    return _REGISTRY[task_type]
