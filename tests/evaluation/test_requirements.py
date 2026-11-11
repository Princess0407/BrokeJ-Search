from brokej_search.evaluation.requirements import RequirementDecomposer
from brokej_search.evaluation.schemas import RequirementSource


def test_decomposes_mandatory_preferred_and_hard_eligibility() -> None:
    requirements = RequirementDecomposer().decompose(
        RequirementSource(
            description="Must be authorized to work in India. Training provided for Kubernetes.",
            required_skills=["Python"],
            preferred_skills=["Docker"],
            graduation_year_restrictions="Only candidates graduating in 2026 or 2027",
        )
    )
    by_text = {item.original_text: item for item in requirements}
    assert by_text["Python"].criticality == "core_mandatory"
    assert by_text["Docker"].criticality == "preferred"
    assert by_text["Must be authorized to work in India."].criticality == "hard_eligibility"
    assert (
        by_text["Only candidates graduating in 2026 or 2027"].category == "graduation_eligibility"
    )
    assert by_text["Training provided for Kubernetes."].criticality == "trainable"


def test_keeps_ambiguous_must_out_of_hard_eligibility() -> None:
    [requirement] = RequirementDecomposer().decompose(
        RequirementSource(description="You must build reliable developer tools.")
    )
    assert requirement.category == "responsibility"
    assert requirement.criticality == "mandatory_but_ambiguous"


def test_malformed_or_empty_description_produces_no_invented_requirements() -> None:
    decomposer = RequirementDecomposer()
    assert decomposer.decompose(RequirementSource(description="")) == []
    assert decomposer.decompose(RequirementSource(description="<><>")) == []
