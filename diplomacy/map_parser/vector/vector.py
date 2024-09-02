import re
from typing import Callable
from xml.etree.ElementTree import Element

import numpy as np
from lxml import etree
from scipy.spatial import cKDTree
from shapely.geometry import Point, Polygon

from diplomacy.map_parser.vector import cheat_parsing
from diplomacy.map_parser.vector.config_player import player_to_color, NEUTRAL, BLANK_CENTER
from diplomacy.map_parser.vector.config_svg import *
from diplomacy.map_parser.vector.utils import (
    get_player,
    _get_unit_type,
    _get_unit_coordinates,
    get_svg_element_by_id,
    get_translation_for_element,
    add_tuples,
)
from diplomacy.persistence.board import Board
from diplomacy.persistence.phase import spring_moves
from diplomacy.persistence.player import Player
from diplomacy.persistence.province import Province, ProvinceType, Coast
from diplomacy.persistence.unit import Unit, UnitType

# TODO: (BETA) all attribute getting should be in utils which we import and call utils.my_unit()
# TODO: (BETA) consistent in bracket formatting
NAMESPACE: dict[str, str] = {
    "inkscape": "{http://www.inkscape.org/namespaces/inkscape}",
    "sodipodi": "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd",
    "svg": "http://www.w3.org/2000/svg",
}


