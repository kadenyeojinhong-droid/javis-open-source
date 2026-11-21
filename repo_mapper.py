"""repo_mapper.py

Traverse Python files in repository using standard library `ast`
and generate REPO_MAP.txt with file paths and signatures of
top-level functions, classes, and methods.
"""

import ast
import os
import sys

IGNORED_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".ai_bus"}


def find_python_files(root_dir: str = ".") -> list[str]:
    """Find all .py files under root_dir ignoring specified directories."""
    py_files = []
    for root, dirs, files in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for f in files:
            if f.endswith(".py"):
                rel_path = os.path.relpath(os.path.join(root, f), root_dir)
                py_files.append(rel_path.replace("\\", "/"))
    py_files.sort()
    return py_files


def format_args(args_node: ast.arguments) -> str:
    """Format AST arguments node into parameter string."""
    try:
        return ast.unparse(args_node)
    except Exception:
        parts = []
        for a in getattr(args_node, "posonlyargs", []):
            parts.append(a.arg)
        if getattr(args_node, "posonlyargs", []):
            parts.append("/")
        for a in args_node.args:
            parts.append(a.arg)
        if args_node.vararg:
            parts.append(f"*{args_node.vararg.arg}")
        for a in args_node.kwonlyargs:
            parts.append(a.arg)
        if args_node.kwarg:
            parts.append(f"**{args_node.kwarg.arg}")
        return ", ".join(parts)


def format_function_def(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Format function or async function definition into a signature string."""
    prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
    args_str = format_args(node.args)
    ret_str = ""
    if node.returns:
        try:
            ret_str = f" -> {ast.unparse(node.returns)}"
        except Exception:
            pass
    return f"{prefix}{node.name}({args_str}){ret_str}"


def format_class_def(node: ast.ClassDef) -> str:
    """Format class definition into a signature string."""
    bases_str = ""
    if node.bases:
        try:
            bases_str = f"({', '.join(ast.unparse(b) for b in node.bases)})"
        except Exception:
            bases_str = f"({', '.join(getattr(b, 'id', str(b)) for b in node.bases)})"
    return f"class {node.name}{bases_str}:"


def parse_file_signatures(filepath: str) -> list[str]:
    """Parse top-level functions, classes, and their methods from a python file."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            code = f.read()
        tree = ast.parse(code, filename=filepath)
    except Exception as e:
        return [f"  # Error parsing {filepath}: {e}"]

    lines = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            lines.append(f"  {format_function_def(node)}")
        elif isinstance(node, ast.ClassDef):
            lines.append(f"  {format_class_def(node)}")
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    lines.append(f"    {format_function_def(child)}")
    return lines


def generate_repo_map(root_dir: str = ".", output_file: str = "REPO_MAP.txt") -> str:
    """Scan root_dir, format signatures, and write to output_file."""
    py_files = find_python_files(root_dir)
    result_lines = []
    for rel_path in py_files:
        full_path = os.path.join(root_dir, rel_path)
        sigs = parse_file_signatures(full_path)
        result_lines.append(rel_path)
        result_lines.extend(sigs)
        result_lines.append("")

    content = "\n".join(result_lines).rstrip() + "\n"
    if output_file:
        out_dir = os.path.dirname(output_file)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(content)
    return content


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    out = sys.argv[2] if len(sys.argv) > 2 else "REPO_MAP.txt"
    generate_repo_map(root, out)
    print(f"Generated {out}")


if __name__ == "__main__":
    main()
