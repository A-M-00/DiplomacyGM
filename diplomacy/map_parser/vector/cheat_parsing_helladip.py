from diplomacy.persistence.province import Province, Coast, ProvinceType


# We are not yet perfect when parsing the map. This file is a temporary hard-coded cheat to get around that.


# Create high seas and sands provinces
def create_high_seas_and_sands(provinces: set[Province], name_to_province: dict[str, Province]) -> None:
    return

def _set_adjacencies(
    name_to_province: dict[str, Province],
    name: str,
    num: int,
    adjacent_provinces: set[Province],
) -> None:
    return


# Set coasts for all provinces with multiple coasts
def set_coasts(name_to_province: dict[str, Province]) -> None:
    _set_coasts(
        name_to_province["CONT"],
        {
            "nc": {
                name_to_province["GVAL"],
            },
            "sc": {
                name_to_province["GVAL"],
            },
        },
    )
    _set_coasts(
        name_to_province["WSIC"],
        {
            "nc": {
                name_to_province["TYRH"],
                name_to_province["SMES"],
            },
            "sc": {
                name_to_province["SSIC"],
            },
        },
    )
    _set_coasts(
        name_to_province["ESIC"],
        {
            "nc": {
                name_to_province["SMES"],
            },
            "sc": {
                name_to_province["MACH"],
            },
        },
    )
    _set_coasts(
        name_to_province["LAOS"],
        {
            "wc": {
                name_to_province["GSIC"],
            },
            "ec": {
                name_to_province["GTAR"],
            },
        },
    )
    _set_coasts(
        name_to_province["EPEL"],
        {
            "ec": {
                name_to_province["SCRE"],
            },
            "nc": {
                name_to_province["GCOR"],
            },
        },
    )
    _set_coasts(
        name_to_province["DELP"],
        {
            "sc": {
            },
            "wc": {
                name_to_province["GCOR"],
            },
        },
    )
    _set_coasts(
        name_to_province["CRIM"],
        {
            "wc": {
                name_to_province["GODE"],
            },
            "nc": {
                name_to_province["AZOV"],
            },
            "sc": {
                name_to_province["CRIS"],
            },
        },
    )


# Remove coasts for canal provinces
def set_canals(name_to_province: dict[str, Province]) -> None:
    _set_coasts(
        name_to_province["Cairo"],
        {
            "coast #1": {
                name_to_province["Levantine Sea"],
                name_to_province["Red Sea"],
            }
        },
    )
    _set_coasts(
        name_to_province["Kiel"],
        {
            "coast #1": {
                name_to_province["Wadden Sea"],
                name_to_province["Copenhagen"],
            }
        },
    )
    _set_coasts(
        name_to_province["Constantinople"],
        {
            "coast #1": {
                name_to_province["Black Sea"],
                name_to_province["Aegean Sea"],
            }
        },
    )


def _set_coasts(province: Province, name_to_adjacent: dict[str, set[Province]]):
    province.coasts = set()
    for name, adjacent in name_to_adjacent.items():
        coast = Coast(f"{province.name} {name}", None, None, adjacent, province)
        province.coasts.add(coast)


def fix_phantom_units(provinces: set[Province]):
    for province in provinces:
        if province.name == "Yucatan Channel":
            province.primary_unit_coordinate = (1028, 952)
            province.retreat_unit_coordinate = (1039, 921)
        if province.name == "SAH1":
            province.primary_unit_coordinate = (2029, 922)
            province.retreat_unit_coordinate = (2041, 935)
        if province.name == "SAH2":
            province.primary_unit_coordinate = (2100, 949)
            province.retreat_unit_coordinate = (2112, 961)
        if province.name == "SAH3":
            province.primary_unit_coordinate = (2129, 1017)
            province.retreat_unit_coordinate = (2141, 1029)
        if province.name == "Imerina":
            province.primary_unit_coordinate = (2632, 1518)
            province.retreat_unit_coordinate = (2648, 1485)
            province.coast().primary_unit_coordinate = province.primary_unit_coordinate
            province.coast().retreat_unit_coordinate = province.retreat_unit_coordinate


def set_secondary_locs(name_to_province: dict[str, set[Province]]):
    def set_one(name, primary, retreat):
        p: Province = name_to_province[name]
        # correct for inkscape giving top left, not middle coord
        primary = (primary[0] + 7.7655, primary[1] + 7.033)
        retreat = (retreat[0] + 7.7655, retreat[1] + 7.033)
        p.all_locs.add(primary)
        p.all_rets.add(retreat)

    set_one("NPO1", (3982.726, 874.217), (3994.726, 886.217))
    set_one("NPO2", (4059.726, 874.217), (4071.726, 886.217))
    set_one("NPO3", (4136.726, 874.217), (4148.726, 886.217))
    set_one("NPO4", (4021.226, 942.459), (4033.226, 954.459))
    set_one("NPO5", (4098.226, 942.401), (4110.226, 954.401))

    set_one("SPO1", (4061.260, 1509.495), (4073.260, 1521.495))
    set_one("SPO2", (4138.259, 1509.495), (4150.259, 1521.495))
    set_one("SPO3", (4215.260, 1510.000), (4227.260, 1522.000))
    set_one("SPO4", (4099.759, 1577.737), (4111.759, 1589.737))
    set_one("SPO5", (4176.760, 1577.678), (4188.760, 1589.678))

    set_one("Chukchi Sea", (28.000, 241.000), (72.908, 186.392))
