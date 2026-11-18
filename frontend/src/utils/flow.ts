// Geometry for the monitoring board: pipes are straight lines and horizontal S-curves, and a request
// travels along a chain of them. Computed here rather than measured from the DOM, so it stays cheap.

export interface Point { x: number; y: number }
export type Segment = { kind: "line" | "curve"; a: Point; b: Point };

/** An S-curve that leaves `a` and enters `b` horizontally. */
export function curvePath(a: Point, b: Point): string {
  const mid = (a.x + b.x) / 2;
  return `M${a.x} ${a.y}C${mid} ${a.y} ${mid} ${b.y} ${b.x} ${b.y}`;
}

function pointOn(segment: Segment, t: number): Point {
  const { a, b } = segment;
  if (segment.kind === "line") return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
  // Cubic Bezier with control points (mid, a.y) and (mid, b.y).
  const mid = (a.x + b.x) / 2;
  const u = 1 - t;
  const w0 = u * u * u, w1 = 3 * u * u * t, w2 = 3 * u * t * t, w3 = t * t * t;
  return { x: w0 * a.x + w1 * mid + w2 * mid + w3 * b.x, y: w0 * a.y + w1 * a.y + w2 * b.y + w3 * b.y };
}

function lengthOf(segment: Segment): number {
  if (segment.kind === "line") return Math.hypot(segment.b.x - segment.a.x, segment.b.y - segment.a.y);
  let total = 0;
  let last = segment.a;
  for (let step = 1; step <= 16; step++) {
    const next = pointOn(segment, step / 16);
    total += Math.hypot(next.x - last.x, next.y - last.y);
    last = next;
  }
  return total;
}

export interface Route { length: number; at: (fraction: number) => Point }

/** A path through several segments, walked at an even speed. */
export function route(segments: Segment[]): Route {
  const lengths = segments.map(lengthOf);
  const length = lengths.reduce((sum, item) => sum + item, 0);
  return {
    length,
    at(fraction: number) {
      if (!segments.length) return { x: 0, y: 0 };
      let distance = Math.min(1, Math.max(0, fraction)) * length;
      for (let index = 0; index < segments.length; index++) {
        if (distance <= lengths[index] || index === segments.length - 1) {
          return pointOn(segments[index], lengths[index] ? Math.min(1, distance / lengths[index]) : 1);
        }
        distance -= lengths[index];
      }
      return segments[segments.length - 1].b;
    },
  };
}

/** Rough text width for the board's labels, so pills and truncation fit without measuring. */
export function textWidth(text: string, size: number): number {
  return text.length * size * 0.56;
}

export function clip(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}
