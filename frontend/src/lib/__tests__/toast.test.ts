/**
 * @jest-environment node
 *
 * Module-level toast queue (`src/lib/toast.ts`) — the singleton-emitter
 * pattern that lets pure helpers (context-menu builders, drag-and-drop
 * handlers) emit user-facing notifications without threading a React
 * context. Tests cover:
 *
 *  * default kind + duration (info / 5000 ms)
 *  * subscribe gets the current queue synchronously (no flash-of-empty)
 *  * dismissToast / clearToasts are idempotent
 *  * misbehaving listeners do not poison the chain
 *  * ids are monotonic so two consecutive pushes can be told apart
 */

import {
  clearToasts,
  dismissToast,
  getToastsSnapshot,
  pushToast,
  subscribeToasts,
} from "@/lib/toast";

describe("toast queue", () => {
  beforeEach(() => {
    clearToasts();
    jest.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    clearToasts();
    jest.restoreAllMocks();
  });

  it("pushToast returns a unique id and stamps defaults", () => {
    const id1 = pushToast({ message: "first" });
    const id2 = pushToast({ message: "second" });
    expect(id1).not.toEqual(id2);

    const snap = getToastsSnapshot();
    expect(snap).toHaveLength(2);
    expect(snap[0]).toMatchObject({
      id: id1,
      message: "first",
      kind: "info",
      durationMs: 5000,
    });
    expect(typeof snap[0].createdAt).toBe("number");
    expect(snap[1].id).toBe(id2);
  });

  it("respects explicit kind / durationMs / action overrides", () => {
    const onClick = jest.fn();
    pushToast({
      message: "with action",
      kind: "success",
      durationMs: 0,
      action: { label: "Undo", onClick },
    });
    const snap = getToastsSnapshot();
    expect(snap[0].kind).toBe("success");
    expect(snap[0].durationMs).toBe(0);
    expect(snap[0].action?.label).toBe("Undo");
    expect(snap[0].action?.onClick).toBe(onClick);
  });

  it("delivers the current queue synchronously on subscribe", () => {
    pushToast({ message: "pre-existing" });
    const received: number[] = [];
    const unsubscribe = subscribeToasts((toasts) => {
      received.push(toasts.length);
    });
    // First synchronous delivery -- avoids the flash-of-empty pattern
    // that breaks the host's render-then-effect order.
    expect(received).toEqual([1]);
    pushToast({ message: "after subscribe" });
    expect(received).toEqual([1, 2]);
    unsubscribe();
  });

  it("unsubscribe stops further deliveries", () => {
    const received: number[] = [];
    const unsubscribe = subscribeToasts((toasts) => {
      received.push(toasts.length);
    });
    pushToast({ message: "one" });
    unsubscribe();
    pushToast({ message: "two" });
    // Initial empty delivery + the single push before unsubscribe.
    expect(received).toEqual([0, 1]);
  });

  it("dismissToast removes the entry and emits exactly once", () => {
    const id = pushToast({ message: "drop me" });
    const received: number[] = [];
    subscribeToasts((toasts) => {
      received.push(toasts.length);
    });
    received.length = 0;
    dismissToast(id);
    expect(getToastsSnapshot()).toHaveLength(0);
    expect(received).toEqual([0]);
  });

  it("dismissToast is idempotent for an unknown id", () => {
    pushToast({ message: "keep me" });
    const before = getToastsSnapshot();
    const received: number[] = [];
    subscribeToasts((toasts) => {
      received.push(toasts.length);
    });
    received.length = 0;
    dismissToast("toast-never-existed");
    expect(getToastsSnapshot()).toEqual(before);
    // No emit when nothing changed -- prevents render storms on a
    // double-click of the dismiss button.
    expect(received).toEqual([]);
  });

  it("clearToasts is idempotent", () => {
    const received: number[] = [];
    subscribeToasts((toasts) => {
      received.push(toasts.length);
    });
    received.length = 0;
    clearToasts();
    expect(received).toEqual([]); // already empty -- no emit.
    pushToast({ message: "x" });
    received.length = 0;
    clearToasts();
    expect(received).toEqual([0]);
  });

  it("isolates a throwing listener from other subscribers", () => {
    const ok = jest.fn();
    subscribeToasts(() => {
      throw new Error("nope");
    });
    subscribeToasts(ok);
    pushToast({ message: "after broken listener" });
    // The good subscriber still receives both the initial delivery and
    // the push notification.
    expect(ok).toHaveBeenCalledTimes(2);
    // The thrown error is surfaced to the dev console so the bug
    // isn't silently swallowed.
    expect(console.error).toHaveBeenCalled();
  });
});
