from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from .models import AppliedSectionChange, SectionEdit


BACKEND_ROOT = Path(__file__).resolve().parents[2]
TESTING_ROOT = BACKEND_ROOT / "testing"


@dataclass(frozen=True)
class EditPolicy:
    path: str
    selector_types: tuple[str, ...]
    apply_mode: str
    note: str


def normalize_repo_path(path: str) -> str:
    normalized = path.replace("\\", "/").lstrip("./")
    if normalized.startswith("backend/"):
        return normalized
    return f"backend/{normalized}"


def get_policy(path: str) -> EditPolicy | None:
    normalized = normalize_repo_path(path)
    if not normalized.startswith("backend/testing/"):
        return None

    if normalized.endswith(".py"):
        selector_types = ("python_symbol", "text_between")
        note = "Testing Python modules may be changed through one symbol or one anchored block at a time."
    elif normalized.endswith(".md"):
        selector_types = ("markdown_heading", "text_between")
        note = "Testing markdown files may be changed through one heading block or one anchored block at a time."
    elif normalized.endswith(".json"):
        selector_types = ("text_between",)
        note = "Testing JSON-like files may only be changed through exact anchored text blocks."
    else:
        return None

    return EditPolicy(
        path=normalized,
        selector_types=selector_types,
        apply_mode="auto_apply",
        note=note,
    )


def path_is_blocked(path: str) -> bool:
    normalized = normalize_repo_path(path)
    return not normalized.startswith("backend/testing/")


def read_target_file(path: str) -> str:
    absolute_path = BACKEND_ROOT.parent / normalize_repo_path(path)
    return absolute_path.read_text(encoding="utf-8")


