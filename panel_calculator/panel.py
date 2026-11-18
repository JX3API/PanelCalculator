"""属性通道、主属性转换与最终面板；保留逐步取整的顺序。"""

from math import floor

from . import config as cfg
from .equipment import round_score


def external_primary(kungfu: dict) -> bool:
    if kungfu["type"] == "tank":
        return kungfu.get("attr_school") == "external"
    return kungfu["type"] == "external"


def attribute_rules(kungfu: dict) -> dict:
    rules = {attr: ((field,), field) for attr, field in cfg.DIRECT_MAP.items()}
    rules.update(cfg.MULTI_ATTR_MAP)
    channels = {
        "BASE_ATTACK": ["allAttackPowerBase", "atAllTypeAttackPowerBase"],
        "CRIT_LEVEL": ["atAllTypeCriticalStrike"],
        "OVERCOME_LEVEL": ["atAllOvercome", "atAllTypeOvercomeBase"],
        "CRIT_POWER_LEVEL": ["atAllTypeCriticalDamagePowerBase"],
    }
    external = external_primary(kungfu)
    channels["BASE_ATTACK"] += ["atPhysicsAttackPowerBase"] if external else cfg.MAGIC_ATTACK_TYPES
    channels["OVERCOME_LEVEL"] += ["atPhysicsOvercomeBase"] if external else cfg.MAGIC_OVERCOME_TYPES
    if external or kungfu["type"] == "tianluo":
        channels["CRIT_LEVEL"].append("atPhysicsCriticalStrike")
        channels["CRIT_POWER_LEVEL"].append("atPhysicsCriticalDamagePowerBase")
    else:
        channels["CRIT_LEVEL"] += cfg.MAGIC_CRIT_TYPES
        channels["CRIT_POWER_LEVEL"] += cfg.MAGIC_CRIT_POWER_TYPES
    if kungfu["type"] == "heal":
        rules["atTherapyPowerBase"] = (("THERAPY_POWER",), "THERAPY_POWER")
    for field, attrs in channels.items():
        for attr in attrs:
            rules[attr] = ((field,), field)
    rules.update(cfg.KUNGFU_ATTR_MAP.get(kungfu["code"], {}))
    if kungfu["code"] == "youluo":
        for field, attrs in cfg.YOULUO_GROUPS.items():
            for attr in attrs:
                rules[attr] = (("_RAW_" + attr,), field)
    return rules


def add_attr(panel: dict, name: str, value: float, rules: dict) -> str:
    fields, label = rules.get(name, ((), ""))
    for field in fields:
        panel[field] += value
    return label


def percent(ratio: float) -> float:
    return floor(ratio * 10000 + 0.5) / 100


def mitigate(level: float, name: str) -> float:
    ratio = level / (level + cfg.ATTR_COEF[name])
    if name == "defense":
        ratio = max(0, min(0.75, ratio))
    return percent(ratio)


