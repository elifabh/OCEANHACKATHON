#!/usr/bin/env python3
"""
asset_classes.py -- the receptor taxonomy for the national screen.

WHY THIS FILE EXISTS SEPARATELY
-------------------------------
Every national screen this project has run counted ONE kind of receptor: an
OSM building. That was never stated as a limitation -- it was stated as a
result ("no exposed receptors"), and the two are not the same sentence. A
road, a pier, a substation, a water main and a national monument are all
damage receptors, and none of them is a building.

The taxonomy lives in its own module so it can be read, audited and diffed
without reading the screen. Nothing here computes anything.

STRUCTURE
---------
Five FAMILIES, matching the classes asked for on 2026-08-28:

    transport        highways (all classes), railways, aeroways, bridges,
                     tunnels, fords, ferry terminals, parking
    coastal_marine   piers, breakwaters, groynes, embankments, dykes, quays,
                     lighthouses, beacons, harbours, marinas, slipways,
                     boatyards, docks, sea walls, retaining walls, bollards
    utilities        power (all), pipelines, water towers/works, covered
                     reservoirs, storage tanks, silos, wastewater plants,
                     pumping stations, masts, communications towers, street
                     cabinets, manholes, telecom, sewerage, culverts
    public_community amenities (school ... waste), emergency infrastructure,
                     tourism, leisure, historic (ANY -- the Irish coast
                     carries protected national monuments)
    land_parcels     landuse residential/commercial/retail/industrial/
                     farmyard/quarry/cemetery/allotments/aquaculture, and
                     man_made=works

Each CLASS carries:
    key           stable id, used as a column and a cache key
    family        one of the five above
    label         plain English, for the note and the tables
    match         a predicate over the OSM tag dict (pure Python, no
                  Overpass dialect) -- this is what actually classifies
    completeness  our assessment of whether ABSENCE of this class from OSM
                  in rural coastal Ireland is evidence of absence on the
                  ground. See the three levels below. This is a JUDGEMENT,
                  recorded here so it can be challenged, and it is tested
                  empirically by asset_completeness_probe.py.

COMPLETENESS LEVELS -- what an empty cell means
----------------------------------------------
  "high"     OSM coverage of this class in rural Ireland is good enough that
             absence is weak evidence of absence. Roads and buildings only:
             both have been systematically mapped nationally, and the
             coastline itself is one of the best-mapped features in OSM IE.
  "medium"   The class is mapped when a mapper visits, and coastal Ireland
             has been visited. Absence is suggestive, not conclusive.
  "low"      The class is mapped sporadically or only in urban areas.
             ABSENCE IS NOT EVIDENCE. Buried, small or unglamorous assets:
             manholes, street cabinets, culverts, pipelines, telecom,
             sewerage, minor power. A zero here means "OSM does not record
             one", never "there is not one".

The screen prints the level beside every count, and the note repeats it.
No count from a "low" class may be used to support a negative finding.

PROVENANCE
----------
  (c) OpenStreetMap contributors, ODbL 1.0. Everything this taxonomy
  selects is an ODbL derivative database.
"""

from __future__ import annotations

# ----------------------------------------------------------------------
# helpers for the match predicates
# ----------------------------------------------------------------------

def _in(key: str, values: set):
    return lambda t: t.get(key) in values


def _kv(key: str, value: str):
    return lambda t: t.get(key) == value


# ----------------------------------------------------------------------
# tag value sets
# ----------------------------------------------------------------------
# highway=* is split into four classes rather than one, because "a
# regional road is exposed" and "a footpath is exposed" are different
# sentences and lumping them would hide the difference. The split follows
# the OSM highway hierarchy, not our judgement of importance.

HIGHWAY_MAJOR = {"motorway", "trunk", "primary", "secondary", "tertiary",
                 "motorway_link", "trunk_link", "primary_link",
                 "secondary_link", "tertiary_link"}
HIGHWAY_MINOR = {"unclassified", "residential", "living_street", "service",
                 "road", "busway"}
HIGHWAY_PATH = {"footway", "cycleway", "path", "bridleway", "steps",
                "pedestrian", "corridor"}
HIGHWAY_POINT = {"bus_stop", "crossing", "turning_circle", "turning_loop",
                 "passing_place", "stop", "give_way", "traffic_signals",
                 "mini_roundabout", "street_lamp", "milestone", "speed_camera",
                 "elevator", "emergency_bay"}

RAILWAY_ACTIVE = {"rail", "light_rail", "tram", "subway", "narrow_gauge",
                  "funicular", "monorail", "preserved"}
RAILWAY_DISUSED = {"disused", "abandoned", "razed", "proposed",
                   "construction", "dismantled"}