def candidate_paths_for_category(category: str) -> list[str]:
    del category
    candidates: list[str] = []
    for path in sorted(TESTING_ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(BACKEND_ROOT.parent).as_posix()
        if "/outputs/" in relative or "/reports/" in relative or "__pycache__" in relative:
            continue
        if path.suffix not in {".py", ".md", ".json"}:
            continue
        candidates.append(relative)
    return candidates


def _extract_python_symbols(text: str) -> list[str]:
    tree = ast.parse(text)
    symbols: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.append(node.name)
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        symbols.append(f"{node.name}.{child.name}")
    return symbols


def selector_hints(path: str, text: str) -> list[str]:
    normalized = normalize_repo_path(path)
    if normalized.endswith(".py"):
        return _extract_python_symbols(text)
    if normalized.endswith(".md"):
        hints: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                hints.append(stripped.lstrip("#").strip())
        return hints
    return []


def _locate_python_symbol(text: str, selector_value: str) -> tuple[int, int]:
    tree = ast.parse(text)
    target: ast.AST | None = None
    class_name, _, member_name = selector_value.partition(".")

    for node in tree.body:
        if member_name:
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == member_name:
                        target = child
                        break
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == selector_value:
            target = node
        if target is not None:
            break

    if target is None or not hasattr(target, "lineno") or not hasattr(target, "end_lineno"):
        raise ValueError(f"Python selector not found or not bounded: {selector_value}")

    return int(target.lineno) - 1, int(target.end_lineno)


def _locate_markdown_heading(text: str, selector_value: str) -> tuple[int, int]:
    lines = text.splitlines(keepends=True)
    heading_line_index: int | None = None
    heading_level: int | None = None
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if not stripped.startswith("#"):
            continue
        level = len(stripped) - len(stripped.lstrip("#"))
        heading_text = stripped[level:].strip()
        if heading_text == selector_value:
            if heading_line_index is not None:
                raise ValueError(f"Multiple markdown headings matched: {selector_value}")
            heading_line_index = index
            heading_level = level

    if heading_line_index is None or heading_level is None:
        raise ValueError(f"Markdown heading not found: {selector_value}")

    end_index = len(lines)
    for index in range(heading_line_index + 1, len(lines)):
        stripped = lines[index].lstrip()
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            if level <= heading_level:
                end_index = index
                break
    return heading_line_index, end_index


def _locate_text_between(text: str, selector_value: str) -> tuple[int, int, str, str]:
    start_anchor, separator, end_anchor = selector_value.partition("|")
    if separator != "|" or not start_anchor or not end_anchor:
        raise ValueError("text_between selector must be formatted as START|END")

    if text.count(start_anchor) != 1 or text.count(end_anchor) != 1:
        raise ValueError("text_between anchors must each appear exactly once")

    start_anchor_index = text.index(start_anchor)
    end_anchor_index = text.index(end_anchor)
    if start_anchor_index >= end_anchor_index:
        raise ValueError("text_between anchors are in the wrong order")

    start_index = start_anchor_index + len(start_anchor)
    end_index = end_anchor_index
    return start_index, end_index, start_anchor, end_anchor


def apply_section_edit(edit: SectionEdit) -> AppliedSectionChange:
    normalized_path = normalize_repo_path(edit.path)
    policy = get_policy(normalized_path)
    if policy is None:
        return AppliedSectionChange(
            path=normalized_path,
            selector_type=edit.selector_type,
            selector_value=edit.selector_value,
            applied=False,
            blocked=path_is_blocked(normalized_path),
            error="Target path is not allowlisted for bounded auto-apply.",
        )

    if edit.selector_type not in policy.selector_types:
        return AppliedSectionChange(
            path=normalized_path,
            selector_type=edit.selector_type,
            selector_value=edit.selector_value,
            applied=False,
            blocked=False,
            error=f"Selector type '{edit.selector_type}' is not allowed for {normalized_path}.",
        )

    absolute_path = BACKEND_ROOT.parent / normalized_path
    original_text = absolute_path.read_text(encoding="utf-8")

    try:
        if edit.selector_type == "python_symbol":
            lines = original_text.splitlines(keepends=True)
            start_line, end_line = _locate_python_symbol(original_text, edit.selector_value)
            before_content = "".join(lines[start_line:end_line])
            replacement = edit.replacement
            if replacement and not replacement.endswith("\n"):
                replacement += "\n"
            updated_text = "".join(lines[:start_line]) + replacement + "".join(lines[end_line:])
            after_content = replacement
        elif edit.selector_type == "markdown_heading":
            lines = original_text.splitlines(keepends=True)
            start_line, end_line = _locate_markdown_heading(original_text, edit.selector_value)
            before_content = "".join(lines[start_line:end_line])
            replacement = edit.replacement
            if replacement and not replacement.endswith("\n"):
                replacement += "\n"
            updated_text = "".join(lines[:start_line]) + replacement + "".join(lines[end_line:])
            after_content = replacement
        elif edit.selector_type == "text_between":
            start_index, end_index, _, _ = _locate_text_between(original_text, edit.selector_value)
            before_content = original_text[start_index:end_index]
            updated_text = original_text[:start_index] + edit.replacement + original_text[end_index:]
            after_content = edit.replacement
        else:
            raise ValueError(f"Unsupported selector type: {edit.selector_type}")
    except Exception as exc:
        return AppliedSectionChange(
            path=normalized_path,
            selector_type=edit.selector_type,
            selector_value=edit.selector_value,
            applied=False,
            blocked=False,
            error=str(exc),
        )

    if updated_text == original_text:
        return AppliedSectionChange(
            path=normalized_path,
            selector_type=edit.selector_type,
            selector_value=edit.selector_value,
            applied=False,
            blocked=False,
            error="Section edit produced no file change.",
            before_content=before_content,
            after_content=after_content,
        )

    absolute_path.write_text(updated_text, encoding="utf-8")
    return AppliedSectionChange(
        path=normalized_path,
        selector_type=edit.selector_type,
        selector_value=edit.selector_value,
        applied=True,
        blocked=False,
        before_content=before_content,
        after_content=after_content,
    )