class Parser:
    def __init__(self):
        svg_root = etree.parse(SVG_PATH)

        self.land_layer: Element = get_svg_element_by_id(svg_root, LAND_PROVINCE_LAYER_ID)
        self.island_layer: Element = get_svg_element_by_id(svg_root, ISLAND_PROVINCE_LAYER_ID)
        self.island_fill_layer: Element = get_svg_element_by_id(svg_root, ISLAND_FILL_PLAYER_ID)
        self.sea_layer: Element = get_svg_element_by_id(svg_root, SEA_PROVINCE_LAYER_ID)
        self.names_layer: Element = get_svg_element_by_id(svg_root, PROVINCE_NAMES_LAYER_ID)
        self.centers_layer: Element = get_svg_element_by_id(svg_root, SUPPLY_CENTER_LAYER_ID)
        self.units_layer: Element = get_svg_element_by_id(svg_root, UNITS_LAYER_ID)

        self.phantom_primary_armies_layer: Element = get_svg_element_by_id(svg_root, PHANTOM_PRIMARY_ARMY_LAYER_ID)
        self.phantom_retreat_armies_layer: Element = get_svg_element_by_id(svg_root, PHANTOM_RETREAT_ARMY_LAYER_ID)
        self.phantom_primary_fleets_layer: Element = get_svg_element_by_id(svg_root, PHANTOM_PRIMARY_FLEET_LAYER_ID)
        self.phantom_retreat_fleets_layer: Element = get_svg_element_by_id(svg_root, PHANTOM_RETREAT_FLEET_LAYER_ID)

        self.color_to_player: dict[str, Player | None] = {}
        self.name_to_province: dict[str, Province] = {}

    def parse(self) -> Board:
        players = set()
        for name, color in player_to_color.items():
            player = Player(name, color, set(), set())
            players.add(player)
            self.color_to_player[color] = player

        self.color_to_player[NEUTRAL] = None
        self.color_to_player[BLANK_CENTER] = None

        provinces = self._get_provinces()

        units = set()
        for province in provinces:
            unit = province.unit
            if unit:
                units.add(unit)

        return Board(players, provinces, units, spring_moves)

    def _get_provinces(self) -> set[Province]:
        # TODO: (BETA) get names/centers/units without aid labeling and test equality against aid labeling
        # set coordinates and names
        provinces: set[Province] = self._get_province_coordinates()
        if not PROVINCE_FILLS_LABELED:
            self._initialize_province_names(provinces)

        for province in provinces:
            self.name_to_province[province.name] = province

        # set adjacencies
        # TODO: (BETA) province adjacency margin somtimes too high or too low, base it case by case on province size?
        adjacencies = _get_adjacencies(provinces)
        for name1, name2 in adjacencies:
            province1 = self.name_to_province[name1]
            province2 = self.name_to_province[name2]
            province1.adjacent.add(province2)
            province2.adjacent.add(province1)

        # set coasts
        for province in provinces:
            province.set_coasts()
        cheat_parsing.set_coasts(self.name_to_province)
        cheat_parsing.set_canals(self.name_to_province)

        cheat_parsing.create_high_seas_and_sands(provinces, self.name_to_province)

        self._initialize_province_owners(self.land_layer)
        self._initialize_province_owners(self.island_fill_layer)

        # set supply centers
        if CENTER_PROVINCES_LABELED:
            self._initialize_supply_centers_assisted()
        else:
            self._initialize_supply_centers(provinces)

        # set units
        if UNIT_PROVINCES_LABELED:
            self._initialize_units_assisted()
        else:
            self._initialize_units(provinces)

        # set phantom unit coordinates for optimal unit placements
        self._set_phantom_unit_coordinates()

        return provinces

    def _get_province_coordinates(self) -> set[Province]:
        # TODO: (BETA) don't hardcode translation
        land_provinces = self._create_provinces_type(self.land_layer, ProvinceType.LAND)
        island_provinces = self._create_provinces_type(self.island_layer, ProvinceType.ISLAND)
        sea_provinces = self._create_provinces_type(self.sea_layer, ProvinceType.SEA)
        return land_provinces.union(island_provinces).union(sea_provinces)

    # TODO: (BETA) can a library do all of this for us? more safety from needing to support wild SVG legal syntax
    def _create_provinces_type(
        self,
        provinces_layer: Element,
        province_type: ProvinceType,
    ) -> set[Province]:
        provinces = set()
        for province_data in provinces_layer.getchildren():
            path_string = province_data.get("d")
            if not path_string:
                raise RuntimeError("Province path data not found")
            path: list[str] = path_string.split()

            province_coordinates = []

            command = None
            expected_arguments = 0
            base_coordinate = (0, 0)
            former_coordinate = (0, 0)
            current_index = 0
            while current_index < len(path):
                if path[current_index][0].isalpha():
                    if len(path[current_index]) != 1:
                        # m20,70 is valid syntax, so move the 20,70 to the next element
                        path.insert(current_index + 1, path[current_index][1:])
                        path[current_index] = path[current_index][0]

                    command = path[current_index]
                    if command.lower() == "z":
                        expected_arguments = 0
                        former_coordinate = base_coordinate
                        province_coordinates.append(former_coordinate)
                        current_index += 1
                        continue
                    elif command.lower() in ["m", "l", "h", "v", "t"]:
                        expected_arguments = 1
                    elif command.lower() in ["s", "q"]:
                        expected_arguments = 2
                    elif command.lower() in ["c"]:
                        expected_arguments = 3
                    elif command.lower() in ["a"]:
                        expected_arguments = 4
                    else:
                        raise RuntimeError(f"Unknown SVG path command {command}")

                    current_index += 1

                if len(path) < (current_index + expected_arguments):
                    raise RuntimeError(f"Ran out of arguments for {command}")

                args = [
                    (float(coord_string.split(",")[0]), float(coord_string.split(",")[-1]))
                    for coord_string in path[current_index : current_index + expected_arguments]
                ]
                base_coordinate, former_coordinate = _parse_path_command(
                    command, args, base_coordinate, former_coordinate
                )
                province_coordinates.append(former_coordinate)
                current_index += expected_arguments

            layer_translation = get_translation_for_element(provinces_layer)
            for index, coordinate in enumerate(province_coordinates):
                province_coordinates[index] = add_tuples(coordinate, layer_translation)

            name = None
            if PROVINCE_FILLS_LABELED:
                name = self._get_province_name(province_data)

            province = Province(
                name,
                province_coordinates,
                None,
                None,
                province_type,
                False,
                set(),
                set(),
                None,
                None,
                None,
            )

            provinces.add(province)
        return provinces

    def _initialize_province_owners(self, provinces_layer: Element) -> None:
        for province_data in provinces_layer.getchildren():
            name = self._get_province_name(province_data)
            self.name_to_province[name].owner = get_player(province_data, self.color_to_player)

    # Sets province names given the names layer
    def _initialize_province_names(self, provinces: set[Province]) -> None:
        def get_coordinates(name_data: Element) -> tuple[float, float]:
            return float(name_data.get("x")), float(name_data.get("y"))

        def set_province_name(province: Province, name_data: Element) -> None:
            if province.name is not None:
                raise RuntimeError(f"Province already has name: {province.name}")
            province.name = name_data.findall(".//svg:tspan", namespaces=NAMESPACE)[0].text

        initialize_province_resident_data(provinces, self.names_layer.getchildren(), get_coordinates, set_province_name)

    def _initialize_supply_centers_assisted(self) -> None:
        for center_data in self.centers_layer.getchildren():
            name = self._get_province_name(center_data)
            province = self.name_to_province[name]

            if province.has_supply_center:
                raise RuntimeError(f"{name} already has a supply center")
            province.has_supply_center = True

            owner = province.owner
            if owner:
                owner.centers.add(province)

            # TODO: (BETA): we cheat assume core = owner if exists because capital center symbols work different
            core = province.owner
            if not core:
                core_data = center_data.findall(".//svg:circle", namespaces=NAMESPACE)[1]
                core = get_player(core_data, self.color_to_player)
            province.core = core

    # Sets province supply center values
    def _initialize_supply_centers(self, provinces: set[Province]) -> None:

        def get_coordinates(supply_center_data: Element) -> tuple[float | None, float | None]:
            circles = supply_center_data.findall(".//svg:circle", namespaces=NAMESPACE)
            if not circles:
                return None, None
            circle = circles[0]
            base_coordinates = float(circle.get("cx")), float(circle.get("cy"))
            translation_coordinates = _get_translation_coordinates(supply_center_data)
            return (
                base_coordinates[0] + translation_coordinates[0],
                base_coordinates[1] + translation_coordinates[1],
            )

        def set_province_supply_center(province: Province, _: Element) -> None:
            if province.has_supply_center:
                raise RuntimeError(f"{province.name} already has a supply center")
            province.has_supply_center = True

        initialize_province_resident_data(provinces, self.centers_layer, get_coordinates, set_province_supply_center)

    def _set_province_unit(self, province: Province, unit_data: Element, coast: Coast) -> Unit:
        if province.unit:
            raise RuntimeError(f"{province.name} already has a unit")

        unit_type = _get_unit_type(unit_data.findall(".//svg:path", namespaces=NAMESPACE)[0])
        color_data = unit_data.findall(".//svg:path", namespaces=NAMESPACE)[0]
        player = get_player(color_data, self.color_to_player)
        # TODO: (BETA) tech debt: let's pass the coast in instead of only passing in coast when province has multiple
        if not coast and unit_type == UnitType.FLEET:
            coast = next((coast for coast in province.coasts), None)

        unit = Unit(unit_type, player, province, coast, None)
        province.unit = unit
        unit.player.units.add(unit)
        return unit

    def _initialize_units_assisted(self) -> None:
        for unit_data in self.units_layer.getchildren():
            province_name = self._get_province_name(unit_data)
            province, coast = self._get_province_and_coast(province_name)
            self._set_province_unit(province, unit_data, coast)

    # Sets province unit values
    def _initialize_units(self, provinces: set[Province]) -> None:
        def get_coordinates(unit_data: Element) -> tuple[float | None, float | None]:
            base_coordinates = unit_data.findall(".//svg:path", namespaces=NAMESPACE)[0].get("d").split()[1].split(",")
            translation_coordinates = _get_translation_coordinates(unit_data)
            return (
                float(base_coordinates[0]) + translation_coordinates[0],
                float(base_coordinates[1]) + translation_coordinates[1],
            )

        initialize_province_resident_data(
            provinces, self.units_layer.getchildren(), get_coordinates, self._set_province_unit
        )

    def _set_phantom_unit_coordinates(self) -> None:
        # TODO: (MAP) bug: all of our phantom units also have a matrix transform (all the same)
        army_layer_to_key = [
            (self.phantom_primary_armies_layer, "primary_unit_coordinate"),
            (self.phantom_retreat_armies_layer, "retreat_unit_coordinate"),
        ]
        for layer, province_key in army_layer_to_key:
            layer_translation = get_translation_for_element(self.phantom_primary_armies_layer)
            for unit_data in layer.getchildren():
                unit_translation = get_translation_for_element(unit_data)
                province = self._get_province(unit_data)
                coordinate = _get_unit_coordinates(unit_data)
                setattr(province, province_key, add_tuples(coordinate, layer_translation, unit_translation))
        fleet_layer_to_key = [
            (self.phantom_primary_fleets_layer, "primary_unit_coordinate"),
            (self.phantom_retreat_fleets_layer, "retreat_unit_coordinate"),
        ]
        for layer, province_key in fleet_layer_to_key:
            layer_translation = get_translation_for_element(self.phantom_primary_armies_layer)
            for unit_data in layer.getchildren():
                unit_translation = get_translation_for_element(unit_data)
                # This could either be a sea province or a land coast
                province_name = self._get_province_name(unit_data)
                province, coast = self._get_province_and_coast(province_name)
                coordinate = _get_unit_coordinates(unit_data)
                if coast:
                    setattr(coast, province_key, add_tuples(coordinate, layer_translation, unit_translation))
                else:
                    setattr(province, province_key, add_tuples(coordinate, layer_translation, unit_translation))

    def _get_province_name(self, province_data: Element) -> str:
        return province_data.get(f"{NAMESPACE.get('inkscape')}label")

    def _get_province(self, province_data: Element) -> Province:
        return self.name_to_province[self._get_province_name(province_data)]

    def _get_province_and_coast(self, province_name: str) -> tuple[Province, Coast | None]:
        coast_suffix: str | None = None
        coast_names = {" (nc)", " (sc)", " (ec)", " (wc)"}

        for coast_name in coast_names:
            if province_name[len(province_name) - 5 :] == coast_name:
                province_name = province_name[: len(province_name) - 5]
                coast_suffix = coast_name[2:4]
                break

        province = self.name_to_province[province_name]
        coast = None
        if coast_suffix:
            coast = next((coast for coast in province.coasts if coast.name == f"{province_name} {coast_suffix}"), None)

        return province, coast


