"""装备计算实际使用的 10 张表，按原始 GBK 文本读取。"""

from pathlib import Path


EQUIPMENT_FILES = (
    "settings/item/Custom_Weapon.tab",
    "settings/item/Custom_Armor.tab",
    "settings/item/Custom_Trinket.tab",
)
INDEX_FILES = {
    "enchants": ("settings/item/Enchant.tab", "ID"),
    "sets": ("settings/item/Set.tab", "ID"),
    "attribs": ("settings/item/Attrib.tab", "ID"),
    "others": ("settings/item/Other.tab", "ID"),
    "items": ("ui/scheme/case/Item.txt", "ItemID"),
    "skill_events": ("ui/scheme/case/Skillevent.txt", "ID"),
    "equip_db": ("ui/scheme/case/equipdb.txt", "ID"),
}
TABLE_FILES = EQUIPMENT_FILES + tuple(file for file, _ in INDEX_FILES.values())


def read_table(path: str | Path):
    """首行为表头；引号是普通字符，缺列不补值，多列记为 extra_下标。"""
    with Path(path).open(encoding="gbk") as stream:
        headers = stream.readline().strip("\r\n").split("\t")
        headers = [name.strip() for name in headers]
        for line in stream:
            if line.strip():
                yield {
                    headers[i] if i < len(headers) else f"extra_{i}": value.strip()
                    for i, value in enumerate(line.rstrip("\r\n").split("\t"))
                }


def load_tables(directory: str | Path) -> dict:
    directory = Path(directory)
    tables = {"equips": {}}
    for tab_type, filename in enumerate(EQUIPMENT_FILES, 6):
        for row in read_table(directory / filename):
            tables["equips"][f"{tab_type}_{row.get('ID', '')}"] = row
    for name, (filename, field) in INDEX_FILES.items():
        index = {}
        for row in read_table(directory / filename):
            key = row.get(field, "")
            if name in ("enchants", "others"):
                key = int(key)
            elif name == "equip_db":
                key = f"{row.get('TabType', '')}_{key}"
            index[key] = row
        tables[name] = index
    return tables
