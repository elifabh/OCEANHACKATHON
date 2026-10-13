"""Transparent screening physics. Geometry in metres, angles clockwise from north.

This module estimates attenuation *within assumed habitat*. It does not model
shoreline hazard, refraction, diffraction, breaking, surge or expected damage.
"""
from __future__ import annotations

import math
import numpy as np
from shapely.geometry import LineString, Point
from shapely.ops import unary_union

DEPTHS = np.array([4., 6., 8., 10.])
DAMPING = np.array([.0094, .0032, .0014, .0005])


def finite(value, name):
    if value is None or isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return value


def damping(depth_m, method="interpolated"):
    """Dubi & Torum (1996). Interpolation is our choice, not new measurements."""
    d = finite(depth_m, "depth")
    if not 4 <= d <= 10:
        raise ValueError("Water depth lies outside the 4–10 m experimental domain")
    if method == "fitted":
        return .0658 * math.exp(-.5 * d)
    if method != "interpolated":
        raise ValueError("Unknown coefficient method")
    return float(np.interp(d, DEPTHS, DAMPING))


def effect(optical_depth):
    tau = finite(optical_depth, "integrated damping")
    if tau < 0:
        raise ValueError("Integrated damping cannot be negative")
    return {"height_fraction": -math.expm1(-tau),
            "energy_fraction": -math.expm1(-2*tau)}


def connected_groups(polygons, tolerance_m=2):
    """Components with a declared grid rounding tolerance; gaps stay unfilled."""
    seen, groups = set(), []
    for i in range(len(polygons)):
        if i in seen:
            continue
        group, queue = [], [i]
        seen.add(i)
        while queue:
            j = queue.pop(); group.append(j)
            for k in range(len(polygons)):
                if k not in seen and polygons[j].distance(polygons[k]) <= tolerance_m:
                    seen.add(k); queue.append(k)
        groups.append(sorted(group))
    return groups


def direction_vector(bearing):
    a = math.radians(finite(bearing, "bearing"))
    return np.array([math.sin(a), math.cos(a)])


def projected_intervals(polygons, bearing):
    """Union of habitat footprints across a ray, excluding gaps between groups."""
    u = direction_vector(bearing); v = np.array([u[1], -u[0]])
    intervals = []
    for p in polygons:
        vals = np.asarray(p.exterior.coords) @ v
        intervals.append((float(vals.min()), float(vals.max())))
    intervals.sort(); merged = []
    for lo, hi in intervals:
        if merged and lo <= merged[-1][1]:
            merged[-1][1] = max(hi, merged[-1][1])
        else:
            merged.append([lo, hi])
    return merged


def ray_effect(polygons, depths, point, bearing, water_level_m=0, method="interpolated", land=None):
    """Integrate actual polygon chords; do not count diagonals or empty gaps.

    Any intersected habitat cell outside the depth domain makes that ray
    non-computable. It is never assigned zero attenuation.
    """
    if len(polygons) != len(depths):
        raise ValueError("Each polygon needs one depth")
    level = finite(water_level_m, "water level")
    u = direction_vector(bearing); xy = np.array([point.x, point.y])
    line = LineString([xy-20000*u, xy+20000*u])
    intersections = [line.intersection(p) for p in polygons]
    lengths = [float(p.length) for p in intersections]
    hit = [i for i, length in enumerate(lengths) if length > 1e-6]
    if not hit:
        return {"status":"NO_HABITAT_INTERSECTION", "height_fraction":0.,
                "energy_fraction":0., "path_m":0., "cell_ids":[]}
    if land is not None:
        positions=[]
        for i in hit:
            parts=list(intersections[i].geoms) if hasattr(intersections[i],'geoms') else [intersections[i]]
            positions.extend(line.project(Point(c)) for p in parts for c in p.coords)
        span=LineString([line.interpolate(min(positions)),line.interpolate(max(positions))])
        if span.intersection(land).length>1:
            return {"status":"LAND_BETWEEN_HABITAT","height_fraction":None,
                    "energy_fraction":None,"path_m":sum(lengths),"cell_ids":hit}
    invalid = [i for i in hit if not 4 <= float(depths[i])+level <= 10]
    if invalid:
        return {"status":"OUTSIDE_DEPTH_DOMAIN", "height_fraction":None,
                "energy_fraction":None, "path_m":sum(lengths), "cell_ids":hit,
                "invalid_cell_ids":invalid}
    tau = sum(lengths[i]*damping(float(depths[i])+level,method) for i in hit)
    return {"status":"MODELLED_UNVALIDATED", **effect(tau),
            "path_m":sum(lengths), "cell_ids":hit}