# returns:
# new base_coordinate (= base_coordinate if not applicable),
# new former_coordinate (= former_coordinate if not applicable),
def _parse_path_command(
    command: str,
    args: list[tuple[float, float]],
    base_coordinate: tuple[float, float],
    former_coordinate: tuple[float, float],
) -> tuple[tuple[float, float], tuple[float, float]]:
    if command.isupper():
        former_coordinate = (0, 0)
        command = command.lower()

    if command == "m":
        new_coordinate = move_coordinate(former_coordinate, args[0])
        return new_coordinate, new_coordinate
    elif command == "l" or command == "t" or command == "s" or command == "q" or command == "c" or command == "a":
        return base_coordinate, move_coordinate(former_coordinate, args[-1])  # Ignore all args except the last
    elif command == "h":
        return base_coordinate, move_coordinate(former_coordinate, args[0], ignore_y=True)
    elif command == "v":
        return base_coordinate, move_coordinate(former_coordinate, args[0], ignore_x=True)
    elif command == "z":
        raise RuntimeError("SVG command z should not be followed by any coordinates")
    else:
        raise RuntimeError(f"Unknown SVG path command: {command}")


def move_coordinate(
    former_coordinate: tuple[float, float],
    coordinate: tuple[float, float],
    ignore_x=False,
    ignore_y=False,
) -> tuple[float, float]:
    x = former_coordinate[0]
    y = former_coordinate[1]
    if not ignore_x:
        x += coordinate[0]
    if not ignore_y:
        y += coordinate[1]
    return x, y