def settle_panel(whole: dict, kungfu: dict) -> dict:
    stats = whole.copy()
    code, kind = kungfu["code"], kungfu["type"]
    if code == "youluo":
        potential = stats["_RAW_POTENTIAL"]
        maximum = max(stats[key] - cfg.BASE_STATS[key] - potential for key in ("STRENGTH", "SPUNK", "AGILITY"))
        for key in ("STRENGTH", "SPUNK", "AGILITY"):
            stats[key] = cfg.BASE_STATS[key] + potential
        stats["SPIRIT"] += maximum
        for field, attrs in cfg.YOULUO_GROUPS.items():
            values = [stats["_RAW_" + attr] for attr in attrs]
            if field == "BASE_ATTACK":
                values[0] += (stats["WEAPON_DAMAGE_MIN"] + stats["WEAPON_DAMAGE_MAX"]) / 2 * 6
            stats[field] += max(values)
    elif code == "mingzun":
        stats["BASE_ATTACK"] += max(stats["_RAW_TANK_SOLAR_ATTACK"], stats["_RAW_TANK_LUNAR_ATTACK"])
        stats["OVERCOME_LEVEL"] += max(stats["_RAW_TANK_SOLAR_OVERCOME"], stats["_RAW_TANK_LUNAR_OVERCOME"])

    for key in cfg.STAT_PERCENT_FIELDS:
        stats[key] = floor(stats[key] * (1 + stats["_RAW_PERCENT_" + key] / 1024))
    main = stats[kungfu["main_attr"]]
    bonus = kungfu["main_attr_bonus"]
    panel_attack = stats["BASE_ATTACK"] + floor(main * bonus.get("PANEL_ATTACK", 0))
    external = external_primary(kungfu)
    field, prefix = ("STRENGTH", "strength") if external else ("SPUNK", "spunk")
    attack = floor(stats[field] * cfg.BASE_COEF[prefix + "_to_attack"])
    stats["BASE_ATTACK"] += attack
    panel_attack += attack
    stats["OVERCOME_LEVEL"] += floor(stats[field] * cfg.BASE_COEF[prefix + "_to_overcome"])
    field, prefix = ("AGILITY", "agility") if external or kind == "tianluo" else ("SPIRIT", "spirit")
    stats["CRIT_LEVEL"] += floor(stats[field] * cfg.BASE_COEF[prefix + "_to_crit"])
    for key, value in bonus.items():
        if key not in ("PANEL_ATTACK", "PANEL_THERAPY", "HEALTH"):
            stats[key] += floor(main * value)
    stats["PANEL_ATTACK"] = panel_attack + floor(main * bonus.get("BASE_ATTACK", 0))
    if kind == "heal":
        stats["PANEL_THERAPY"] = stats["THERAPY_POWER"] + floor(main * bonus.get("PANEL_THERAPY", 0))
        therapy = floor(stats["ALL_ROUND_LEVEL"] * 150 / 1000)
        stats["THERAPY_POWER"] += therapy
        stats["PANEL_THERAPY"] += therapy
    else:
        stats["STRAIN_LEVEL"] += floor(stats["ALL_ROUND_LEVEL"] * 1220 / 1000)
    stats["DECRITICAL_LEVEL"] += stats["ALL_ROUND_LEVEL"]

    panel = {key: stats[key] for key in cfg.PANEL_SETTLE_FIELDS}
    base = cfg.BASE_MAX_HEALTH + stats["LIFE_BASE"]
    base += floor(stats["VITALITY"] * cfg.BASE_COEF["vitality_to_health"])
    health = base + floor(base * kungfu.get("base_health_bonus", 0) / 1024)
    health += floor(stats["VITALITY"] * bonus.get("HEALTH", 0))
    panel["MAX_HEALTH"] = health + stats["LIFE_ADDITIONAL"]
    crit = percent(stats["CRIT_LEVEL"] / cfg.ATTR_COEF["crit"])
    if code in ("jingyu", "tianluo"):
        crit += 1
    haste = min(stats["HASTE_LEVEL"] / cfg.ATTR_COEF["haste"], 0.25)
    decritical = mitigate(stats["DECRITICAL_LEVEL"], "decritical")
    decritical += kungfu["base_attrs"].get("DECRITICAL_RATE", 0) * 100
    panel.update({
        "CRIT_RATE": round_score(crit * 100) / 100,
        "CRIT_POWER": percent(1.75 + stats["CRIT_POWER_LEVEL"] / cfg.ATTR_COEF["crit_power"]),
        "OVERCOME_RATE": percent(stats["OVERCOME_LEVEL"] / cfg.ATTR_COEF["overcome"]),
        "STRAIN_RATE": percent(stats["STRAIN_LEVEL"] / cfg.ATTR_COEF["strain"]),
        "HASTE_BASE_RATE": percent(haste), "HASTE_RATE": percent(floor(haste * 1024) / 1024),
        "EXTERNAL_DEFENSE_RATE": mitigate(stats["EXTERNAL_DEFENSE"], "defense"),
        "INTERNAL_DEFENSE_RATE": mitigate(stats["INTERNAL_DEFENSE"], "defense"),
        "TOUGHNESS_RATE": percent(stats["TOUGHNESS_LEVEL"] / cfg.ATTR_COEF["toughness"]),
        "DECRITICAL_RATE": min(85, round_score(decritical * 100) / 100),
        "DODGE_RATE": mitigate(stats["DODGE_LEVEL"], "dodge"),
        "PARRY_RATE": mitigate(stats["PARRY_LEVEL"], "parry"),
    })
    if kind == "heal":
        panel["BASE_THERAPY"] = stats["THERAPY_POWER"]
        panel["PANEL_THERAPY"] = stats["PANEL_THERAPY"]
    return panel


def format_panel(panel: dict) -> list:
    rows = []
    for name, value, required, rate in cfg.PANEL_ROWS:
        if required and required not in panel:
            continue
        row = {"name": name, "value": panel[value]}
        if rate:
            row["percent"] = panel[rate]
        rows.append(row)
    return rows
