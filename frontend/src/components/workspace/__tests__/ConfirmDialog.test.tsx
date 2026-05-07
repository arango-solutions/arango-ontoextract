import { render, screen, fireEvent } from "@testing-library/react";
import ConfirmDialog from "../ConfirmDialog";

describe("ConfirmDialog", () => {
  describe("plain mode", () => {
    it("does not render when open=false", () => {
      render(
        <ConfirmDialog
          open={false}
          title="Delete run?"
          message="run-1 will be removed."
          onConfirm={jest.fn()}
          onClose={jest.fn()}
        />,
      );

      expect(screen.queryByRole("dialog")).toBeNull();
    });

    it("renders title, message, and danger-styled Confirm by default", () => {
      render(
        <ConfirmDialog
          open
          title="Delete run?"
          message="run-1 will be removed."
          confirmLabel="Delete"
          onConfirm={jest.fn()}
          onClose={jest.fn()}
        />,
      );

      const dialog = screen.getByRole("dialog");
      expect(dialog).toHaveAttribute("aria-modal", "true");
      expect(screen.getByText("Delete run?")).toBeInTheDocument();
      expect(screen.getByText("run-1 will be removed.")).toBeInTheDocument();

      const confirm = screen.getByRole("button", { name: "Delete" });
      expect(confirm).not.toBeDisabled();
      expect(confirm.className).toContain("bg-red-");
    });

    it("Confirm fires onConfirm; Cancel fires onClose", () => {
      const onConfirm = jest.fn();
      const onClose = jest.fn();
      render(
        <ConfirmDialog
          open
          title="Delete?"
          message="."
          confirmLabel="Delete"
          onConfirm={onConfirm}
          onClose={onClose}
        />,
      );

      fireEvent.click(screen.getByRole("button", { name: "Delete" }));
      expect(onConfirm).toHaveBeenCalledTimes(1);

      fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it("× close button fires onClose", () => {
      const onClose = jest.fn();
      render(
        <ConfirmDialog
          open
          title="t"
          message="m"
          onConfirm={jest.fn()}
          onClose={onClose}
        />,
      );

      fireEvent.click(screen.getByRole("button", { name: /close/i }));
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it("backdrop click fires onClose; clicks inside the dialog do not", () => {
      const onClose = jest.fn();
      render(
        <ConfirmDialog
          open
          title="t"
          message="m"
          onConfirm={jest.fn()}
          onClose={onClose}
        />,
      );

      const dialog = screen.getByRole("dialog");
      fireEvent.mouseDown(dialog);
      expect(onClose).not.toHaveBeenCalled();

      const backdrop = dialog.parentElement!;
      fireEvent.mouseDown(backdrop);
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it("Escape key fires onClose", () => {
      const onClose = jest.fn();
      render(
        <ConfirmDialog
          open
          title="t"
          message="m"
          onConfirm={jest.fn()}
          onClose={onClose}
        />,
      );

      fireEvent.keyDown(document, { key: "Escape" });
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it("renders indigo (non-danger) styling when danger=false", () => {
      render(
        <ConfirmDialog
          open
          title="t"
          message="m"
          confirmLabel="Proceed"
          danger={false}
          onConfirm={jest.fn()}
          onClose={jest.fn()}
        />,
      );

      const confirm = screen.getByRole("button", { name: "Proceed" });
      expect(confirm.className).toContain("bg-indigo-");
      expect(confirm.className).not.toContain("bg-red-");
    });
  });

  describe("typed-name mode", () => {
    const typedName = {
      expected: "Demo Ontology",
      label: "Type the ontology name to confirm:",
    };

    it("disables Confirm until the input matches the expected string", () => {
      const onConfirm = jest.fn();
      render(
        <ConfirmDialog
          open
          title="Delete ontology?"
          message="This cascades to classes / properties / edges."
          confirmLabel="Delete"
          typedName={typedName}
          onConfirm={onConfirm}
          onClose={jest.fn()}
        />,
      );

      const confirm = screen.getByRole("button", { name: "Delete" });
      expect(confirm).toBeDisabled();

      fireEvent.click(confirm);
      expect(onConfirm).not.toHaveBeenCalled();

      const input = screen.getByLabelText(typedName.label);
      fireEvent.change(input, { target: { value: "Demo Ontolog" } });
      expect(confirm).toBeDisabled();

      fireEvent.change(input, { target: { value: "Demo Ontology" } });
      expect(confirm).not.toBeDisabled();

      fireEvent.click(confirm);
      expect(onConfirm).toHaveBeenCalledTimes(1);
    });

    it("treats the input as case- and whitespace-sensitive", () => {
      render(
        <ConfirmDialog
          open
          title="t"
          message="m"
          confirmLabel="Delete"
          typedName={typedName}
          onConfirm={jest.fn()}
          onClose={jest.fn()}
        />,
      );

      const confirm = screen.getByRole("button", { name: "Delete" });
      const input = screen.getByLabelText(typedName.label);

      fireEvent.change(input, { target: { value: "demo ontology" } });
      expect(confirm).toBeDisabled();

      fireEvent.change(input, { target: { value: " Demo Ontology" } });
      expect(confirm).toBeDisabled();
    });

    it("Enter inside the input fires onConfirm only once the gate is satisfied", () => {
      const onConfirm = jest.fn();
      render(
        <ConfirmDialog
          open
          title="t"
          message="m"
          confirmLabel="Delete"
          typedName={typedName}
          onConfirm={onConfirm}
          onClose={jest.fn()}
        />,
      );

      const input = screen.getByLabelText(typedName.label);

      fireEvent.keyDown(input, { key: "Enter" });
      expect(onConfirm).not.toHaveBeenCalled();

      fireEvent.change(input, { target: { value: typedName.expected } });
      fireEvent.keyDown(input, { key: "Enter" });
      expect(onConfirm).toHaveBeenCalledTimes(1);
    });

    it("clears the typed value when reopened", () => {
      const { rerender } = render(
        <ConfirmDialog
          open
          title="t"
          message="m"
          confirmLabel="Delete"
          typedName={typedName}
          onConfirm={jest.fn()}
          onClose={jest.fn()}
        />,
      );

      const input = screen.getByLabelText(typedName.label) as HTMLInputElement;
      fireEvent.change(input, { target: { value: typedName.expected } });
      expect(input.value).toBe(typedName.expected);

      rerender(
        <ConfirmDialog
          open={false}
          title="t"
          message="m"
          confirmLabel="Delete"
          typedName={typedName}
          onConfirm={jest.fn()}
          onClose={jest.fn()}
        />,
      );

      rerender(
        <ConfirmDialog
          open
          title="t"
          message="m"
          confirmLabel="Delete"
          typedName={typedName}
          onConfirm={jest.fn()}
          onClose={jest.fn()}
        />,
      );

      const reopenedInput = screen.getByLabelText(typedName.label) as HTMLInputElement;
      expect(reopenedInput.value).toBe("");
    });
  });
});
