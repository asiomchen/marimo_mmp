import type { AbsolutePosition, Position } from "./types";

export function radialRings<T extends { id: string }>(items: T[], startRadius: number, footprint: number, gap = 12): {
  positions: Map<string, Position>;
  outerRadius: number;
} {
  const positions = new Map<string, Position>();
  let cursor = 0;
  let radius = startRadius;
  while (cursor < items.length) {
    const spacing = footprint + gap;
    const angleStep = 2 * Math.asin(Math.min(1, spacing / (2 * radius)));
    const capacity = Math.max(1, Math.floor((Math.PI * 2) / angleStep));
    const count = Math.min(capacity, items.length - cursor);
    for (let index = 0; index < count; index += 1) {
      const angle = -Math.PI / 2 + (Math.PI * 2 * index) / count;
      const item = items[cursor + index];
      if (item) positions.set(item.id, { radius, angle });
    }
    cursor += count;
    if (cursor < items.length) radius += spacing;
  }
  return { positions, outerRadius: items.length ? radius + footprint / 2 : startRadius };
}

export function absolutePosition(position: Position, center: number): AbsolutePosition {
  return {
    ...position,
    x: center + Math.cos(position.angle) * position.radius,
    y: center + Math.sin(position.angle) * position.radius,
  };
}

export function requiredPosition(positions: Map<string, AbsolutePosition>, id: string): AbsolutePosition {
  const position = positions.get(id);
  if (!position) throw new Error(`Missing layout position for ${id}`);
  return position;
}
