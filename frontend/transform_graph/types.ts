export type Evidence = "Strong" | "Moderate" | "Exploratory";
export type Direction = "all" | "gain" | "loss" | "neutral";
export type PropertyDirection = "higher" | "lower";
export type TimerId = ReturnType<typeof globalThis.setTimeout>;
export type FrameId = ReturnType<typeof globalThis.requestAnimationFrame>;

export interface TransformFilters {
  effect: Direction;
  min_abs_effect: number;
  min_support: number;
  radii: number[] | null;
  quality: Evidence[] | null;
  text: string;
}

export interface ControlState {
  property_name: string;
  direction: PropertyDirection;
  filters: TransformFilters;
  max_nodes: number;
}

export interface ControlPatch {
  property_name?: string;
  direction?: PropertyDirection;
  filters?: Partial<TransformFilters>;
  max_nodes?: number;
}

export interface ControlRequest extends ControlState {
  revision: number;
}

export interface ControlResponse {
  revision: number;
  ok: boolean;
  error: string | null;
}

export interface Product {
  id: string;
  smiles: string;
  group: string;
  median: number;
  count: number;
  evidence: Evidence;
  radius: number;
  std: number | null;
  min: number | null;
  q1: number | null;
  q3: number | null;
  max: number | null;
  pValue: number | null;
  missing: string[];
  depictionId: string;
}

export interface RuleGroup {
  id: string;
  environmentId: number;
  fromGroup: string;
  from: string;
  to: string;
  fromDepictionId: string;
  toDepictionId: string;
  smarts: string | null;
  pseudosmiles: string | null;
  radius: number;
  median: number;
  min: number | null;
  max: number | null;
  count: number;
  evidence: Evidence;
}

export interface FromGroup {
  id: string;
  from: string;
  fromDepictionId: string;
  ruleIds: string[];
  productCount: number;
  ruleCount: number;
  gainCount: number;
  lossCount: number;
  neutralCount: number;
  totalSupport: number;
  aggregateMedian: number;
  effectMin: number;
  effectMax: number;
}

export interface GraphData {
  properties: string[];
  controlOptions: {
    radii: number[];
    maxSupport: number;
    maxEffect: number;
    evidenceThresholds: { moderate: number; strong: number };
  };
  querySmiles: string | null;
  queryDepictionId: string | null;
  products: Product[];
  fromGroups: FromGroup[];
  groups: RuleGroup[];
  shown: number;
  matching: number;
  truncated: boolean;
  warnings: string[];
  hasMmpdb: boolean;
}

export interface WidgetState {
  data: GraphData;
  depictions: Record<string, string>;
  selected_id: string | null;
  property_name: string;
  direction: PropertyDirection;
  filters: TransformFilters;
  max_nodes: number;
  height: number;
  _control_request: Partial<ControlRequest>;
  _control_response: ControlResponse;
}

export type ModelCallback = () => void;

export interface AnywidgetModel {
  get<K extends keyof WidgetState>(name: K): WidgetState[K];
  set<K extends keyof WidgetState>(name: K, value: WidgetState[K]): void;
  save_changes(): void;
  on(event: `change:${keyof WidgetState}`, callback: ModelCallback): void;
  off(event: `change:${keyof WidgetState}`, callback: ModelCallback): void;
}

export interface Controls {
  rail: HTMLDivElement;
  property: HTMLSelectElement;
  optimum: HTMLSelectElement;
  direction: HTMLSelectElement;
  effect: HTMLInputElement;
  effectOutput: HTMLOutputElement;
  support: HTMLInputElement;
  supportOutput: HTMLOutputElement;
  radius: HTMLDivElement;
  quality: HTMLDivElement;
  search: HTMLInputElement;
  searchPending: () => boolean;
  signal: AbortSignal;
  submitControls: (patch: ControlPatch) => void;
}

export interface ControlSync {
  submit: (patch: ControlPatch) => void;
  requestChanged: ModelCallback;
  responseChanged: ModelCallback;
  acceptedChanged: ModelCallback;
  current: () => ControlState;
}

export interface ShellRefs {
  el: HTMLElement;
  frame: HTMLDivElement;
  toggle: HTMLButtonElement;
  counter: HTMLDivElement;
  toolbar: HTMLDivElement;
  status: HTMLParagraphElement;
  stage: HTMLDivElement;
  canvas: SVGElement;
  tooltip: HTMLElement;
  notices: HTMLDivElement;
  controls: Controls;
  signal: AbortSignal;
}

export interface ViewRefs extends ShellRefs {
  controlSync: ControlSync;
  setViewTimeout: (callback: () => void, delay: number) => TimerId;
  requestFrame: (callback: () => void) => FrameId;
  layoutSize?: number;
}

export interface Position {
  radius: number;
  angle: number;
  x?: number;
  y?: number;
}

export type AbsolutePosition = Required<Position>;
export type MetricEntry = [string, string];
export type TooltipFill = (tooltip: HTMLElement) => void;