RAILWAY_POINT = {"station", "halt", "tram_stop", "platform", "stop",
                 "level_crossing", "crossing", "yard", "turntable",
                 "buffer_stop", "signal", "switch"}

AEROWAY = {"aerodrome", "runway", "taxiway", "apron", "helipad",
           "heliport", "terminal", "hangar", "airstrip", "windsock"}

AMENITY_PUBLIC = {"school", "kindergarten", "college", "university",
                  "hospital", "clinic", "doctors", "pharmacy",
                  "fire_station", "police", "community_centre",
                  "place_of_worship", "fuel", "shelter", "toilets",
                  "drinking_water", "waste_disposal", "waste_transfer_station",
                  "recycling", "waste_basket", "social_facility",
                  "townhall", "library", "post_office", "prison",
                  "grave_yard", "nursing_home", "childcare"}

AMENITY_PARKING = {"parking", "parking_space", "bicycle_parking",
                   "motorcycle_parking", "parking_entrance"}

TOURISM = {"camp_site", "caravan_site", "hotel", "hostel", "guest_house",
           "attraction", "information", "viewpoint", "motel", "apartment",
           "chalet", "museum", "picnic_site", "alpine_hut", "wilderness_hut",
           "artwork", "gallery", "theme_park", "zoo"}

LEISURE = {"marina", "pitch", "golf_course", "park", "slipway", "playground",
           "nature_reserve", "sports_centre", "swimming_pool", "track",
           "stadium", "recreation_ground", "fitness_station", "garden",
           "bird_hide", "fishing", "beach_resort", "common", "dog_park",
           "horse_riding", "outdoor_seating", "sports_hall"}

LANDUSE_PARCEL = {"residential", "commercial", "retail", "industrial",
                  "farmyard", "quarry", "cemetery", "allotments",
                  "aquaculture", "harbour", "port", "brownfield",
                  "landfill", "depot", "religious", "education",
                  "institutional"}

POWER_NODE = {"tower", "pole", "substation", "generator", "plant",
              "transformer", "portal", "converter", "switchgear",
              "insulator", "terminal", "catenary_mast", "connection"}
POWER_LINE = {"line", "minor_line", "cable"}


