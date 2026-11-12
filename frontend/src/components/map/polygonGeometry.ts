import type { GeoJSONPolygon } from '../../types/gis';

export interface PolygonValidationResult {
  valid: boolean;
  reason?: string;
  estimatedAreaKm2: number;
  centroid: [number, number];
}

function orientation(p: [number, number], q: [number, number], r: [number, number]): number {
  const val = (q[1] - p[1]) * (r[0] - q[0]) - (q[0] - p[0]) * (r[1] - q[1]);
  if (Math.abs(val) < 1e-12) return 0;
  return val > 0 ? 1 : 2;
}

function onSegment(p: [number, number], q: [number, number], r: [number, number]): boolean {
  return (
    q[0] <= Math.max(p[0], r[0]) &&
    q[0] >= Math.min(p[0], r[0]) &&
    q[1] <= Math.max(p[1], r[1]) &&
    q[1] >= Math.min(p[1], r[1])
  );
}

function segmentsIntersect(
  p1: [number, number],
  q1: [number, number],
  p2: [number, number],
  q2: [number, number]
): boolean {
  const o1 = orientation(p1, q1, p2);
  const o2 = orientation(p1, q1, q2);
  const o3 = orientation(p2, q2, p1);
  const o4 = orientation(p2, q2, q1);

  if (o1 !== o2 && o3 !== o4) return true;
  if (o1 === 0 && onSegment(p1, p2, q1)) return true;
  if (o2 === 0 && onSegment(p1, q2, q1)) return true;
  if (o3 === 0 && onSegment(p2, p1, q2)) return true;
  if (o4 === 0 && onSegment(p2, q1, q2)) return true;
  return false;
}

export function estimatePolygonAreaKm2(ring: [number, number][]): number {
  if (ring.length < 3) return 0;
  let lonSum = 0;
  let latSum = 0;
  for (const [lon, lat] of ring) {
    lonSum += lon;
    latSum += lat;
  }
  const meanLatRad = ((latSum / ring.length) * Math.PI) / 180;
  const kmPerDegLat = 111.132;
  const kmPerDegLon = 111.32 * Math.cos(meanLatRad);

  let area2 = 0;
  for (let i = 0; i < ring.length; i++) {
    const [x1, y1] = ring[i];
    const [x2, y2] = ring[(i + 1) % ring.length];
    area2 += x1 * kmPerDegLon * (y2 * kmPerDegLat) - x2 * kmPerDegLon * (y1 * kmPerDegLat);
  }
  return Math.abs(area2) * 0.5;
}

export function validateOpenPolygonVertices(vertices: [number, number][]): PolygonValidationResult {
  if (vertices.length < 3) {
    return {
      valid: false,
      reason: 'Add at least 3 vertices on the map to form an exploration polygon.',
      estimatedAreaKm2: 0,
      centroid: vertices[0] || [75.79, 28.0],
    };
  }

  for (const [lon, lat] of vertices) {
    if (!Number.isFinite(lon) || !Number.isFinite(lat) || lon < -180 || lon > 180 || lat < -90 || lat > 90) {
      return {
        valid: false,
        reason: 'Vertices contain out-of-range WGS84 coordinates.',
        estimatedAreaKm2: 0,
        centroid: [0, 0],
      };
    }
  }

  // Check consecutive or non-adjacent edge self-intersections for closed ring
  const n = vertices.length;
  for (let i = 0; i < n; i++) {
    const a1 = vertices[i];
    const a2 = vertices[(i + 1) % n];
    if (Math.hypot(a1[0] - a2[0], a1[1] - a2[1]) < 1e-8) {
      return {
        valid: false,
        reason: 'Polygon contains duplicate adjacent vertices.',
        estimatedAreaKm2: 0,
        centroid: a1,
      };
    }
    for (let j = i + 2; j < n; j++) {
      if (i === 0 && j === n - 1) continue; // adjacent across closure
      const b1 = vertices[j];
      const b2 = vertices[(j + 1) % n];
      if (segmentsIntersect(a1, a2, b1, b2)) {
        return {
          valid: false,
          reason: 'Polygon edges self-intersect; adjust vertices so the boundary does not cross itself.',
          estimatedAreaKm2: 0,
          centroid: a1,
        };
      }
    }
  }

  const areaKm2 = estimatePolygonAreaKm2(vertices);
  const cx = vertices.reduce((acc, v) => acc + v[0], 0) / n;
  const cy = vertices.reduce((acc, v) => acc + v[1], 0) / n;

  if (areaKm2 < 0.01) {
    return {
      valid: false,
      reason: 'Polygon area is too tiny (< 0.01 km²); place wider vertices.',
      estimatedAreaKm2: areaKm2,
      centroid: [cx, cy],
    };
  }

  return {
    valid: true,
    estimatedAreaKm2: Number(areaKm2.toFixed(2)),
    centroid: [cx, cy],
  };
}

export function verticesToGeoJSONPolygon(vertices: [number, number][]): GeoJSONPolygon {
  const closed = vertices.map((v) => [Number(v[0].toFixed(6)), Number(v[1].toFixed(6))]);
  if (
    closed.length > 0 &&
    (closed[0][0] !== closed[closed.length - 1][0] || closed[0][1] !== closed[closed.length - 1][1])
  ) {
    closed.push([...closed[0]]);
  }
  return {
    type: 'Polygon',
    coordinates: [closed],
  };
}

export function geoJSONPolygonToVertices(geometry: GeoJSONPolygon | undefined): [number, number][] {
  const ring = geometry?.coordinates?.[0] || [];
  if (ring.length <= 1) return [];
  const first = ring[0];
  const last = ring[ring.length - 1];
  const open =
    first[0] === last[0] && first[1] === last[1] ? ring.slice(0, -1) : ring.slice();
  return open.map((pt) => [pt[0], pt[1]]);
}
