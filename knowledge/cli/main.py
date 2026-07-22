from __future__ import annotations

import argparse

from knowledge.services.runtime import get_knowledge_service


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Knowledge Base CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate-kb")
    validate.add_argument("--kb-id", required=True)

    rebuild = sub.add_parser("rebuild-index")
    rebuild.add_argument("--kb-id", required=True)

    health = sub.add_parser("check-health")
    health.add_argument("--kb-id", required=True)

    verify = sub.add_parser("verify-filesystem-metadata")
    verify.add_argument("--kb-id", required=True)

    recover = sub.add_parser("recover")
    recover.add_argument("--kb-id", required=True)
    recover.add_argument("--actor", default="cli")

    return parser


def main() -> int:
    args = _parser().parse_args()
    service = get_knowledge_service()

    if args.command == "validate-kb":
        print(service.validate_kb(args.kb_id))
        return 0

    if args.command == "rebuild-index":
        print(service.reindex(args.kb_id, actor="cli"))
        return 0

    if args.command == "check-health":
        print(service.kb_health(args.kb_id))
        return 0

    if args.command == "verify-filesystem-metadata":
        print(service.verify_metadata(args.kb_id))
        return 0

    if args.command == "recover":
        print(service.recover(args.kb_id, actor=args.actor))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
