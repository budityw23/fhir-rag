from eval.evaluate import _matches_expectation, _retrieval_recall, load_questions


class _Resource:
    def __init__(self, resource_type: str):
        self.resource_type = resource_type


def test_date_expectation_matches_a_full_iso_timestamp():
    # Rendered resources carry "2025-04-06T12:39:43+07:00"; a trailing word
    # boundary after the day fails against the "T" and scored every temporal
    # question zero.
    assert _matches_expectation("Onset 2025-04-06T12:39:43+07:00.", "date")


def test_chronological_expectation_needs_two_timestamps():
    one = "Diagnosed 2020-11-06T12:39:43+07:00."
    two = one + " Then 2025-02-01T12:39:43+07:00."
    assert not _matches_expectation(one, "chronological events with dates")
    assert _matches_expectation(two, "chronological events with dates")


def test_duration_expectation_accepts_either_form():
    assert _matches_expectation("for 12 years", "duration or date")
    assert _matches_expectation("since 1977-08-31T00:00:00+07:00", "duration or date")


def test_alternatives_are_matched_case_insensitively():
    assert _matches_expectation("Prescribed Simvastatin 20 MG.", "simvastatin|statin")
    assert not _matches_expectation("Prescribed metformin.", "simvastatin|statin")


def test_negative_questions_do_not_score_recall_on_retrieved_resources():
    # Patient-scoped retrieval still returns that patient's other resources,
    # so recall is not a meaningful signal for a question with no expectation.
    question = {"expected_resource_types": []}
    assert _retrieval_recall(question, [_Resource("Observation")]) == 1.0


def test_dataset_questions_reference_real_patients():
    for question in load_questions():
        assert question["patient_ref"].startswith("Patient/")
        assert "{" not in question["patient_ref"]
        assert question["cohort"] in {"diabetes", "pediatric_atopic"}
