from core.session import Session


def build_report(session: Session) -> dict:
    skills = {s["id"]: {"name": s["name"], "score": 0.0, "max": 0.0} for s in session.role_cfg["skills"]}

    for r in session.results:
        if r.skill in skills:
            skills[r.skill]["score"] += r.score
            skills[r.skill]["max"] += r.max_score

    for s in skills.values():
        s["fraction"] = round(s["score"] / s["max"], 3) if s["max"] else 0.0

    total_score = sum(s["score"] for s in skills.values())
    total_max = sum(s["max"] for s in skills.values())
    overall = round(total_score / total_max, 3) if total_max else 0.0

    gaps = [name for name, s in skills.items() if s["fraction"] < 0.6]

    if overall >= 0.8 and not gaps:
        verdict = "Ready"
    elif overall >= 0.6:
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
    }
