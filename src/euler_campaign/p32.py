"""In-domain disk area: exact interior disks, clipped inscribed 128-gons at boundaries."""

from math import pi, prod

import numpy as np

P32_METHOD_ID = "disk_box_polygon"
P32_METHOD_VERSION = "v1-128"
POLYGON_VERTICES = 128


def disk_box_areas(centers, normals, radii, extents):
    centers, normals, radii = (np.asarray(v, dtype=float) for v in (centers, normals, radii))
    extents = np.asarray(extents, dtype=float)
    count = len(radii)
    if (centers.shape != (count, 3) or normals.shape != (count, 3)
        or extents.shape != (3,) or not np.all(extents > 0)
        or not all(np.all(np.isfinite(v)) for v in (centers, normals, radii, extents))
        or np.any(radii <= 0)):
        raise ValueError("invalid disk/domain arrays")
    lengths = np.linalg.norm(normals, axis=1)
    if np.any(lengths <= 0):
        raise ValueError("disk normal must be nonzero")
    normals = normals / lengths[:, None]
    projected = radii[:, None] * np.sqrt(np.maximum(0, 1 - normals**2))
    inside = np.all((centers - projected >= 0) & (centers + projected <= extents), axis=1)
    outside = np.any((centers + projected < 0) | (centers - projected > extents), axis=1)
    result = np.where(inside, pi * radii**2, 0.)
    boundary = np.flatnonzero(~inside & ~outside)
    angles = np.arange(POLYGON_VERTICES) * (2 * pi / POLYGON_VERTICES)
    capacity = POLYGON_VERTICES + 6
    for offset in range(0, len(boundary), 256):
        indices = boundary[offset:offset + 256]
        c, n, r = centers[indices], normals[indices], radii[indices]
        axes = np.eye(3)[np.argmin(np.abs(n), axis=1)]
        u = np.cross(n, axes)
        u /= np.linalg.norm(u, axis=1)[:, None]
        v = np.cross(n, u)
        polygon = np.zeros((len(indices), capacity, 3))
        polygon[:, :POLYGON_VERTICES] = c[:, None] + r[:, None, None] * (
            np.cos(angles)[None, :, None] * u[:, None]
            + np.sin(angles)[None, :, None] * v[:, None])
        sizes = np.full(len(indices), POLYGON_VERTICES)
        positions = np.arange(capacity)[None, :]
        rows = np.arange(len(indices))[:, None]
        for axis in range(3):
            for bound, sign in ((0., 1.), (extents[axis], -1.)):
                valid = positions < sizes[:, None]
                end = polygon[rows, (positions + 1) % np.maximum(sizes[:, None], 1)]
                start_distance = sign * (polygon[:, :, axis] - bound)
                end_distance = sign * (end[:, :, axis] - bound)
                start_inside, end_inside = start_distance >= 0, end_distance >= 0
                crosses = valid & (start_inside != end_inside)
                denominator = np.where(crosses, start_distance - end_distance, 1.)
                intersection = polygon + (start_distance / denominator)[:, :, None] * (end - polygon)
                candidates = np.stack((intersection, end), axis=2).reshape(len(indices), -1, 3)
                keep = np.stack((crosses, valid & end_inside), axis=2).reshape(len(indices), -1)
                destinations = np.cumsum(keep, axis=1) - 1
                clipped = np.zeros_like(polygon)
                row_indices, source_indices = np.nonzero(keep)
                clipped[row_indices, destinations[row_indices, source_indices]] = candidates[
                    row_indices, source_indices]
                polygon, sizes = clipped, keep.sum(axis=1)
        end = polygon[rows, (positions + 1) % np.maximum(sizes[:, None], 1)]
        cross = np.cross(polygon, end) * (positions < sizes[:, None])[:, :, None]
        result[indices] = np.abs(np.sum(np.sum(cross, axis=1) * n, axis=1)) / 2
    return result


def measure_domain_p32(case, geometry):
    from .dfn import _domain_extents
    extents = _domain_extents(case.domain)
    volume = prod(extents)
    records = {s.set_id: {"joint_count": 0, "intersecting_joint_count": 0, "area_m2": 0.}
               for s in case.joint_sets}
    count = geometry.count if hasattr(geometry, "count") else len(geometry.joints)
    for start in range(0, count, 65_536):
        stop = min(count, start + 65_536)
        if hasattr(geometry, "centers"):
            centers, normals, radii, ids = (
                np.asarray(getattr(geometry, name)[start:stop])
                for name in ("centers", "normals", "radii", "set_ids"))
        else:
            joints = geometry.joints[start:stop]
            centers = np.array([j.center for j in joints])
            normals = np.array([j.normal for j in joints])
            radii = np.array([j.radius for j in joints])
            ids = np.array([j.set_id for j in joints])
        areas = disk_box_areas(centers, normals, radii, extents)
        for set_id in np.unique(ids):
            if int(set_id) not in records:
                raise ValueError("geometry contains an unknown joint set")
            selected = ids == set_id
            record = records[int(set_id)]
            record["joint_count"] += int(selected.sum())
            record["intersecting_joint_count"] += int((areas[selected] > 0).sum())
            record["area_m2"] += float(areas[selected].sum())
    result = {s.name: records[s.set_id] for s in case.joint_sets}
    result[""] = {key: sum(record[key] for record in records.values())
                  for key in ("joint_count", "intersecting_joint_count", "area_m2")}
    for record in result.values():
        record.update(domain_volume_m3=volume, p32_m2_per_m3=record["area_m2"] / volume,
                      method_id=P32_METHOD_ID, method_version=P32_METHOD_VERSION)
    return result
