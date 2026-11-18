"""python -m panel_calculator --tables data/tables examples/role.json"""

import argparse
import json
import sys
from pathlib import Path

from . import CalculationError, Calculator


def main() -> int:
    parser = argparse.ArgumentParser(description="计算剑网 3 装备装分与面板")
    parser.add_argument("input", nargs="?", default="-", help="UTF-8 JSON 文件；- 表示标准输入")
    parser.add_argument("--tables", type=Path, default=Path("data/tables"), help="游戏表根目录")
    args = parser.parse_args()
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        if args.input == "-":
            request = json.load(sys.stdin)
        else:
            request = json.loads(Path(args.input).read_text(encoding="utf-8"))
        result = Calculator(args.tables).calculate(request)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    except CalculationError as error:
        print(f"{error.status}: {error.detail}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
