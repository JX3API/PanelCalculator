"""单件装备、附魔、镶嵌解析与展示。"""

import re
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from math import floor

from . import config as cfg


class CalculationError(ValueError):
    """保留原计算器的业务状态码与错误说明。"""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def required_row(index: dict, key):
    try:
        return index[key]
    except KeyError:
        raise ValueError(f"game table reference {key} not found") from None


def number(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def integer(value: str) -> int:
    return int(float(value)) if value else 0


def round_score(value: float) -> int:
    # Python round 的银行家舍入与原公式不同。
    return floor(value + 0.5)


def strip_tags(value: str) -> str:
    text = "".join(re.findall(r'text="(.*?)"', value, re.S))
    return text.replace("\\\\", "").replace(r"\n", "\n").replace(r"\t", "\t").strip()


def normalize_item(item: dict) -> dict:
    if not isinstance(item, dict):
        raise CalculationError(400, "equipList 中的装备必须是对象")
    result = {}
    for key in (
        "dwTabType", "dwTabIndex", "nItemIndex", "nStrengthLevel",
        "dwPermanentEnchantID", "dwTemporaryEnchantID",
    ):
        value = item.get(key)
        if value is None:
            value = 0
        if type(value) is not int:
            raise CalculationError(400, f"{key}必须为整数")
        result[key] = value
    for key in ("aMountDiamond", "aColorDiamond"):
        value = item.get(key)
        if value is None:
            value = []
        if not isinstance(value, list):
            raise CalculationError(400, f"{key}必须为数组")
        pairs = value if key == "aMountDiamond" else [value]
        for pair in pairs:
            if pair is not None and (
                not isinstance(pair, list)
                or len(pair) not in (0, 2)
                or any(type(v) is not int for v in pair)
            ):
                raise CalculationError(400, f"{key}中的石头必须是空数组或两个整数")
        if key == "aMountDiamond":
            result[key] = [list(pair or []) for pair in pairs]
        else:
            result[key] = list(value)
    return result


@dataclass
class ItemData:
    """可供不同心法复用的解析结果；复用期间请勿修改。"""

    item: dict
    row: dict
    view: dict
    raw_score: float
    strengthen_coef: float
    base: dict = field(default_factory=dict)
    magic: dict = field(default_factory=dict)
    min_attrs: dict = field(default_factory=dict)
    max_attrs: dict = field(default_factory=dict)
    mount_attrs: dict = field(default_factory=dict)
    magic_list: list = field(default_factory=list)
    has_skill_event: bool = False
    min_enchant: dict = field(default_factory=dict)
    max_enchant: dict = field(default_factory=dict)
    mounts: list = field(default_factory=list)
    color: dict = field(default_factory=dict)
    color_conditions: list = field(default_factory=list)
    stone_count: int = 0
    stone_intensity: int = 0
    cangjian_detail: int | None = None


def script_profile(enchant_id: int, row: dict):
    profile = cfg.SCRIPT_ENCHANT_EFFECTS.get(enchant_id)
    path = row.get("Attribute1Value1", "").replace("\\", "/").removeprefix("scripts/")
    if profile and row.get("Attribute1ID") == "atExecuteScript" and path == profile["script"]:
        return profile
    return None


def enchant_attrs(enchant_id: int, row: dict) -> dict:
    attrs = defaultdict(float)
    for i in range(1, 5):
        name = row.get(f"Attribute{i}ID", "")
        value = number(row.get(f"Attribute{i}Value1", ""))
        if name not in ("", "atInvalid", "atExecuteScript") and value is not None:
            attrs[name] += value
    profile = script_profile(enchant_id, row)
    if profile:
        for name, value in profile.get("passive_attrs", {}).items():
            attrs[name] += value
    return dict(attrs)


def parse_enchant(tables: dict, enchant_id: int) -> tuple[dict, dict]:
    if enchant_id == 0:
        return {}, {}
    row = required_row(tables["enchants"], enchant_id)
    return {
        "itemId": row.get("ID", ""), "itemName": row.get("Name", ""), "itemType": row.get("UIID", ""),
        "attribute1Name": row.get("AttriName", ""), "attribute1ID": row.get("Attribute1ID", ""),
        "attribute1Value1": row.get("Attribute1Value1", ""), "attribute1Value2": row.get("Attribute1Value2", ""),
        "itemScore": row.get("Score", ""), "destItemSubType": row.get("DestItemSubType", ""),
    }, enchant_attrs(enchant_id, row)


def parse_equip(tables: dict, item: dict) -> ItemData | None:
    if not tables["equips"]:
        raise CalculationError(503, "服务未就绪：装备表格未加载")
    item = normalize_item(item)
    key = f"{item['dwTabType']}_{item['dwTabIndex']}"
    row = tables["equips"].get(key)
    if row is None:
        return None
    view = row | tables["equip_db"].get(key, {}) | tables["items"].get(row.get("UiID", ""), {})
    strength = item["nStrengthLevel"]
    if not 0 <= strength < len(cfg.STRENGTHEN_BONUS_COEF):
        raise CalculationError(400, f"不支持的精炼等级：{strength}")
    coefficient = cfg.STRENGTHEN_BONUS_COEF[strength]
    quality = row.get("Quality", "")
    if quality not in cfg.SCORE_QUALITY_COEF:
        raise ValueError(f"equipment quality {quality!r} not found")
    subtype = integer(row.get("SubType", ""))
    slot = cfg.SCORE_SLOT_COEF[subtype] if 0 <= subtype < len(cfg.SCORE_SLOT_COEF) else 1
    score = round_score(integer(row.get("Level", "")) * cfg.SCORE_QUALITY_COEF[quality] * slot)
    score += round_score(score * coefficient)
    raw = ItemData(item, row, view, score, coefficient)
    base, magic = defaultdict(float), defaultdict(float)
    for i in range(1, 7):
        name = row.get(f"Base{i}Type", "")
        value = number(row.get(f"Base{i}Min", ""))
        if name not in ("", "atInvalid") and value is not None:
            base[name] += value
    for i in range(1, 17):
        attr_id = row.get(f"Magic{i}Type", "")
        if attr_id in ("", "0"):
            continue
        attr = required_row(tables["attribs"], attr_id)
        name = attr.get("ModifyType", "")
        value = number(attr.get("Param1Min", ""))
        if value is not None:
            magic[name] += value + round_score(value * coefficient)
        description = None
        if name == "atSkillEventHandler":
            raw.has_skill_event = True
            event = tables["skill_events"].get(attr.get("Param1Min", ""))
            if event is not None:
                description = strip_tags(event.get("Desc", ""))
        if name in cfg.ATTRIBUTES_SHORT:
            raw.magic_list.append({
                "typeName": name, "itemName": cfg.ATTRIBUTES_SHORT[name],
                "itemValue": {"Param1Min": integer(attr.get("Param1Min", "")),
                              "Param1Max": integer(attr.get("Param1Max", ""))},
                "itemDesc": description,
            })
    raw.base, raw.magic = dict(base), dict(magic)
    raw.min_enchant, raw.min_attrs = parse_enchant(tables, item["dwPermanentEnchantID"])
    raw.max_enchant, raw.max_attrs = parse_enchant(tables, item["dwTemporaryEnchantID"])
    for enchant in (raw.min_enchant, raw.max_enchant):
        raw.raw_score += integer(enchant.get("itemScore", ""))
    parse_stones(tables, raw)
    parse_color(tables, raw)
    if item["dwTabType"] == 6 and row.get("SubType") == "0":
        detail = row.get("DetailType", "")
        raw.cangjian_detail = integer(detail) if detail else -1
    return raw


def parse_stones(tables: dict, raw: ItemData):
    attrs, score = defaultdict(float), 0.0
    for i, stone in enumerate(raw.item["aMountDiamond"], 1):
        if not stone:
            raw.mounts.append({})
            continue
        row = required_row(tables["others"], stone[1])
        view = required_row(tables["items"], row.get("UiID", ""))
        level = integer(row.get("DetailType", ""))
        if level > 0:
            raw.stone_count += 1
            raw.stone_intensity += level
        if level > 6:
            score += (level * 0.65 - 3.2) * 1.3 * cfg.FIVE_STONE_SCORE_BASE
        elif level > 0:
            score += level * 1.3 * 0.15 * cfg.FIVE_STONE_SCORE_BASE
        attr = required_row(tables["attribs"], raw.row.get(f"DiamondAttributeID{i}", ""))
        attr_id = attr.get("ID", "")
        if attr_id not in cfg.DIAMOND_LEVEL_VALUES:
            raise CalculationError(503, f"孔位属性 {attr_id} 尚未校准")
        values = cfg.DIAMOND_LEVEL_VALUES[attr_id]
        if not 0 <= level < len(values):
            raise CalculationError(400, f"不支持的五行石等级：{level}")
        attrs[attr.get("ModifyType", "")] += values[level]
        bind = row.get("BindType", "")
        raw.mounts.append({
            "itemId": int(row["ID"]), "itemName": row.get("Name", ""),
            "iconId": int(view["IconID"]), "itemQuality": int(row["Quality"]),
            "bindType": int(bind) if bind else None, "itemDesc": strip_tags(view.get("Desc", "")),
        })
    raw.mount_attrs = dict(attrs)
    raw.raw_score += round_score(score)


def parse_color(tables: dict, raw: ItemData):
    raw.color = {"itemScore": 0}
    stone = raw.item["aColorDiamond"]
    if not stone:
        return
    row = required_row(tables["others"], stone[1])
    enchant_id = int(row["EnchantID"])
    enchant = required_row(tables["enchants"], enchant_id)
    view = tables["items"].get(enchant.get("UIID", ""), {})
    score = round_score(integer(row.get("DetailType", "")) * cfg.COLOR_STONE_SCORE_PER_LEVEL)
    raw.raw_score += score
    raw.color = {
        "itemScore": score, "itemId": stone[1], "itemName": row.get("Name", ""),
        "itemQuality": row.get("Quality", ""), "iconId": view.get("IconID"),
        "itemAttr": enchant_attrs(enchant_id, enchant),
    }
    for i in range(1, 5):
        name = enchant.get(f"Attribute{i}ID", "")
        if name:
            raw.color_conditions.append((
                name, int(enchant[f"Attribute{i}Value1"]),
                integer(enchant.get(f"DiamondCount{i}", "")),
                integer(enchant.get(f"DiamondIntensity{i}", "")),
            ))


def format_piece(raw: ItemData, subtotal: dict) -> dict:
    item, row, view = raw.item, raw.row, raw.view
    label = None
    if item["nItemIndex"] in (0, 1) and item["nStrengthLevel"] == 8:
        label = "橙武"
    elif raw.has_skill_event or row.get("SkillID", ""):
        label = "特效"
    elif row.get("BelongSchool") == "精简":
        label = "精简"
    desc = []
    kinds = view.get("GetType", "").split(",")
    groups = re.split(r"}\s*,\s*{", view.get("Get_Desc", "").strip())
    for kind, group in zip(kinds, groups):
        text = re.sub(r"[{}\[\]]", "", group)
        if text and text.strip() != "()":
            desc.append(f"{kind}({text})")
    result = {
        "tabId": item["dwTabType"], "tabIndex": item["dwTabIndex"],
        "itemName": view.get("Name", ""), "itemIndex": item["nItemIndex"],
        "iconId": integer(view.get("IconID", "")), "magicType": view.get("MagicType"),
        "itemAttrib": [
            {"name": cfg.PANEL_FIELD_LABELS.get(key, key), "value": subtotal[key]}
            for key in cfg.ITEM_ATTR_FIELDS if subtotal.get(key)
        ],
        "itemMagic": deepcopy(raw.magic_list), "needLevel": integer(view.get("Require1Value", "")),
        "itemLevel": integer(view.get("Level", "")), "itemQuality": integer(view.get("Quality", "")),
        "itemSchool": view.get("BelongSchool"), "schoolName": row.get("BelongSchool"),
        "itemKind": view.get("MagicKind"), "belongSchool": view.get("BelongSchool"),
        "mountDiamond": [stone.copy() for stone in raw.mounts], "setId": view.get("SetID", ""),
        "minEnchant": raw.min_enchant.copy(), "maxEnchant": raw.max_enchant.copy(),
        "strengthLevel": item["nStrengthLevel"], "maxStrengthLevel": integer(view.get("MaxStrengthLevel", "")),
        "itemSource": view.get("GetType"), "itemType": view.get("PVE_PVP"),
        "itemPlus": label, "itemDesc": desc,
    }
    if item["nItemIndex"] in (0, 1):
        result["colorDiamond"] = deepcopy(raw.color)
    return result
