#!/usr/bin/env python3
"""List all quantum-lego examples with their difficulty and API functions.

Scans the examples directory, extracts metadata from each script's module
docstring, and prints a formatted table.

Usage:
    python examples/list_examples.py
    python examples/list_examples.py --category 07
    python examples/list_examples.py --difficulty beginner
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

EXAMPLES_DIR = Path(__file__).resolve().parent

# Category display names
CATEGORY_NAMES = {
    '01': 'Getting Started',
    '02': 'DOS',
    '03': 'Batch',
    '04': 'Sequential',
    '05': 'Convergence',
    '06': 'Surface',
    '07': 'Advanced VASP',
    '08': 'AIMD',
    '09': 'Other Codes',
    '10': 'Utilities',
    '11': 'NEB',
    '12': 'Dimer',
}

DIFFICULTY_ORDER = {'beginner': 0, 'intermediate': 1, 'advanced': 2, '—': 3}

COL_WIDTHS = {
    'category': 18,
    'file': 46,
    'difficulty': 14,
    'api': 50,
}


def _extract_docstring_metadata(path: Path) -> dict[str, str]:
    """Extract ``API functions`` and ``Difficulty`` lines from a module docstring.

    Args:
        path: Path to the Python source file.

    Returns:
        Dict with keys ``api`` and ``difficulty`` (both ``str``).
    """
    try:
        source = path.read_text(encoding='utf-8')
        tree = ast.parse(source)
    except (SyntaxError, OSError):
        return {'api': '—', 'difficulty': '—'}

    docstring = ast.get_docstring(tree) or ''
    api = '—'
    difficulty = '—'
    for line in docstring.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith('api functions:'):
            api = stripped.split(':', 1)[1].strip()
        elif stripped.lower().startswith('difficulty:'):
            difficulty = stripped.split(':', 1)[1].strip()
    return {'api': api or '—', 'difficulty': difficulty or '—'}


def _collect_examples(
    category_filter: str | None = None,
    difficulty_filter: str | None = None,
) -> list[dict[str, str]]:
    """Walk examples dir and collect per-file metadata.

    Args:
        category_filter: If set, restrict to categories whose number prefix
            starts with this string (e.g. ``'07'``).
        difficulty_filter: If set, restrict to this difficulty level.

    Returns:
        List of dicts with keys ``category``, ``file``, ``api``, ``difficulty``.
    """
    rows: list[dict[str, str]] = []
    for subdir in sorted(EXAMPLES_DIR.iterdir()):
        if not subdir.is_dir():
            continue
        num = subdir.name[:2]
        if not num.isdigit():
            continue
        if category_filter and not subdir.name.startswith(category_filter):
            continue
        cat_label = f"{subdir.name[:2]} {CATEGORY_NAMES.get(num, subdir.name[3:])}"
        for py_file in sorted(subdir.rglob('*.py')):
            if py_file.name.startswith('__'):
                continue
            meta = _extract_docstring_metadata(py_file)
            if difficulty_filter and meta['difficulty'].lower() != difficulty_filter.lower():
                continue
            rel = py_file.relative_to(EXAMPLES_DIR)
            rows.append({
                'category': cat_label,
                'file': str(rel),
                'difficulty': meta['difficulty'],
                'api': meta['api'],
            })
    return rows


def _print_table(rows: list[dict[str, str]]) -> None:
    """Print *rows* as a plain-text fixed-width table.

    Args:
        rows: List of row dicts with keys matching ``COL_WIDTHS``.
    """
    w = COL_WIDTHS

    def _row(category: str, file: str, difficulty: str, api: str) -> str:
        return (
            f"  {category:<{w['category']}}  "
            f"{file:<{w['file']}}  "
            f"{difficulty:<{w['difficulty']}}  "
            f"{api}"
        )

    sep = '  ' + '-' * (w['category'] + w['file'] + w['difficulty'] + w['api'] + 8)
    header = _row('Category', 'File', 'Difficulty', 'API functions')
    print(sep)
    print(header)
    print(sep)

    last_cat = ''
    for r in rows:
        cat = r['category'] if r['category'] != last_cat else ''
        last_cat = r['category']
        print(_row(cat, r['file'], r['difficulty'], r['api']))

    print(sep)
    print(f"  {len(rows)} example(s) listed.")


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Command-line arguments (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code.
    """
    parser = argparse.ArgumentParser(
        description='List quantum-lego examples with difficulty and API functions.',
    )
    parser.add_argument(
        '--category', '-c',
        metavar='NUM',
        help='Show only examples in this category number (e.g. 07).',
    )
    parser.add_argument(
        '--difficulty', '-d',
        metavar='LEVEL',
        choices=['beginner', 'intermediate', 'advanced'],
        help='Filter by difficulty level.',
    )
    args = parser.parse_args(argv)

    rows = _collect_examples(
        category_filter=args.category,
        difficulty_filter=args.difficulty,
    )

    if not rows:
        print('No examples matched the given filters.')
        return 1

    _print_table(rows)
    return 0


if __name__ == '__main__':
    sys.exit(main())
