/**
 * @jest-environment jsdom
 *
 * The bottom-centre toast surface bound to the module-level queue in
 * ``src/lib/toast.ts``. Tests cover the contract the rest of the app
 * relies on:
 *
 *  * Empty queue renders nothing (no fixed-position scrim eats clicks).
 *  * Pushing a toast renders it with the right ``data-toast-kind`` and
 *    text.
 *  * Auto-dismiss fires after ``durationMs`` (via jest fake timers).
 *  * Sticky toasts (``durationMs === 0``) never auto-dismiss.
 *  * The action button awaits its async ``onClick`` then dismisses.
 *  * The × button dismisses without firing the action.
 *  * Unmount cancels pending auto-dismiss timers (no late callbacks
 *    landing on an unmounted host -- React 18 warns about that).
 */

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

import ToastHost from "@/components/workspace/ToastHost";
import {
  clearToasts,
  getToastsSnapshot,
  pushToast,
} from "@/lib/toast";

describe("ToastHost", () => {
  beforeEach(() => {
    clearToasts();
  });

  afterEach(() => {
    clearToasts();
    jest.useRealTimers();
  });

  it("renders nothing when the queue is empty", () => {
    const { container } = render(<ToastHost />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a pushed toast with the right kind + message", () => {
    render(<ToastHost />);
    act(() => {
      pushToast({ message: "hello", kind: "success" });
    });
    const host = screen.getByTestId("toast-host");
    expect(host).toBeInTheDocument();
    expect(host).toHaveTextContent("hello");
    const toast = host.querySelector("[data-toast-kind='success']");
    expect(toast).not.toBeNull();
  });

  it("auto-dismisses after durationMs", () => {
    jest.useFakeTimers();
    render(<ToastHost />);
    act(() => {
      pushToast({ message: "fades", durationMs: 200 });
    });
    expect(screen.getByText("fades")).toBeInTheDocument();

    act(() => {
      jest.advanceTimersByTime(250);
    });
    expect(screen.queryByText("fades")).not.toBeInTheDocument();
    expect(getToastsSnapshot()).toHaveLength(0);
  });

  it("does NOT auto-dismiss when durationMs === 0 (sticky)", () => {
    jest.useFakeTimers();
    render(<ToastHost />);
    act(() => {
      pushToast({ message: "sticky", durationMs: 0 });
    });
    act(() => {
      jest.advanceTimersByTime(60_000);
    });
    expect(screen.getByText("sticky")).toBeInTheDocument();
  });

  it("action button awaits its async onClick, then dismisses", async () => {
    const onClick = jest.fn().mockResolvedValue(undefined);
    render(<ToastHost />);
    act(() => {
      pushToast({
        message: "imported FOAF",
        durationMs: 0,
        action: { label: "Undo", onClick },
      });
    });
    fireEvent.click(screen.getByRole("button", { name: /undo/i }));
    await waitFor(() => {
      expect(onClick).toHaveBeenCalledTimes(1);
      expect(screen.queryByText("imported FOAF")).not.toBeInTheDocument();
    });
  });

  it("× button dismisses without firing the action", async () => {
    const onClick = jest.fn();
    render(<ToastHost />);
    act(() => {
      pushToast({
        message: "drop me",
        durationMs: 0,
        action: { label: "Undo", onClick },
      });
    });
    fireEvent.click(screen.getByRole("button", { name: /dismiss/i }));
    expect(onClick).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(screen.queryByText("drop me")).not.toBeInTheDocument();
    });
  });

  it("clears pending timers on unmount", () => {
    jest.useFakeTimers();
    const { unmount } = render(<ToastHost />);
    act(() => {
      pushToast({ message: "racing", durationMs: 500 });
    });
    unmount();
    // The toast is still in the queue (unmount doesn't clear the queue
    // -- a remount would re-render it), but the auto-dismiss timer was
    // cancelled by the host's cleanup so no late ``dismissToast`` lands
    // on a stale host instance.
    act(() => {
      jest.advanceTimersByTime(2000);
    });
    expect(getToastsSnapshot()).toHaveLength(1);
  });
});
