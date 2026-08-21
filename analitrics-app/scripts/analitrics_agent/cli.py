from __future__ import annotations

import argparse
import json
import sys
from uuid import uuid4

from .config import bool_env
from .agent import AnalyticalAgentFactory
from .models import AgentRequest, state_output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analitrics LangGraph agent over LibreChat S3 files")
    parser.add_argument("--file-id", action="append", help="LibreChat file_id. Can be passed multiple times.")
    parser.add_argument("--filename", action="append", help="LibreChat filename. Can be passed multiple times.")
    parser.add_argument("--file-ids", help="Comma-separated LibreChat file_ids.")
    parser.add_argument("--filenames", help="Comma-separated LibreChat filenames.")
    parser.add_argument("--tenant-id", default="analitrics")
    parser.add_argument("--user-id")
    parser.add_argument("--conversation-id")
    parser.add_argument("--message-id")
    parser.add_argument("--cache-dir", default="/var/analitrics/analytics/cache")
    parser.add_argument("--question", required=True)
    parser.add_argument("--sample-rows", type=int, default=5)
    parser.add_argument("--run-id")
    return parser.parse_args()


def request_from_args(args: argparse.Namespace) -> AgentRequest:
    return AgentRequest(
        question=args.question,
        tenant_id=args.tenant_id,
        user_id=args.user_id,
        conversation_id=args.conversation_id,
        message_id=args.message_id,
        file_id=args.file_id,
        filename=args.filename,
        file_ids=args.file_ids,
        filenames=args.filenames,
        cache_dir=args.cache_dir,
        sample_rows=args.sample_rows,
        run_id=args.run_id or str(uuid4()),
    )


def main() -> None:
    request = request_from_args(parse_args())
    try:
        result = AnalyticalAgentFactory.get_agent().run(request)
        print(json.dumps(state_output(request, result), ensure_ascii=False, indent=2))
    except Exception as exc:
        if bool_env("ANALITRICS_DEBUG_ERRORS", False):
            raise
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
