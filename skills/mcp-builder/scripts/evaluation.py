#!/usr/bin/env python3
"""
MCP Server Evaluation Script

Evaluates an MCP server for quality, correctness, and best practices.
"""

import asyncio
import json
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional


@dataclass
class EvaluationResult:
    """Result of a single evaluation check."""
    name: str
    passed: bool
    message: str
    severity: str  # 'error', 'warning', 'info'


class MCPEvaluator:
    """Evaluates MCP servers for quality and correctness."""

    def __init__(self, server_command: list[str]):
        self.server_command = server_command
        self.results: list[EvaluationResult] = []

    async def evaluate(self) -> list[EvaluationResult]:
        """Run all evaluation checks."""
        self.results = []

        # Basic checks
        await self._check_server_starts()
        await self._check_tools_list()
        await self._check_tool_schemas()
        await self._check_resources_list()

        return self.results

    async def _check_server_starts(self):
        """Verify server starts without errors."""
        try:
            process = await asyncio.create_subprocess_exec(
                *self.server_command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            # Send initialize request
            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "mcp-evaluator", "version": "1.0.0"}
                }
            }

            stdin_data = json.dumps(request) + "\n"
            stdout, stderr = await asyncio.wait_for(
                process.communicate(stdin_data.encode()),
                timeout=10.0
            )

            if process.returncode == 0 or stdout:
                self.results.append(EvaluationResult(
                    name="Server Startup",
                    passed=True,
                    message="Server starts successfully",
                    severity="info"
                ))
            else:
                self.results.append(EvaluationResult(
                    name="Server Startup",
                    passed=False,
                    message=f"Server failed to start: {stderr.decode()}",
                    severity="error"
                ))
        except asyncio.TimeoutError:
            self.results.append(EvaluationResult(
                name="Server Startup",
                passed=False,
                message="Server startup timed out",
                severity="error"
            ))
        except Exception as e:
            self.results.append(EvaluationResult(
                name="Server Startup",
                passed=False,
                message=f"Error starting server: {str(e)}",
                severity="error"
            ))

    async def _check_tools_list(self):
        """Verify tools/list returns valid response."""
        try:
            result = await self._send_request("tools/list", {})

            if result and "tools" in result:
                tools = result["tools"]
                self.results.append(EvaluationResult(
                    name="Tools List",
                    passed=True,
                    message=f"Found {len(tools)} tool(s)",
                    severity="info"
                ))

                if len(tools) == 0:
                    self.results.append(EvaluationResult(
                        name="Tools Count",
                        passed=False,
                        message="Server has no tools defined",
                        severity="warning"
                    ))
            else:
                self.results.append(EvaluationResult(
                    name="Tools List",
                    passed=False,
                    message="Invalid tools/list response",
                    severity="error"
                ))
        except Exception as e:
            self.results.append(EvaluationResult(
                name="Tools List",
                passed=False,
                message=f"Error listing tools: {str(e)}",
                severity="error"
            ))

    async def _check_tool_schemas(self):
        """Verify tool schemas are well-formed."""
        try:
            result = await self._send_request("tools/list", {})

            if result and "tools" in result:
                for tool in result["tools"]:
                    # Check required fields
                    if "name" not in tool:
                        self.results.append(EvaluationResult(
                            name=f"Tool Schema",
                            passed=False,
                            message="Tool missing 'name' field",
                            severity="error"
                        ))
                        continue

                    name = tool["name"]

                    if "description" not in tool or not tool["description"]:
                        self.results.append(EvaluationResult(
                            name=f"Tool '{name}' Description",
                            passed=False,
                            message="Tool missing description",
                            severity="warning"
                        ))

                    if "inputSchema" in tool:
                        schema = tool["inputSchema"]
                        if schema.get("type") != "object":
                            self.results.append(EvaluationResult(
                                name=f"Tool '{name}' Schema",
                                passed=False,
                                message="inputSchema type should be 'object'",
                                severity="warning"
                            ))
                    else:
                        self.results.append(EvaluationResult(
                            name=f"Tool '{name}' Schema",
                            passed=True,
                            message="Tool has valid schema (no input required)",
                            severity="info"
                        ))
        except Exception as e:
            self.results.append(EvaluationResult(
                name="Tool Schemas",
                passed=False,
                message=f"Error checking schemas: {str(e)}",
                severity="error"
            ))

    async def _check_resources_list(self):
        """Verify resources/list returns valid response."""
        try:
            result = await self._send_request("resources/list", {})

            if result is not None:
                resources = result.get("resources", [])
                self.results.append(EvaluationResult(
                    name="Resources List",
                    passed=True,
                    message=f"Found {len(resources)} resource(s)",
                    severity="info"
                ))
        except Exception as e:
            # Resources are optional, so this isn't necessarily an error
            self.results.append(EvaluationResult(
                name="Resources List",
                passed=True,
                message="Resources not implemented (optional)",
                severity="info"
            ))

    async def _send_request(self, method: str, params: dict) -> Optional[dict]:
        """Send a JSON-RPC request to the server."""
        process = await asyncio.create_subprocess_exec(
            *self.server_command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # Initialize first
        init_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "mcp-evaluator", "version": "1.0.0"}
            }
        }

        # Then send actual request
        request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": method,
            "params": params
        }

        stdin_data = json.dumps(init_request) + "\n" + json.dumps(request) + "\n"
        stdout, _ = await asyncio.wait_for(
            process.communicate(stdin_data.encode()),
            timeout=10.0
        )

        # Parse responses
        for line in stdout.decode().strip().split("\n"):
            if line:
                try:
                    response = json.loads(line)
                    if response.get("id") == 2:
                        return response.get("result")
                except json.JSONDecodeError:
                    continue

        return None

    def print_report(self):
        """Print evaluation report."""
        print("\n" + "=" * 60)
        print("MCP SERVER EVALUATION REPORT")
        print("=" * 60 + "\n")

        errors = [r for r in self.results if r.severity == "error" and not r.passed]
        warnings = [r for r in self.results if r.severity == "warning" and not r.passed]
        passed = [r for r in self.results if r.passed]

        if passed:
            print("✅ PASSED:")
            for r in passed:
                print(f"   • {r.name}: {r.message}")
            print()

        if warnings:
            print("⚠️  WARNINGS:")
            for r in warnings:
                print(f"   • {r.name}: {r.message}")
            print()

        if errors:
            print("❌ ERRORS:")
            for r in errors:
                print(f"   • {r.name}: {r.message}")
            print()

        print("-" * 60)
        print(f"Total: {len(passed)} passed, {len(warnings)} warnings, {len(errors)} errors")
        print("=" * 60)

        return len(errors) == 0


async def main():
    if len(sys.argv) < 2:
        print("Usage: python evaluation.py <server_command> [args...]")
        print("Example: python evaluation.py python my_server.py")
        sys.exit(1)

    evaluator = MCPEvaluator(sys.argv[1:])
    await evaluator.evaluate()
    success = evaluator.print_report()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
