#!/usr/bin/env python3
"""
GitHub Sub-Issue Suggester

Uses the task decomposer to analyze GitHub issues and suggest
breakdown into multiple sub-issues.
"""

import sys
import asyncio
import argparse
from pathlib import Path

# Add repository root to path to allow imports
repo_root = Path(__file__).resolve().parent.parent
candidate_roots = [
    repo_root,
    repo_root / "workspace" / "projects" / "ai-council-system",
]

for path in candidate_roots:
    if path.exists() and str(path) not in sys.path:
        sys.path.insert(0, str(path))

try:
    from swarm.orchestrator.task_decomposer import TaskDecomposer, TaskType
except ImportError as e:
    print(f"Error: Could not import task decomposer. Make sure you're running from the repository root.", file=sys.stderr)
    print(f"Details: {e}", file=sys.stderr)
    sys.exit(1)


class SubIssueSuggester:
    """Suggests sub-issues for GitHub issues using task decomposition"""

    def __init__(self):
        self.decomposer = TaskDecomposer()

    async def suggest_sub_issues(
        self,
        issue_title: str,
        issue_description: str,
        task_type: str = "development"
    ) -> str:
        """
        Analyze issue and suggest sub-issues

        Args:
            issue_title: Title of the GitHub issue
            issue_description: Description/body of the issue
            task_type: Type of task (development, research, analysis, testing, documentation, architecture)

        Returns:
            Formatted string with sub-issue suggestions
        """
        # Map string to TaskType enum
        type_mapping = {
            "development": TaskType.DEVELOPMENT,
            "research": TaskType.RESEARCH,
            "analysis": TaskType.ANALYSIS,
            "testing": TaskType.TESTING,
            "documentation": TaskType.DOCUMENTATION,
            "architecture": TaskType.ARCHITECTURE,
        }

        task_type_enum = type_mapping.get(task_type.lower(), TaskType.DEVELOPMENT)

        # Combine title and description for decomposition
        full_description = f"{issue_title}\n\n{issue_description}" if issue_description else issue_title

        # Decompose the task
        result = await self.decomposer.decompose_task(
            task_description=full_description,
            task_type=task_type_enum,
            context={"source": "github_issue"}
        )

        # Format as GitHub issue suggestions
        return self._format_suggestions(result, issue_title)

    def _format_suggestions(self, result, parent_title: str) -> str:
        """Format decomposition result as GitHub issue suggestions"""
        output = []
        output.append("# Suggested Sub-Issues")
        output.append("")
        output.append(f"**Parent Issue:** {parent_title}")
        output.append(f"**Total Estimated Effort:** {result.estimated_total_effort} story points")
        output.append(f"**Number of Sub-tasks:** {len(result.subtasks)}")
        output.append("")
        output.append("---")
        output.append("")

        # Group by execution order
        for batch_num, batch in enumerate(result.execution_order, 1):
            output.append(f"## Phase {batch_num}")
            output.append("")

            batch_tasks = [t for t in result.subtasks if t.task_id in batch]

            for task in batch_tasks:
                # Mark critical path tasks
                critical_marker = " 🔴 **CRITICAL PATH**" if task.task_id in result.critical_path else ""
                output.append(f"### {task.title}{critical_marker}")
                output.append("")
                output.append(f"**Description:** {task.description}")
                output.append("")
                output.append(f"**Estimated Effort:** {task.estimated_effort} story points")
                output.append(f"**Priority:** {task.priority.value}")
                output.append(f"**Required Capabilities:** {', '.join(task.required_capabilities)}")
                output.append("")

                if task.acceptance_criteria:
                    output.append("**Acceptance Criteria:**")
                    for criterion in task.acceptance_criteria:
                        output.append(f"- [ ] {criterion}")
                    output.append("")

                if task.dependencies:
                    output.append("**Dependencies:**")
                    for dep in task.dependencies:
                        output.append(f"- Depends on: `{dep.task_id}` ({dep.dependency_type})")
                    output.append("")
                else:
                    output.append("**Dependencies:**")
                    output.append("- Depends on: `none` (blocks)")
                    output.append("")

                output.append("**Labels:** " + ", ".join([
                    f"`{task.task_type.value}`",
                    f"`{task.priority.value}-priority`",
                    "`sub-issue`"
                ]))
                output.append("")
                output.append("---")
                output.append("")

        output.append("## Execution Summary")
        output.append("")
        output.append("**Recommended Execution Order:**")
        for i, batch in enumerate(result.execution_order, 1):
            output.append(f"{i}. {', '.join(batch)} (can be done in parallel)")
        output.append("")
        output.append("**Critical Path:**")
        output.append(f"- {' → '.join(result.critical_path)}")
        output.append("")

        return "\n".join(output)


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Suggest sub-issues for GitHub issues"
    )
    parser.add_argument(
        "title",
        help="Issue title"
    )
    parser.add_argument(
        "--description",
        "-d",
        default="",
        help="Issue description/body"
    )
    parser.add_argument(
        "--type",
        "-t",
        default="development",
        choices=["development", "research", "analysis", "testing", "documentation", "architecture"],
        help="Type of task"
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Output file (default: stdout)"
    )

    args = parser.parse_args()

    suggester = SubIssueSuggester()
    suggestions = await suggester.suggest_sub_issues(
        issue_title=args.title,
        issue_description=args.description,
        task_type=args.type
    )

    if args.output:
        with open(args.output, "w") as f:
            f.write(suggestions)
        print(f"Suggestions written to {args.output}")
    else:
        print(suggestions)


if __name__ == "__main__":
    asyncio.run(main())
