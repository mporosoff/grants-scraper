// Small DOM/event fixture for shell contracts; no browser or E2E runner.
import { load } from "cheerio";
export function shellDom(html, { popover = true, deferredClose = false } = {}) {
  const $ = load(html);
  const wrappers = new Map(), listeners = new Map(), observers = [];
  const windowListeners = [];
  const nodeOf = value => value?.node || value;
  let document;
  function wrap(node) {
    if (!node) return null;
    if (wrappers.has(node)) return wrappers.get(node);
    const el = {
      node, style: { setProperty(name, value) { this[name] = value; }, removeProperty(name) { delete this[name]; } }, scrollLeft: 0, scrollTop: 0,
      get tagName() { return node.name?.toUpperCase(); },
      get id() { return $(node).attr("id"); }, set id(value) { $(node).attr("id", value); },
      get className() { return $(node).attr("class"); }, set className(value) { $(node).attr("class", value); },
      get textContent() { return $(node).text(); }, set textContent(value) { $(node).text(value); },
      get innerHTML() { return $(node).html(); }, set innerHTML(value) { $(node).html(value); },
      get value() { return $(node).val() || ""; }, set value(value) { $(node).val(value); },
      get hidden() { return $(node).attr("hidden") !== undefined; }, set hidden(value) { value ? $(node).attr("hidden", "") : $(node).removeAttr("hidden"); },
      get disabled() { return $(node).attr("disabled") !== undefined; }, set disabled(value) { value ? $(node).attr("disabled", "") : $(node).removeAttr("disabled"); },
      get checked() { return $(node).attr("checked") !== undefined; }, set checked(value) { value ? $(node).attr("checked", "") : $(node).removeAttr("checked"); },
      get open() { return $(node).attr("open") !== undefined; }, set open(value) { value ? $(node).attr("open", "") : $(node).removeAttr("open"); },
      get isConnected() { return $(node).parents("html").length > 0; },
      get parentElement() { return wrap(node.parent?.type === "tag" ? node.parent : null); },
      get clientWidth() { return 320; },
      get dataset() { return new Proxy({}, { get: (_, key) => $(node).attr(`data-${key.replace(/[A-Z]/g, c => `-${c.toLowerCase()}`)}`) }); },
      classList: { add: value => $(node).addClass(value), remove: value => $(node).removeClass(value), contains: value => $(node).hasClass(value), toggle: (value, on) => $(node).toggleClass(value, on) },
      getAttribute: name => $(node).attr(name) ?? null,
      setAttribute: (name, value) => $(node).attr(name, String(value)),
      removeAttribute: name => $(node).removeAttr(name),
      querySelector: selector => wrap($(node).find(selector)[0]),
      querySelectorAll: selector => $(node).find(selector).toArray().map(wrap),
      closest: selector => wrap($(node).closest(selector)[0]),
      contains: other => other !== document && (node === nodeOf(other) || $(nodeOf(other)).parents().toArray().includes(node)),
      matches: selector => {
        if (selector !== ":popover-open") return $(node).is(selector);
        if (!popover) throw new SyntaxError("Unsupported pseudo-class :popover-open");
        return !!node.popoverOpen;
      },
      getClientRects: () => $(node).parents().addBack().toArray().some(parent => $(parent).attr("hidden") !== undefined) ? [] : [{}],
      getBoundingClientRect: () => el.rect || { left: 0, top: 0, right: 280, bottom: 200, width: 280, height: 200 },
      focus() { document.activeElement = el; dispatch("focusin", el); },
      scrollIntoView() { el.scrolled = true; },
      append: (...values) => values.forEach(value => $(node).append(nodeOf(value))),
      appendChild: value => $(node).append(nodeOf(value)),
      after: value => $(node).after(nodeOf(value)),
      replaceChildren: (...values) => { $(node).empty(); el.append(...values); },
      insertAdjacentHTML: (_, value) => $(node).append(value),
      remove: () => $(node).remove(),
      ...(popover ? {
        showPopover() { node.popoverOpen = true; },
        hidePopover() { node.popoverOpen = false; },
      } : {}),
      showModal() { $(node).attr("open", ""); },
      close() { $(node).removeAttr("open"); deferredClose ? setTimeout(() => dispatch("close", el), 0) : dispatch("close", el); },
      addEventListener(type, listener) { add(type, listener, false, el); },
    };
    wrappers.set(node, el);
    return el;
  }
  function add(type, callback, capture, owner) {
    if (!listeners.has(type)) listeners.set(type, []);
    listeners.get(type).push({ callback, capture: !!capture, owner });
  }
  function dispatch(type, target, extra = {}) {
    const event = { type, target, prevented: false, stopped: false, preventDefault() { this.prevented = true; }, stopImmediatePropagation() { this.stopped = true; }, ...extra };
    const all = [...(listeners.get(type) || [])].sort((a, b) => Number(b.capture) - Number(a.capture));
    for (const { callback, owner } of all) {
      if (event.stopped) break;
      if (!owner || owner.contains(target)) callback(event);
    }
    return event;
  }
  document = {
    body: wrap($("body")[0]), documentElement: wrap($("html")[0]),
    createElement: tag => wrap($(`<${tag}></${tag}>`)[0]),
    getElementById: id => wrap($(`[id="${id}"]`)[0]),
    querySelector: selector => wrap($(selector)[0]),
    querySelectorAll: selector => $(selector).toArray().map(wrap),
    addEventListener: (type, callback, capture) => add(type, callback, capture),
  };
  document.activeElement = document.body;
  const context = {
    document, Map, WeakMap, queueMicrotask, setTimeout, innerHeight: 480, scrollX: 0, scrollY: 0,
    addEventListener: (type, callback) => windowListeners.push({ type, callback }),
    matchMedia: () => ({ addEventListener() {} }),
    MutationObserver: class { constructor(callback) { observers.push(callback); } observe() {} },
  };
  return { context, document, dispatch, listeners, windowListeners, mutate: () => observers.forEach(callback => callback()) };
}
