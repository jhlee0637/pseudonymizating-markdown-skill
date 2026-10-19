"""Local, literal Markdown pseudonymization. Python 3.10+, no dependencies."""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# 버전의 원본은 git 태그(vMAJOR.MINOR.PATCH)이며, 코드에 번호를 직접 적지 않는다.
def get_version():
    try:  # git 저장소에서 실행한 경우
        described = subprocess.run(
            ["git", "-C", str(Path(__file__).resolve().parent), "describe", "--tags", "--dirty", "--match", "v*"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
        return described.removeprefix("v")
    except (OSError, subprocess.SubprocessError):
        return "unknown (copy without git information)"


class _VersionAction(argparse.Action):
    # --version을 준 때만 git을 조회한다.
    def __init__(self, option_strings, dest=argparse.SUPPRESS, default=argparse.SUPPRESS, help=None):
        super().__init__(option_strings, dest=dest, default=default, nargs=0, help=help)

    def __call__(self, parser, namespace, values, option_string=None):
        print(f"{parser.prog} {get_version()}")
        parser.exit()


class RuleError(ValueError):
    pass


def table_cells(line):
    line = line.strip()
    if not line.startswith("|"):
        raise RuleError("Each table row must start with '|' (Markdown table syntax).")
    cells, cell = [], []
    i = 1
    while i < len(line):
        char = line[i]
        if char == "\\" and i + 1 < len(line) and line[i + 1] in "|\\":
            cell.append(line[i + 1])
            i += 2
            continue
        if char == "|":
            cells.append("".join(cell).strip())
            cell = []
        else:
            cell.append(char)
        i += 1
    if cell or not line.endswith("|"):
        cells.append("".join(cell).strip())
    return cells


def split_aliases(cell):
    # Key 칸의 쉼표와 <br> 줄바꿈은 별칭 구분자이고, 쉼표 문자 자체는 `\,`로 쓴다.
    # 구분자가 연속되거나 끝에 붙어서 생긴 빈 별칭은 무시한다. 별칭 안의 띄어쓰기는 유지한다.
    cell = re.sub(r"<br\s*/?>", ",", cell, flags=re.IGNORECASE)
    parts, buf, i = [], [], 0
    while i < len(cell):
        char = cell[i]
        if char == "\\" and i + 1 < len(cell) and cell[i + 1] == ",":
            buf.append(",")
            i += 2
            continue
        if char == ",":
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(char)
        i += 1
    parts.append("".join(buf).strip())
    return [part for part in parts if part]


def load_rules(markdown):
    # Only inspect tables outside fenced code. Markdown prose is not executable.
    lines = markdown.splitlines()
    table_starts = []
    fence = None
    has_json = False
    for index, line in enumerate(lines):
        if fence:
            if re.fullmatch(r" {0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}\s*", line):
                fence = None
            continue
        opening = re.match(r" {0,3}(`{3,}|~{3,})(.*)$", line)
        if opening:
            fence = opening.group(1)
            has_json |= opening.group(2).strip() == "json"
            continue
        if line.strip().startswith("|"):
            cells = table_cells(line)
            if cells[:2] == ["Key", "Value"]:
                if len(set(cells)) != len(cells) or set(cells[2:]) - {"note", "action"}:
                    raise RuleError("The answer table supports only the columns Key, Value and the optional note, action.")
                table_starts.append((index, cells))
    if has_json:
        if table_starts:
            raise RuleError("An answer table and JSON rules cannot be mixed in one file.")
        return load_json_rules(markdown)
    if len(table_starts) != 1:
        raise RuleError("Exactly one answer table containing Key and Value is required.")
    start, headers = table_starts[0]
    columns = len(headers)
    if start + 1 >= len(lines):
        raise RuleError("The answer table has no separator row.")
    separator = table_cells(lines[start + 1])
    if len(separator) != columns or any(not re.fullmatch(r":?-{3,}:?", cell) for cell in separator):
        raise RuleError("The answer table separator row is invalid.")
    # 오류·경고 메시지에는 행 번호만 쓰고 Key·Value는 쓰지 않는다.
    entries = {}  # Key -> (action, Value, 행). 같은 Key가 다시 나오면 나중 행이 앞의 규칙을 덮어쓴다.
    overrides = {}  # (나중 행, 덮어쓴 앞 행) -> 겹친 Key 수
    for row, line in enumerate(lines[start + 2:], start + 3):
        if not line.strip().startswith("|"):
            break
        cells = table_cells(line)
        if len(cells) != columns:
            raise RuleError(f"The number of columns does not match the header. (row {row})")
        if not any(cells):
            continue  # 모든 칸이 빈 행은 규칙이 아니므로 건너뛴다
        key_cell, value = cells[:2]
        action = (cells[headers.index("action")] or "replace") if "action" in headers else "replace"
        if action not in {"replace", "remove_text", "remove_line"}:
            raise RuleError(f"action must be one of replace, remove_text, remove_line. (row {row})")
        if action == "replace" and not value:
            raise RuleError(f"A replace rule needs a non-empty Value. (row {row})")
        if action != "replace" and value:
            raise RuleError(f"A removal rule must have an empty Value. (row {row})")
        keys = split_aliases(key_cell)
        if not keys:
            raise RuleError(f"Key cannot be empty. (row {row})")
        for key in keys:
            if key in entries:
                pair = (row, entries[key][2])
                overrides[pair] = overrides.get(pair, 0) + 1
            entries[key] = (action, value, row)
    if not entries:
        raise RuleError("The answer table has no rules.")
    # Value 중복: 서로 다른 행이 같은 가명을 쓰면 원문을 구별할 수 없으므로 작업을 중단한다.
    # 한 행의 별칭들이 같은 Value를 쓰는 것은 중복이 아니다.
    value_rows = {}
    for action, value, row in entries.values():
        if action == "replace":
            value_rows.setdefault(value, set()).add(row)
    conflicts = sorted(sorted(rows) for rows in value_rows.values() if len(rows) > 1)
    if conflicts:
        detail = "; ".join("rows " + ", ".join(str(row) for row in rows) for rows in conflicts)
        raise RuleError(
            "Different rows use the same Value. Aborted: fix the answer table and run again. "
            f"({detail})"
        )
    # Key 중복: 경고만 표시하고 나중에 읽은 행의 규칙을 사용한다.
    for (row, previous), count in sorted(overrides.items()):
        where = f"within row {row}" if row == previous else f"row {row} overrides row {previous}"
        print(f"warning: {count} duplicate Key(s); the later rule is used. ({where})", file=sys.stderr)
    mapping = {key: value for key, (action, value, row) in entries.items() if action == "replace"}
    remove_text = [key for key, (action, value, row) in entries.items() if action == "remove_text"]
    remove_lines = [key for key, (action, value, row) in entries.items() if action == "remove_line"]
    return {"replace": mapping, "remove_text": remove_text, "remove_lines_containing": remove_lines}


def load_json_rules(markdown):
    # Require one unambiguous JSON fence; prose outside it is documentation.
    blocks = []
    fence = None
    body = []
    for line in markdown.splitlines():
        if fence is None:
            match = re.fullmatch(r" {0,3}(`{3,}|~{3,})json\s*", line)
            if match:
                fence = match.group(1)
                body = []
        elif re.fullmatch(r" {0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}\s*", line):
            blocks.append("\n".join(body))
            fence = None
        else:
            body.append(line)
    if fence is not None or len(blocks) != 1:
        raise RuleError("The answer file needs exactly one closed json code block.")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise RuleError("Duplicate key in JSON.")
            result[key] = value
        return result

    try:
        rules = json.loads(blocks[0], object_pairs_hook=unique_object)
    except json.JSONDecodeError as exc:
        raise RuleError(f"JSON syntax error: line {exc.lineno}, column {exc.colno} of the block") from None
    allowed = {"replace", "remove_text", "remove_lines_containing"}
    if not isinstance(rules, dict) or not rules or set(rules) - allowed:
        raise RuleError("The rules object may contain only replace, remove_text and remove_lines_containing.")
    mapping = rules.get("replace", {})
    if not isinstance(mapping, dict):
        raise RuleError("replace must be an object of original: pseudonym pairs.")
    for key, value in mapping.items():
        if not key or not isinstance(value, str) or not value:
            raise RuleError("Replacement originals and pseudonyms must be non-empty strings.")
    for field in ("remove_text", "remove_lines_containing"):
        values = rules.get(field, [])
        if not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values):
            raise RuleError(f"{field} must be an array of non-empty strings.")
    if set(mapping) & set(rules.get("remove_text", [])):
        raise RuleError("The same original cannot be both replaced and removed.")
    if any("\n" in v or "\r" in v for v in rules.get("remove_lines_containing", [])):
        raise RuleError("A line-removal condition cannot contain a line break.")
    return rules


def transform(text, rules):
    needles = rules.get("remove_lines_containing", [])
    # A line means LF or CRLF, rather than arbitrary Unicode separators.
    lines = text.splitlines(keepends=True) if not text else re.findall(r"[^\n]*\n|[^\n]+$", text)
    kept = []
    removed = 0
    for line in lines:
        if any(needle in line for needle in needles):
            removed += 1
        else:
            kept.append(line)
    text = "".join(kept)
    replacements = dict(rules.get("replace", {}))
    replacements.update({value: "" for value in rules.get("remove_text", [])})
    count = 0
    if replacements:
        pattern = re.compile("|".join(re.escape(key) for key in sorted(replacements, key=len, reverse=True)))
        text, count = pattern.subn(lambda match: replacements[match.group(0)], text)
    return text, removed, count


def read_utf8(path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return handle.read()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Create pseudonymized Markdown from a source Markdown and an answer (rules) Markdown")
    parser.add_argument("input", type=Path, help="source Markdown (UTF-8)")
    parser.add_argument("answer", type=Path, help="answer (rules) Markdown (UTF-8)")
    parser.add_argument("-o", "--output", type=Path, help="default: <source name>.pseudonymized.md")
    parser.add_argument("--version", action=_VersionAction, help="show the version from git tags")
    args = parser.parse_args(argv)
    output = args.output or args.input.with_name(args.input.stem + ".pseudonymized.md")
    try:
        if output.resolve() in {args.input.resolve(), args.answer.resolve()}:
            raise RuleError("The output path must differ from the source and answer files.")
        rules = load_rules(read_utf8(args.answer))
        result, removed, changed = transform(read_utf8(args.input), rules)
        # Exclusive creation also protects existing outputs and hard links.
        with output.open("x", encoding="utf-8", newline="") as handle:
            handle.write(result)
    except FileExistsError:
        print("error: the output file already exists. Choose another output name.", file=sys.stderr)
        return 1
    except UnicodeError:
        print("error: input files must be saved as UTF-8.", file=sys.stderr)
        return 1
    except RuleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError:
        print("error: check the file paths, parent folders, permissions and disk space.", file=sys.stderr)
        return 1
    print(f"Done: {removed} line(s) removed, {changed} replacement/removal(s) applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
