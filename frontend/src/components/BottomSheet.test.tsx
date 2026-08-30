import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import BottomSheet from "./BottomSheet";

function setup(props: Partial<React.ComponentProps<typeof BottomSheet>> = {}) {
  const onClose = vi.fn();
  const utils = render(
    <BottomSheet open onClose={onClose} title="Signal Detail · NVDA" subtitle="1D · CONFIRMED" {...props}>
      <div>sheet body</div>
    </BottomSheet>,
  );
  return { onClose, ...utils };
}

/** Drag the handle down by `px` and release. */
function drag(px: number) {
  const handle = document.querySelector('[style*="grab"]') as HTMLElement;
  fireEvent.touchStart(handle, { touches: [{ clientY: 500 }] });
  fireEvent.touchMove(handle, { touches: [{ clientY: 500 + px }] });
  fireEvent.touchEnd(handle);
}

afterEach(() => { document.body.style.overflow = ""; });

describe("BottomSheet", () => {
  it("renders nothing when closed", () => {
    setup({ open: false });
    expect(screen.queryByText("sheet body")).not.toBeInTheDocument();
  });

  it("is a labelled modal dialog", () => {
    setup();
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByText("Signal Detail · NVDA")).toBeInTheDocument();
    expect(screen.getByText("1D · CONFIRMED")).toBeInTheDocument();
  });

  // Three dismiss paths, because the Close button alone sits at the top of
  // the sheet — the furthest point from a thumb.
  it("closes on the Close button", () => {
    const { onClose } = setup();
    fireEvent.click(screen.getByLabelText("Close"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes on a backdrop tap", () => {
    const { onClose, container } = setup();
    fireEvent.click(container.querySelector(".bottom-sheet-backdrop")!);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes on Escape", () => {
    const { onClose } = setup();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes when dragged past the threshold", () => {
    const { onClose } = setup();
    drag(150);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("springs back when the drag is too short to count", () => {
    // A short downward drag is usually the start of a scroll, not a dismiss.
    const { onClose, container } = setup();
    drag(40);
    expect(onClose).not.toHaveBeenCalled();
    const sheet = container.querySelector(".bottom-sheet") as HTMLElement;
    expect(sheet.style.transform).toBe("");
  });

  it("ignores an upward drag", () => {
    const { onClose, container } = setup();
    const handle = container.querySelector('[style*="grab"]') as HTMLElement;
    fireEvent.touchStart(handle, { touches: [{ clientY: 500 }] });
    fireEvent.touchMove(handle, { touches: [{ clientY: 300 }] });
    expect((container.querySelector(".bottom-sheet") as HTMLElement).style.transform).toBe("");
    fireEvent.touchEnd(handle);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("locks the page behind it while open, and releases on unmount", () => {
    // Without this, dragging the sheet scrolls the list underneath instead.
    const { unmount } = setup();
    expect(document.body.style.overflow).toBe("hidden");
    unmount();
    expect(document.body.style.overflow).not.toBe("hidden");
  });

  it("stops short of covering the whole screen", () => {
    // The page behind is the context for what the sheet is showing.
    const { container } = setup();
    const sheet = container.querySelector(".bottom-sheet") as HTMLElement;
    expect(sheet.style.maxHeight).toBe("86dvh");
  });

  it("gives the close control a full-size touch target", () => {
    const { container } = setup();
    const close = screen.getByLabelText("Close");
    expect(close.style.minHeight).toBe("44px");
    expect(close.style.minWidth).toBe("44px");
    expect(container).toBeTruthy();
  });
});
