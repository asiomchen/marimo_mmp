export class AnywidgetModelStub {
  constructor(values = {}) {
    this.values = { ...values };
    this.listeners = new Map();
    this.saved = [];
  }

  get(name) {
    return this.values[name];
  }

  set(name, value) {
    this.values[name] = value;
    this.emit(`change:${name}`);
  }

  save_changes() {
    this.saved.push(structuredClone(this.values));
  }

  on(event, callback) {
    const callbacks = this.listeners.get(event) || new Set();
    callbacks.add(callback);
    this.listeners.set(event, callbacks);
  }

  off(event, callback) {
    const callbacks = this.listeners.get(event);
    callbacks?.delete(callback);
    if (callbacks?.size === 0) this.listeners.delete(event);
  }

  emit(event) {
    for (const callback of [...(this.listeners.get(event) || [])]) callback();
  }

  listenerCount(event = null) {
    if (event) return this.listeners.get(event)?.size || 0;
    return [...this.listeners.values()].reduce((count, callbacks) => count + callbacks.size, 0);
  }
}

export function modelState(overrides = {}) {
  return {
    data: {
      properties: ["pIC50", "pKi"],
      controlOptions: {
        radii: [0, 1],
        maxSupport: 10,
        maxEffect: 2,
        evidenceThresholds: { moderate: 2, strong: 5 },
      },
      products: [],
      fromGroups: [],
      groups: [],
      shown: 0,
      matching: 0,
      warnings: [],
      querySmiles: null,
      queryDepictionId: null,
    },
    depictions: {},
    selected_id: null,
    property_name: "pIC50",
    direction: "higher",
    filters: { direction: "all", min_abs_effect: 0, min_support: 1, radii: null, quality: null, text: "" },
    max_nodes: 100,
    height: 600,
    _control_request: {},
    _control_response: { revision: 0, ok: true, error: null },
    ...overrides,
  };
}
