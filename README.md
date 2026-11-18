# PanelCalculator

剑网 3 装备计算的独立 Python 实现。支持 33 个心法的装分、装备属性、精炼、五行石、五彩石、套装、附魔和面板结算，沿用原计算器的 **50 级角色、5 重心法**口径。

支持客户端 **1.6.0.10053**。

运行需要 Python 3.10+，仅使用标准库。表格在创建计算器时加载一次，后续调用复用索引；计算不访问数据库或网络。

## 使用

`examples/role.json` 保存了完整的原始装备响应（含 `status/detail`）。在项目目录执行即可计算这份数据：

```sh
python -m panel_calculator --tables data/tables examples/role.json
```

输出是 UTF-8 JSON；也可以省略文件名，从标准输入读取。失败时返回非零退出码，并将原因写入标准错误。

Python 可以直接传 `detail`，也可以传完整响应：

```python
import json
from pathlib import Path
from panel_calculator import Calculator

calculator = Calculator("data/tables")
response = json.loads(Path("examples/role.json").read_text(encoding="utf-8"))
result = calculator.calculate(response["detail"])
# result = calculator.calculate(response)  # 同样支持完整响应
print(result["score"], result["panel"])
```

计算使用 `detail` 中的 `kungfuName`、原始 `equipList` 和可选的 `enchantState`。角色、区服、头像等其他字段不参与计算。最小输入示例：

```json
{
  "kungfuName": "花间游",
  "equipList": [
    {
      "dwTabType": 6,
      "dwTabIndex": 45860,
      "nItemIndex": 0,
      "nStrengthLevel": 4,
      "dwPermanentEnchantID": 0,
      "dwTemporaryEnchantID": 0,
      "aMountDiamond": [[5, 24447], [5, 24447], [5, 24447]],
      "aColorDiamond": []
    }
  ],
  "enchantState": {"lifePercent": 100}
}
```

`dwTabType` 的 6、7、8 分别对应武器、防具、饰品；`dwTabIndex` 是该表的装备 ID。`examples/request.json` 是仅含计算字段的配装示例。未提供的整数装备字段按原实现取 0，镶嵌数组取空；额外字段忽略。

`enchantState` 可省略。缺少血量条件时，条件附魔保留 `unknown`；无法解析的脚本保留 `unresolved`，不猜测是否生效。`lifePercent` 必须是 0～100 的有限数值。

返回字段为 `kungfu`、`score`、`panel`、`equipList`、`panelList`、`suits`、`enchantEffects`。字段名称、缺失展示值的 `null`、数组顺序及分步舍入与原计算器一致。

同一套装备计算不同心法时，可复用解析结果：

```python
pieces = [calculator.parse_equip(item) for item in response["detail"]["equipList"]]
if any(piece is None for piece in pieces):
    raise ValueError("存在表内未收录的装备")
result = calculator.calculate({"kungfuName": "花间游"}, pieces)
```

`parse_equip()` 遇到未知装备返回 `None`；`calculate()` 自行解析时遇到未知装备抛出 `CalculationError`，可通过 `status/detail` 取得业务错误。缺少表文件、引用或数值格式错误直接抛出异常。复用的 `ItemData` 请视为只读；修改返回结果不会影响下一次计算。

## 表格

只读取下列 10 个文件，保持原目录结构：

| 路径 | 用途 |
| --- | --- |
| `settings/item/Custom_Weapon.tab` | 武器 |
| `settings/item/Custom_Armor.tab` | 防具 |
| `settings/item/Custom_Trinket.tab` | 饰品 |
| `settings/item/Attrib.tab` | 装备、孔位和套装属性 |
| `settings/item/Enchant.tab` | 附魔与五彩石 |
| `settings/item/Other.tab` | 五行石、五彩石物品 |
| `settings/item/Set.tab` | 套装 |
| `ui/scheme/case/Item.txt` | 物品名称、图标和描述 |
| `ui/scheme/case/Skillevent.txt` | 装备特效描述 |
| `ui/scheme/case/equipdb.txt` | 装备展示与来源 |

读取使用 GBK、TAB 分隔，首行是表头；空白行跳过，表头和字段去除首尾空白，引号原样保留。多列使用从零计数的 `extra_下标`，缺列不补值；同 ID 后出现的记录覆盖先出现的记录。

`data/tables/` 是本地数据目录，已加入 `.gitignore`，安装包也不包含游戏原始表。使用者需要自行提供同版本的数据。路径由调用方指定，代码不依赖迁移来源或开发机器的绝对路径。

## 代码与验证

| 文件 | 职责 |
| --- | --- |
| `panel_calculator/calculator.py` | 配装汇总、套装和条件附魔 |
| `panel_calculator/equipment.py` | 单件解析、镶嵌和装备明细 |
| `panel_calculator/panel.py` | 属性通道、主属性转换、面板与百分比 |
| `panel_calculator/config.py` | 心法、系数、映射与已校准附魔 |
| `panel_calculator/tables.py` | 必需表清单及读取 |

```sh
python -m unittest discover -v
```

回归测试自带裁剪后的表格行，无需完整游戏数据。87 组原始样本覆盖 33 个心法、1,122 件装备，并包含 50 项独立客户端字段；另用 `examples/role.json` 与其已计算结果核对完整响应和 `detail` 两种入口。同时检查解析复用、并发隔离、非法参数和命令行。完整数据校验可额外运行：

```powershell
$env:PANEL_CALCULATOR_TABLES = "data/tables"
python -m unittest discover -v
```

迁移来源是搜索服务的装备计算模块，计算公式与系数基线为 `114c6e4`（2026-11-09）。原始计算样本保存在 `tests/fixtures/calculation.json.gz`，包含原表 SHA-256；`role-result.json.gz` 保存角色示例已有的装分、装备明细、面板、套装与附魔结果；`tables.json.gz` 仅裁出这些样本实际引用的原始表格行。

当前范围是静态装备面板；没有迁入配装自动识别、采集、鉴权、交易、HTTP/WS 服务或数据库代码。30 级输入不在原算法范围，客户端对照也只覆盖实际采样的字段。更换游戏版本时应同时核对表格、系数和回归样本。
