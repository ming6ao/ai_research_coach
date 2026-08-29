"""Build assessment report from session data.

Generates a competency profile with scores, confidence, and evidence.
"""

from core.session import Session, SkillState


def build_report(session: Session) -> dict:
    """Build final assessment report.

    Returns:
        Dictionary containing:
        - candidate: Candidate name
        - role: Role name
        - overall_score: Weighted overall score (0.0 - 1.0)
        - verdict: Readiness assessment
        - skill_breakdown: Per-skill scores with evidence
        - gaps: Skills needing improvement
        - questions_answered: Total questions answered
    """
    skills = {}
    total_weighted_score = 0.0
    total_weight = 0.0

    for skill_cfg in session.role_cfg.get("skills", []):
        skill_id = skill_cfg["id"]
        state = session.get_skill_state(skill_id)
        importance = skill_cfg.get("importance", 3)

        # Calculate score as fraction (0.0 - 1.0)
        # For MCQ: score is 0 or 1, so fraction is direct
        # For open/code: score is 0-5, so fraction is score/5
        # We use the normalized score from SkillState which is already 0-1
        fraction = state.score

        skills[skill_id] = {
            "name": skill_cfg["name"],
            "score": fraction,
            "confidence": state.confidence,
            "questions_answered": state.questions_answered,
            "evidence": state.evidence,
            "importance": importance,
        }

        # Weighted score for overall calculation
        total_weighted_score += fraction * importance
        total_weight += importance

    # Overall score (importance-weighted average)
    overall = round(total_weighted_score / total_weight, 3) if total_weight else 0.0

    # Identify gaps (score < 0.6 or low confidence with high importance)
    gaps = []
    for skill_id, skill_data in skills.items():
        if skill_data["score"] < 0.6:
            gaps.append(skill_id)
        elif skill_data["importance"] >= 4 and skill_data["confidence"] < 0.5:
            gaps.append(skill_id)

    # Determine verdict
    high_importance_gaps = [
        s for s in gaps
        if skills[s]["importance"] >= 4
    ]

    if overall >= 0.8 and not high_importance_gaps:
        verdict = "Ready"
    elif overall >= 0.6 and len(high_importance_gaps) <= 1:
        verdict = "Conditionally ready - strengthen gaps"
    else:
        verdict = "Not ready"

    return {
        "candidate": session.candidate,
        "role": session.role_cfg["name"],
        "overall_score": overall,
        "verdict": verdict,
        "skill_breakdown": skills,
        "gaps": gaps,
        "questions_answered": session.index,
    }