def sample_bundle(polygons, depths, bearing, spacing_m=5, water_level_m=0, method="interpolated", land=None):
    """Uniform ray quadrature over union-projected habitat width.

    Width-weighted transmission preserves separate rays and does not imply
    that a 50 m cell is crossed along its whole diagonal. Conditional on
    equal incident energy on all rays. Range is geometric variation, not CI.
    """
    if finite(spacing_m,'ray spacing')<=0:raise ValueError('Ray spacing must be positive')
    if len(polygons)!=len(depths):raise ValueError('Each polygon needs one depth')
    if not polygons:
        return {"status":"NO_HABITAT", "height_fraction":None,"energy_fraction":None,"rays":[]}
    u=direction_vector(bearing); v=np.array([u[1],-u[0]])
    centre=unary_union(polygons).centroid
    along=np.dot([centre.x,centre.y],u)
    intervals=projected_intervals(polygons,bearing)
    rows=[]
    for lo,hi in intervals:
        n=max(1,int(math.ceil((hi-lo)/spacing_m))); width=(hi-lo)/n
        for q in range(n):
            p=along*u+(lo+(q+.5)*width)*v
            r=ray_effect(polygons,depths,Point(p),bearing,water_level_m,method,land)
            rows.append({**r,"weight_m":width})
    valid=[r for r in rows if r['energy_fraction'] is not None]
    width=sum(hi-lo for lo,hi in intervals)
    valid_width=sum(r['weight_m'] for r in valid)
    full=math.isclose(valid_width,width,abs_tol=1e-6)
    invalid_statuses=sorted(set(r['status'] for r in rows if r['energy_fraction'] is None))
    return {"status":"MODELLED_UNVALIDATED" if full else "PARTIAL_MODEL_DOMAIN",
            "invalid_reasons":invalid_statuses,
            "height_fraction":sum(r['height_fraction']*r['weight_m'] for r in valid)/width if full else None,
            "energy_fraction":sum(r['energy_fraction']*r['weight_m'] for r in valid)/width if full else None,
            "wave_intercept_m":width, "envelope_width_m":intervals[-1][1]-intervals[0][0],
            "valid_intercept_m":valid_width, "coverage_fraction":valid_width/width,
            "path_m_mean":sum(r['path_m']*r['weight_m'] for r in rows)/width,
            "height_ray_range":[min(r['height_fraction'] for r in valid),max(r['height_fraction'] for r in valid)] if valid else None,
            "n_rays":len(rows)}


def path_status(origin, receptor, land, coast, bearing, tolerance_degrees=30,
                endpoint_allowance_m=30):
    """Conservative straight-line geographic screen, not a protection claim.

    Shore-end distance allows a short inland setback, never passage through
    an intervening island. Crossing any shoreline earlier is blocked even
    when an incomplete polygonised land mask misses the island.
    """
    delta=np.array([receptor.x-origin.x,receptor.y-origin.y]); dist=float(np.linalg.norm(delta))
    if dist == 0:
        return {"status":"COLOCATED_REVIEW", "distance_m":0.,"angle_difference_deg":None}
    travel=math.degrees(math.atan2(delta[0],delta[1]))%360
    difference=abs((travel-bearing+180)%360-180)
    line=LineString([origin,receptor])
    if difference > tolerance_degrees:
        status="OUTSIDE_DIRECTION_SCREEN"
    elif land is None or coast is None:
        status="LAND_MASK_UNAVAILABLE"
    elif land.covers(origin):
        status="HABITAT_LAND_CONFLICT"
    else:
        # Exclude only the receptor's last short setback and 2 m at the source.
        inner=LineString([line.interpolate(min(2,dist/4)),line.interpolate(max(dist-endpoint_allowance_m,dist/2))])
        blocked=(inner.intersection(land).length > 1 or inner.intersects(coast))
        status="LAND_BLOCKED" if blocked else "DIRECTIONALLY_PLAUSIBLE_UNVALIDATED"
    return {"status":status,"distance_m":dist,"angle_difference_deg":difference,
            "bearing_to_receptor_deg":travel}


def avoided_damage(without=None, with_habitat=None, probabilities=None, *, validated=False):
    """Integrate a complete exceedance-loss curve; unknowns stay unknown.

    A supported exact zero remains possible. Production inputs must include
    both probability endpoints, matched receptor losses and validation.
    No proxy from a wave percentage is accepted here.
    """
    missing = without is None or with_habitat is None or probabilities is None
    if missing or not validated:
        return {"status":"NOT_QUANTIFIED","eur_per_year":None,
                "reason":"Validated receptor hazard, exposure, event probabilities and damage functions are required"}
    a=np.array(without,dtype=float); b=np.array(with_habitat,dtype=float); p=np.array(probabilities,dtype=float)
    if len(a)<2 or len(a)!=len(b) or len(a)!=len(p) or not all(np.isfinite(x).all() for x in [a,b,p]):
        raise ValueError("Complete equal-length finite damage curves required")
    if p[0]!=0 or p[-1]!=1 or np.any(np.diff(p)<=0) or np.any(a<0) or np.any(b<0):
        raise ValueError("Exceedance probabilities must increase from 0 to 1; damages must be non-negative")
    if np.any(np.diff(a)>0) or np.any(np.diff(b)>0):
        raise ValueError("Exceedance-loss curves must not increase with probability")
    value=float(np.trapezoid(a-b,p))
    return {"status":"QUANTIFIED_ZERO" if value==0 else "QUANTIFIED","eur_per_year":value}
