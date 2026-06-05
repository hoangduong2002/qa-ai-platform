from app.utils.file_writer import (
    save_testcases
)


def merge_testcases(
    original_testcases: list,
    improved_testcases: list
):
    testcase_map = {}

    for item in original_testcases:
        testcase_id = item.get(
            "testcase_id"
        )

        if testcase_id:
            testcase_map[testcase_id] = item

    for item in improved_testcases:
        testcase_id = item.get(
            "testcase_id"
        )

        if testcase_id:
            testcase_map[testcase_id] = item

    return list(
        testcase_map.values()
    )


def renumber_testcases(
    testcases: list
):
    for index, testcase in enumerate(
        testcases,
        start=1
    ):
        testcase["testcase_id"] = (
            f"TC{index:03d}"
        )

    return testcases


def merge_renumber_and_save_testcases(
    ticket_id: str,
    original_testcases: list,
    improved_testcases: list
):
    merged = merge_testcases(
        original_testcases,
        improved_testcases
    )

    merged = renumber_testcases(
        merged
    )

    save_testcases(
        ticket_id,
        merged
    )

    return merged