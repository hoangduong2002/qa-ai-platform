import shutil

from pathlib import Path


def delete_requirement(
    ticket_id: str
) -> bool:

    requirement_dir = (
        Path("requirements")
        / ticket_id
    )

    if not requirement_dir.exists():
        return False

    shutil.rmtree(
        requirement_dir
    )

    return True


def delete_all_requirements():

    requirements_dir = Path(
        "requirements"
    )

    if not requirements_dir.exists():
        return 0

    count = 0

    for folder in requirements_dir.iterdir():

        if not folder.is_dir():
            continue

        shutil.rmtree(folder)

        count += 1

    return count