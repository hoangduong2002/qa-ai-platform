from __future__ import annotations

import argparse
import json

from knowledge.services.config import knowledge_base_root
from knowledge.services.knowledge_services import KnowledgeServiceFacade


def main() -> int:
    parser = argparse.ArgumentParser(description="Knowledge Base operational maintenance")
    parser.add_argument("action", choices=["fts5", "health", "reindex", "recover"])
    parser.add_argument("--kb-id", default="")
    parser.add_argument("--actor", default="")
    args = parser.parse_args()

    service = KnowledgeServiceFacade(knowledge_base_root())
    if args.action == "fts5":
        result = {"fts5_supported": service.retriever.verify_fts5()}
    else:
        if not args.kb_id.strip():
            parser.error("--kb-id is required for health, reindex, and recover")
        if args.action in {"reindex", "recover"} and not args.actor.strip():
            parser.error("--actor is required for mutating maintenance actions")
        if args.action == "health":
            result = service.kb_health(args.kb_id)
        elif args.action == "reindex":
            result = service.reindex(args.kb_id, actor=args.actor)
        else:
            result = service.recover(args.kb_id, actor=args.actor)

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