# Returns the coordinates of the translation transform in the given element
def _get_translation_coordinates(element: Element) -> tuple[float, float]:
    transform = element.get("transform")
    if not transform:
        return None, None
    split = re.split(r"[(),]", transform)
    assert split[0] == "translate"
    return float(split[1]), float(split[2])


# Initializes relevant province data
# resident_dataset: SVG element whose children each live in some province
# get_coordinates: functions to get x and y child data coordinates in SVG
# function: method in Province that, given the province and a child element corresponding to that province, initializes
# that data in the Province
def initialize_province_resident_data(
    provinces: set[Province],
    resident_dataset: list[Element],
    get_coordinates: Callable[[Element], tuple[float, float]],
    function: Callable[[Province, Element], None],
) -> None:
    resident_dataset = set(resident_dataset)
    for province in provinces:
        remove = set()

        polygon = Polygon(province.coordinates)
        found = False
        for resident_data in resident_dataset:
            x, y = get_coordinates(resident_data)

            if not x or not y:
                remove.add(resident_data)
                continue

            point = Point((x, y))
            if polygon.contains(point):
                found = True
                function(province, resident_data)
                remove.add(resident_data)

        if not found:
            print("Not found!")

        for resident_data in remove:
            resident_dataset.remove(resident_data)


# Returns province adjacency set
def _get_adjacencies(provinces: set[Province]) -> set[tuple[str, str]]:
    # cKDTree is great, but it doesn't intelligently exclude clearly impossible cases of which we will have many
    coordinates = {}
    for province in provinces:
        x_sort = sorted(province.coordinates, key=lambda coordinate: coordinate[0])
        y_sort = sorted(province.coordinates, key=lambda coordinate: coordinate[1])
        coordinates[province.name] = {"x_sort": x_sort, "y_sort": y_sort}

    adjacencies = set()
    for province_1, coordinates_1 in coordinates.items():
        tree_1 = cKDTree(np.array(coordinates_1["x_sort"]))

        x1_min = coordinates_1["x_sort"][0][0]
        x1_max = coordinates_1["x_sort"][-1][0]
        y1_min = coordinates_1["y_sort"][0][1]
        y1_max = coordinates_1["y_sort"][-1][1]

        for province_2, coordinates_2 in coordinates.items():
            if province_1 >= province_2:
                # check each pair once, don't check self-self
                continue

            x2_min = coordinates_2["x_sort"][0][0]
            x2_max = coordinates_2["x_sort"][-1][0]
            y2_min = coordinates_2["y_sort"][0][1]
            y2_max = coordinates_2["y_sort"][-1][1]

            if x1_min > x2_max or x1_max < x2_min:
                # out of x-scope
                continue

            if y1_min > y2_max or y1_max < y2_min:
                # out of y-scope
                continue

            for point in coordinates_2["x_sort"]:
                if tree_1.query_ball_point(point, r=PROVINCE_BORDER_MARGIN):
                    adjacencies.add((province_1, province_2))
                    continue
    return adjacencies
