from app.services.local_requirement_service import (
    LocalRequirementService
)


def get_requirement_service():

    return (
        LocalRequirementService()
    )