CLASSES: list = [
    # ------------------------------------------------ transport
    dict(key="road_major", family="transport",
         label="Road - major (motorway to tertiary)",
         completeness="high",
         match=_in("highway", HIGHWAY_MAJOR)),
    dict(key="road_minor", family="transport",
         label="Road - minor (unclassified, residential, service)",
         completeness="high",
         match=_in("highway", HIGHWAY_MINOR)),
    dict(key="track", family="transport",
         label="Track (unsurfaced vehicle way)",
         completeness="medium",
         match=_kv("highway", "track")),
    dict(key="path_foot_cycle", family="transport",
         label="Footway / cycleway / path / steps",
         completeness="medium",
         match=_in("highway", HIGHWAY_PATH)),
    dict(key="highway_point", family="transport",
         label="Highway point feature (bus stop, crossing, turning circle, street lamp)",
         completeness="low",
         match=_in("highway", HIGHWAY_POINT)),
    dict(key="railway_active", family="transport",
         label="Railway - in use (rail, tram, light rail)",
         completeness="high",
         match=_in("railway", RAILWAY_ACTIVE)),
    dict(key="railway_disused", family="transport",
         label="Railway - disused / abandoned / proposed",
         completeness="medium",
         match=lambda t: (t.get("railway") in RAILWAY_DISUSED
                          or "disused:railway" in t or "abandoned:railway" in t
                          or "razed:railway" in t or "dismantled:railway" in t)),
    dict(key="railway_point", family="transport",
         label="Railway point feature (station, halt, level crossing)",
         completeness="high",
         match=_in("railway", RAILWAY_POINT)),
    dict(key="aeroway", family="transport",
         label="Aeroway (aerodrome, runway, helipad, hangar)",
         completeness="high",
         match=_in("aeroway", AEROWAY)),
    dict(key="bridge", family="transport",
         label="Bridge",
         completeness="high",
         match=lambda t: (t.get("bridge") not in (None, "no")
                          or t.get("man_made") == "bridge")),
    dict(key="tunnel", family="transport",
         label="Tunnel (culverts counted separately)",
         completeness="high",
         match=lambda t: t.get("tunnel") not in (None, "no", "culvert")),
    dict(key="ford", family="transport",
         label="Ford (way crossing water at grade)",
         completeness="medium",
         match=lambda t: t.get("ford") not in (None, "no")),
    dict(key="ferry_terminal", family="transport",
         label="Ferry terminal",
         completeness="high",
         match=lambda t: (t.get("amenity") == "ferry_terminal"
                          or t.get("seamark:type") == "ferry_terminal")),
    dict(key="ferry_route", family="transport",
         label="Ferry route",
         completeness="medium",
         match=_kv("route", "ferry")),
    dict(key="parking", family="transport",
         label="Parking (car park, parking space, bicycle parking)",
         completeness="medium",
         match=_in("amenity", AMENITY_PARKING)),

    # ------------------------------------------------ coastal / marine works
    dict(key="pier_jetty", family="coastal_marine",
         label="Pier / jetty / wharf",
         completeness="high",
         match=lambda t: t.get("man_made") in {"pier", "jetty", "wharf"}),
    dict(key="breakwater_groyne", family="coastal_marine",
         label="Breakwater / groyne",
         completeness="medium",
         match=lambda t: t.get("man_made") in {"breakwater", "groyne"}),
    dict(key="embankment_dyke", family="coastal_marine",
         label="Embankment / dyke / levee",
         completeness="medium",
         match=lambda t: (t.get("man_made") in {"embankment", "dyke", "levee"}
                          or t.get("embankment") not in (None, "no"))),
    dict(key="quay", family="coastal_marine",
         label="Quay",
         completeness="medium",
         match=_kv("man_made", "quay")),
    dict(key="lighthouse_beacon", family="coastal_marine",
         label="Lighthouse / beacon / navigation light",
         completeness="high",
         match=lambda t: (t.get("man_made") in {"lighthouse", "beacon"}
                          or str(t.get("seamark:type", "")).startswith("beacon")
                          or t.get("seamark:type") in {"light_major", "light_minor",
                                                       "light", "landmark"})),
    dict(key="harbour", family="coastal_marine",
         label="Harbour / port",
         completeness="high",
         match=lambda t: (t.get("harbour") not in (None, "no")
                          or t.get("landuse") in {"harbour", "port"}
                          or t.get("seamark:type") == "harbour"
                          or t.get("waterway") == "harbour")),
    dict(key="marina", family="coastal_marine",
         label="Marina",
         completeness="high",
         match=_kv("leisure", "marina")),
    dict(key="slipway", family="coastal_marine",
         label="Slipway",
         completeness="medium",
         match=lambda t: (t.get("leisure") == "slipway"
                          or t.get("man_made") == "slipway"
                          or t.get("seamark:type") == "slipway")),
    dict(key="boatyard", family="coastal_marine",
         label="Boatyard / boat storage / shipyard",
         completeness="medium",
         match=lambda t: (t.get("industrial") in {"boatyard", "shipyard"}
                          or t.get("craft") in {"boatbuilder", "shipwright"}
                          or t.get("shop") == "boat"
                          or t.get("man_made") == "shipyard"
                          or t.get("landuse") == "boatyard")),
    dict(key="dock", family="coastal_marine",
         label="Dock / dry dock / boat lift",
         completeness="medium",
         match=lambda t: (t.get("waterway") in {"dock", "boatyard"}
                          or t.get("man_made") == "dock")),
    dict(key="sea_wall", family="coastal_marine",
         label="Sea wall / flood wall",
         completeness="low",
         match=lambda t: t.get("barrier") in {"sea_wall", "flood_wall"}),
    dict(key="retaining_wall", family="coastal_marine",
         label="Retaining wall",
         completeness="low",
         match=_kv("barrier", "retaining_wall")),
    dict(key="bollard", family="coastal_marine",
         label="Bollard",
         completeness="low",
         match=_kv("barrier", "bollard")),
    dict(key="wall_other", family="coastal_marine",
         label="Other wall / guard rail (barrier=wall, guard_rail)",
         completeness="low",
         match=lambda t: t.get("barrier") in {"wall", "guard_rail"}),

    # ------------------------------------------------ utilities and networks
    dict(key="power_line", family="utilities",
         label="Power line / minor line / cable",
         completeness="medium",
         match=_in("power", POWER_LINE)),
    dict(key="power_structure", family="utilities",
         label="Power structure (tower, pole, substation, generator, plant, transformer)",
         completeness="low",
         match=lambda t: (t.get("power") in POWER_NODE
                          or t.get("man_made") == "utility_pole")),
    dict(key="pipeline", family="utilities",
         label="Pipeline",
         completeness="low",
         match=lambda t: (t.get("man_made") == "pipeline"
                          or "pipeline" in t)),
    dict(key="water_supply", family="utilities",
         label="Water supply works (water tower, water works, covered reservoir, well)",
         completeness="medium",
         match=lambda t: t.get("man_made") in {"water_tower", "water_works",
                                               "reservoir_covered", "water_well"}),
    dict(key="storage", family="utilities",
         label="Storage tank / silo / gasometer",
         completeness="medium",
         match=lambda t: t.get("man_made") in {"storage_tank", "silo",
                                               "gasometer"}),
    dict(key="wastewater", family="utilities",
         label="Wastewater plant / pumping station / sewerage",
         completeness="low",
         match=lambda t: (t.get("man_made") in {"wastewater_plant",
                                                "pumping_station", "sewerage"}
                          or t.get("substance") in {"sewage", "wastewater"}
                          or t.get("waterway") == "sewer")),
    dict(key="mast_tower", family="utilities",
         label="Mast / communications tower / antenna / tower",
         completeness="medium",
         match=lambda t: t.get("man_made") in {"mast", "communications_tower",
                                               "antenna", "tower"}),
    dict(key="street_cabinet", family="utilities",
         label="Street cabinet",
         completeness="low",
         match=_kv("man_made", "street_cabinet")),
    dict(key="manhole", family="utilities",
         label="Manhole",
         completeness="low",
         match=lambda t: (t.get("man_made") == "manhole" or "manhole" in t)),
    dict(key="telecom", family="utilities",
         label="Telecom infrastructure",
         completeness="low",
         match=lambda t: ("telecom" in t
                          or t.get("man_made") == "telephone_exchange"
                          or t.get("utility") == "telecom")),
    dict(key="culvert", family="utilities",
         label="Culvert",
         completeness="low",
         match=lambda t: (t.get("tunnel") == "culvert"
                          or t.get("waterway") == "culvert"
                          or t.get("man_made") == "culvert")),
    dict(key="monitoring", family="utilities",
         label="Monitoring station (tide gauge, weather, seismic)",
         completeness="medium",
         match=_kv("man_made", "monitoring_station")),
    dict(key="works", family="utilities",
         label="Industrial works (man_made=works)",
         completeness="medium",
         match=_kv("man_made", "works")),

    # ------------------------------------------------ public and community
    dict(key="amenity_public", family="public_community",
         label="Public amenity (school, health, emergency service, worship, fuel, waste, shelter)",
         completeness="high",
         match=_in("amenity", AMENITY_PUBLIC)),
    dict(key="emergency", family="public_community",
         label="Emergency infrastructure (lifeboat station, rescue, hydrant, defibrillator, phone)",
         completeness="medium",
         match=lambda t: t.get("emergency") not in (None, "no")),
    dict(key="tourism", family="public_community",
         label="Tourism (camp site, caravan site, hotel, hostel, guest house, attraction, viewpoint)",
         completeness="high",
         match=_in("tourism", TOURISM)),
    dict(key="leisure", family="public_community",
         label="Leisure (pitch, golf course, park, playground, nature reserve, sports)",
         completeness="high",
         match=_in("leisure", LEISURE)),
    dict(key="historic", family="public_community",
         label="Historic / archaeological (any historic=*)",
         completeness="medium",
         match=lambda t: t.get("historic") not in (None, "no")),
    dict(key="protected_designation", family="public_community",
         label="Protected-area or heritage designation (protect_class, heritage, boundary=protected_area)",
         completeness="medium",
         match=lambda t: ("heritage" in t or "protect_class" in t
                          or "ref:NMS" in t
                          or t.get("boundary") == "protected_area")),

    # ------------------------------------------------ land parcels
    dict(key="landuse_parcel", family="land_parcels",
         label="Land parcel (residential, commercial, retail, industrial, farmyard, quarry, cemetery, allotments, aquaculture)",
         completeness="medium",
         match=_in("landuse", LANDUSE_PARCEL)),
    dict(key="aquaculture", family="land_parcels",
         label="Aquaculture / marine farm",
         completeness="low",
         match=lambda t: (t.get("landuse") == "aquaculture"
                          or t.get("seamark:type") == "marine_farm"
                          or t.get("industrial") == "aquaculture")),
]

BY_KEY = {c["key"]: c for c in CLASSES}
FAMILIES = ["transport", "coastal_marine", "utilities", "public_community",
            "land_parcels"]
KEYS = [c["key"] for c in CLASSES]

COMPLETENESS_MEANING = {
    "high": "OSM coverage in rural Ireland is good; an empty cell is weak "
            "evidence of absence on the ground.",
    "medium": "mapped when a mapper visits; an empty cell is suggestive, "
              "not conclusive.",
    "low": "ABSENCE IS NOT EVIDENCE - mapped sporadically or only in towns. "
           "A zero means OSM does not record one, never that there is none.",
}


def classify(tags: dict) -> list:
    """Every class this element belongs to. An element may match several --
    a pier that is also a road is both, and hiding one of them would be a
    choice about which asset matters."""
    return [c["key"] for c in CLASSES if c["match"](tags)]


def primary_class(keys: list):
    """One class per element for the headline table, chosen by the order in
    CLASSES (transport first, land parcels last). Reported alongside the
    full list, never instead of it."""
    return keys[0] if keys else None
