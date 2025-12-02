#!/usr/bin/env python3
"""
MCP 서버: RAG answer_query 함수를 MCP Tool로 노출
"""

import asyncio
import sys
from pathlib import Path
from typing import Any, Sequence

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# --- 프로젝트 루트 경로 추가 (scripts, src import용) ---
ROOT = Path(__file__).resolve().parents[2]  # mindual-mcp 루트
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 이제 scripts.query_rag 를 import 할 수 있음
from scripts.query_rag import answer_query

# MCP Server 인스턴스 생성
server = Server("manual-rag-server")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """사용 가능한 MCP Tool 목록"""
    return [
        Tool(
            name="answer_query",
            description="전자제품 매뉴얼(RAG)을 이용해 사용자 질문에 답변합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "사용자의 자연어 질문",
                    },
                    "k": {
                        "type": "integer",
                        "description": "검색할 문단 개수 (기본 5)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> Sequence[TextContent]:
    """Tool 호출 실제 처리 로직"""
    try:
        if name == "answer_query":
            query = arguments.get("query", "")
            k = int(arguments.get("k", 5))

            if not query.strip():
                return [TextContent(type="text", text="query 가 비어 있습니다.")]

            answer = answer_query(query, k=k)  # scripts/query_rag.py 함수 호출
            return [TextContent(type="text", text=answer)]

        # 여기에 나중에 다른 에이전트/툴 추가 가능

        return [TextContent(type="text", text=f"알 수 없는 도구: {name}")]

    except Exception as e:
        return [TextContent(type="text", text=f"[MCP 서버 에러] {e}")]


async def main() -> None:
    """표준 입출력(stdio) 기반 MCP 서버 실행"""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Ctrl+C 로 조용히 종료
        pass