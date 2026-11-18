import gzip
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

from panel_calculator import CalculationError, Calculator
from panel_calculator.tables import TABLE_FILES, read_table


FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[1]


def fixture(name):
    return json.loads(gzip.decompress((FIXTURES / name).read_bytes()))


class CalculatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference = fixture("calculation.json.gz")
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.directory = Path(cls.temp.name)
        for filename, text in fixture("tables.json.gz").items():
            path = cls.directory / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("gbk"))
        cls.calculator = Calculator(cls.directory)

    def test_reference(self):
        cases = self.reference["cases"]
        self.assertEqual(len(cases), 87)
        self.assertEqual(len({case["input"]["kungfuName"] for case in cases}), 33)
        self.assertEqual(sum(len(case["input"]["equipList"]) for case in cases), 1122)
        self.assertEqual(sum(len(case["client"]) for case in cases), 50)
        for case in cases:
            with self.subTest(case=case["name"]):
                request = deepcopy(case["input"])
                pieces = [self.calculator.parse_equip(item) for item in request["equipList"]]
                parsed = [{
                    "item_key": f"{raw.item['dwTabType']}_{raw.item['dwTabIndex']}",
                    "raw_score": raw.raw_score, "strengthen_coef": raw.strengthen_coef,
                    "base_attrs": raw.base, "magic_attrs": raw.magic,
                    "min_enchant_attrs": raw.min_attrs, "max_enchant_attrs": raw.max_attrs,
                    "mount_attrs": raw.mount_attrs, "color_attrs": raw.color.get("itemAttr", {}),
                    "stone_count": raw.stone_count, "stone_intensity": raw.stone_intensity,
                    "cangjian_detail": raw.cangjian_detail,
                } for raw in pieces]
                self.assertEqual(parsed, case["parsed"])
                for reusable in (None, pieces):
                    result = self.calculator.calculate(request, reusable)
                    self.assertEqual(result, case["expected"])
                    for name, value in case["client"].items():
                        self.assertEqual(result["panel"][name], value)
                self.assertEqual(request, case["input"])

    def test_role_response_and_detail(self):
        response = json.loads((ROOT / "examples/role.json").read_text(encoding="utf-8"))
        before = deepcopy(response)
        expected = fixture("role-result.json.gz")
        result = self.calculator.calculate(response)
        self.assertEqual(result, self.calculator.calculate(response["detail"]))
        self.assertEqual({key: result[key] for key in expected}, expected)
        self.assertEqual(response, before)

    def test_parallel_calls_and_result_isolation(self):
        cases = self.reference["cases"]
        parsed = [[self.calculator.parse_equip(item) for item in c["input"]["equipList"]] for c in cases]
        before = deepcopy(parsed)

        def calculate(index):
            case, pieces = cases[index], parsed[index]
            result = self.calculator.calculate(case["input"], pieces)
            self.assertEqual(result, case["expected"])
            result["panel"].clear()
            for item in result["equipList"]:
                item["minEnchant"].clear()
                item["itemMagic"].clear()
                for stone in item["mountDiamond"]:
                    stone.clear()
                if "colorDiamond" in item:
                    item["colorDiamond"].get("itemAttr", {}).clear()
            for effect in result["enchantEffects"]:
                effect["attributes"].clear()
            self.assertEqual(self.calculator.calculate(case["input"], pieces), case["expected"])

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(calculate, list(range(len(cases))) * 2))
        self.assertEqual(parsed, before)

    def test_errors(self):
        request = self.reference["cases"][0]["input"]
        unknown = {"dwTabType": 6, "dwTabIndex": -1}
        self.assertIsNone(self.calculator.parse_equip(unknown))
        bad_requests = [
            ([], 400), ({"kungfuName": "unknown"}, 400),
            ({**request, "equipList": [unknown]}, 503),
            ({**request, "equipList": {}}, 400),
            ({**request, "enchantState": []}, 400),
            ({"status": 200, "detail": None}, 400),
            ({"status": 200, "detail": []}, 400),
        ]
        for value in (-1, 101, float("nan"), float("inf"), "75", True):
            bad_requests.append(({**request, "enchantState": {"lifePercent": value}}, 400))
        for invalid, status in bad_requests:
            with self.subTest(request=invalid):
                with self.assertRaises(CalculationError) as caught:
                    self.calculator.calculate(invalid)
                self.assertEqual(caught.exception.status, status)
        item = request["equipList"][0]
        for change in (
            {"nStrengthLevel": -1}, {"nStrengthLevel": 9}, {"nStrengthLevel": True},
            {"dwTabIndex": "1"}, {"aMountDiamond": [[5]]},
            {"aMountDiamond": [1]}, {"aColorDiamond": [5, "1"]},
        ):
            with self.subTest(change=change), self.assertRaises(CalculationError):
                self.calculator.parse_equip(item | change)
        with self.assertRaisesRegex(ValueError, "reference -1 not found"):
            self.calculator.parse_equip(item | {"dwPermanentEnchantID": -1})

    def test_kungfu_suffix_and_missing_state(self):
        case = self.reference["cases"][0]
        for suffix in ("悟", "·悟", "_悟", "(悟)", "（悟）"):
            request = case["input"] | {"kungfuName": case["input"]["kungfuName"] + suffix}
            self.assertEqual(self.calculator.calculate(request), case["expected"])
        request = case["input"] | {"enchantState": {"lifePercent": None}}
        self.assertEqual(self.calculator.calculate(request), case["expected"])

    def test_only_required_tables(self):
        self.assertEqual(set(TABLE_FILES), set(self.reference["tables"]))
        self.assertEqual(len(TABLE_FILES), 10)
        files = {p.relative_to(self.directory).as_posix()
                 for p in self.directory.rglob("*") if p.is_file()}
        self.assertEqual(files, set(TABLE_FILES))

    def test_cli(self):
        case = self.reference["cases"][0]
        command = [sys.executable, "-m", "panel_calculator", "--tables", str(self.directory)]
        result = subprocess.run(
            command, input=json.dumps(case["input"]), capture_output=True,
            text=True, encoding="utf-8", cwd=ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), case["expected"])
        result = subprocess.run(
            command + [str(ROOT / "examples/role.json")], capture_output=True,
            text=True, encoding="utf-8", cwd=self.directory,
            env={**os.environ, "PYTHONPATH": str(ROOT)},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = fixture("role-result.json.gz")
        actual = json.loads(result.stdout)
        self.assertEqual({key: actual[key] for key in expected}, expected)
        for data in ("{", '{"kungfuName":"unknown"}'):
            result = subprocess.run(
                command, input=data, capture_output=True, text=True, encoding="utf-8", cwd=ROOT,
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, "")
            self.assertTrue(result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    @unittest.skipUnless(os.environ.get("PANEL_CALCULATOR_TABLES"), "设置 PANEL_CALCULATOR_TABLES 可验证完整游戏表")
    def test_full_tables(self):
        directory = Path(os.environ["PANEL_CALCULATOR_TABLES"])
        for filename, digest in self.reference["tables"].items():
            self.assertEqual(hashlib.sha256((directory / filename).read_bytes()).hexdigest(), digest, filename)
        calculator = Calculator(directory)
        for case in self.reference["cases"]:
            with self.subTest(case=case["name"]):
                self.assertEqual(calculator.calculate(case["input"]), case["expected"])
        response = json.loads((ROOT / "examples/role.json").read_text(encoding="utf-8"))
        expected = fixture("role-result.json.gz")
        actual = calculator.calculate(response)
        self.assertEqual({key: actual[key] for key in expected}, expected)


class TableTests(unittest.TestCase):
    def test_text_rules(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sample.tab"
            path.write_bytes(' ID \t 名称 \r\n1\t "带引号" \t 多余 \r\n\n2\r3\t\r\n'.encode("gbk"))
            self.assertEqual(list(read_table(path)), [
                {"ID": "1", "名称": '"带引号"', "extra_2": "多余"},
                {"ID": "2"}, {"ID": "3", "名称": ""},
            ])
            path.write_bytes(b"ID\n\xff\n")
            with self.assertRaises(UnicodeDecodeError):
                list(read_table(path))

    def test_missing_and_empty_tables(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            with self.assertRaises(FileNotFoundError):
                Calculator(directory)
            for filename in TABLE_FILES:
                path = directory / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("ID\n", encoding="gbk")
            calculator = Calculator(directory)
            with self.assertRaises(CalculationError) as caught:
                calculator.calculate({"kungfuName": "花间游"})
            self.assertEqual(caught.exception.status, 503)


if __name__ == "__main__":
    unittest.main()
