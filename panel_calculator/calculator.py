"""独立装备计算入口，不访问网络或数据库。"""

import re
from collections import defaultdict
from pathlib import Path

from . import config as cfg
from .equipment import (
    CalculationError, ItemData, format_piece, integer, number, parse_equip,
    required_row, round_score, script_profile,
)
from .panel import add_attr, attribute_rules, format_panel, settle_panel
from .tables import load_tables


class Calculator:
    """初始化时加载所需表格；后续调用复用索引，各次计算互相独立。"""

    def __init__(self, directory: str | Path):
        self._tables = load_tables(directory)

    def parse_equip(self, item: dict) -> ItemData | None:
        """解析单件装备；未知装备返回 None，已知装备缺少引用时报错。"""
        return parse_equip(self._tables, item)

    def calculate(self, request: dict, pieces: list[ItemData] | None = None) -> dict:
        """接收 detail 或完整响应；pieces 可复用单件解析结果。"""
        if not self._tables["equips"]:
            raise CalculationError(503, "服务未就绪：装备表格未加载")
        if isinstance(request, dict):
            request = request.get("detail", request)
        if not isinstance(request, dict):
            raise CalculationError(400, "计算输入必须是对象")
        name = request.get("kungfuName")
        if name is None:
            name = ""
        if not isinstance(name, str):
            raise CalculationError(400, "kungfuName必须为字符串")
        name = re.sub(r"[·_(（]?悟[)）]?$", "", name)
        if name not in cfg.KUNGFU_TABLE:
            raise CalculationError(400, "不支持的心法：" + name)
        kungfu = cfg.KUNGFU_TABLE[name]
        if pieces is None:
            equips = request.get("equipList")
            if equips is None:
                equips = []
            if not isinstance(equips, list):
                raise CalculationError(400, "equipList必须为数组")
            pieces = []
            for item in equips:
                raw = self.parse_equip(item)
                if raw is None:
                    key = f"{item.get('dwTabType') or 0}_{item.get('dwTabIndex') or 0}"
                    raise CalculationError(503, f"装备表未收录：{key}")
                pieces.append(raw)
        state = request.get("enchantState")
        if state is not None and not isinstance(state, dict):
            raise CalculationError(400, "enchantState必须是对象")
        life = state.get("lifePercent") if state else None
        if life is not None and (type(life) not in (int, float) or not 0 <= life <= 100):
            raise CalculationError(400, "lifePercent必须为0至100的数值")

        rules = attribute_rules(kungfu)
        weapon = kungfu.get("cangjian_weapon", 0)
        count = intensity = 0
        for raw in pieces:
            active = raw.item["nItemIndex"] != 1
            if weapon:
                active = raw.cangjian_detail is None or raw.cangjian_detail == weapon
            if active:
                count += raw.stone_count
                intensity += raw.stone_intensity
        whole = defaultdict(float)
        suits, equip_list, effects = {}, [], []
        score = 0.0
        for raw in pieces:
            colors = defaultdict(float)
            for attr, value, required_count, required_intensity in raw.color_conditions:
                if required_count <= count and required_intensity <= intensity:
                    colors[attr] += value
            subtotal = defaultdict(float)
            for source in (raw.base, raw.magic, raw.min_attrs, raw.max_attrs, raw.mount_attrs, colors):
                for attr, value in source.items():
                    add_attr(subtotal, attr, value, rules)
            # 条件附魔不影响原有的装分有效性判断。
            piece_score = round_score(raw.raw_score) if any(subtotal.values()) else 0
            piece_effects = self._enchant_effects(raw, life, subtotal, rules)
            equip_list.append(format_piece(raw, subtotal))
            if not weapon and raw.item["nItemIndex"] == 1:
                continue
            if weapon and raw.cangjian_detail is not None:
                score += piece_score / 2
                if raw.cangjian_detail != weapon:
                    continue
            else:
                score += piece_score
            for field, value in subtotal.items():
                whole[field] += value
            effects.extend(piece_effects)
            set_id = raw.row.get("SetID", "")
            if set_id not in ("", "0"):
                suits[set_id] = suits.get(set_id, 0) + 1
        suit_list = self._suits(suits, rules, kungfu["code"], whole)
        for field, value in kungfu["base_attrs"].items():
            if field != "DECRITICAL_RATE":
                whole["THERAPY_POWER" if field == "BASE_THERAPY" else field] += value
        for field, value in cfg.BASE_STATS.items():
            whole[field] += value
        panel = settle_panel(whole, kungfu)
        return {
            "kungfu": {"name": name, "type": kungfu["type"], "main_attr": kungfu["main_attr"]},
            "score": round_score(score), "panel": panel, "equipList": equip_list,
            "panelList": format_panel(panel), "suits": suit_list, "enchantEffects": effects,
        }

    def _enchant_effects(self, raw: ItemData, life: float | None, panel: dict, rules: dict) -> list:
        effects = []
        for source in ("dwPermanentEnchantID", "dwTemporaryEnchantID"):
            enchant_id = raw.item[source]
            if not enchant_id:
                continue
            row = required_row(self._tables["enchants"], enchant_id)
            if not any(row.get(f"Attribute{i}ID") in cfg.SPECIAL_EFFECT_ATTRS for i in range(1, 5)):
                continue
            profile = script_profile(enchant_id, row)
            if profile is None:
                effect = {"status": "unresolved", "active": None, "attributes": {}}
            elif "passive_attrs" in profile:
                extra = profile.get("non_panel_attrs")
                effect = {"status": "passive", "active": True,
                          "attributes": profile["passive_attrs"].copy(),
                          "nonPanelAttributes": extra.copy() if extra is not None else None}
            else:
                threshold = profile["min_life_percent"]
                active = None if life is None else life >= threshold
                status = "unknown"
                if active is not None:
                    status = "active" if active else "inactive"
                effect = {
                    "status": status,
                    "active": active, "condition": {"lifePercentAtLeast": threshold},
                    "attributes": profile["conditional_attrs"].copy(),
                }
                if active:
                    for attr, value in profile["conditional_attrs"].items():
                        add_attr(panel, attr, value, rules)
            effect.update(itemIndex=raw.item["nItemIndex"], enchantId=enchant_id,
                          name=row.get("Name", ""), source=source)
            effects.append(effect)
        return effects

    def _suits(self, counts: dict, rules: dict, code: str, whole: dict) -> list:
        suits = []
        for set_id, count in counts.items():
            if count < 2:
                continue
            row = required_row(self._tables["sets"], set_id)
            mask = integer(row.get("SchoolMask", ""))
            if mask and mask & (1 << cfg.KUNGFU_SET_SCHOOL_BITS[code]) == 0:
                continue
            entries, recipes = [], 0
            subtotal = defaultdict(float)
            for threshold in range(2, count + 1):
                for i in range(1, 5):
                    attr_id = row.get(f"{threshold}_{i}", "")
                    if attr_id in ("", "0"):
                        continue
                    attr = required_row(self._tables["attribs"], attr_id)
                    name = attr.get("ModifyType", "")
                    if name in cfg.SPECIAL_EFFECT_ATTRS:
                        recipes += 1
                        continue
                    value = number(attr.get("Param1Min", ""))
                    if value is None:
                        raise ValueError(f"套装属性 {attr_id} 缺少有效数值")
                    label = add_attr(subtotal, name, value, rules) or "UNMAPPED"
                    entries.append({"name": cfg.PANEL_FIELD_LABELS.get(label, label),
                                    "value": value, "pieces": threshold})
            for field, value in subtotal.items():
                whole[field] += value
            suits.append({"name": row.get("Name", ""), "count": count,
                          "attributes": entries, "recipes": recipes})
        return suits
