import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import OntologyRenameDialog from "../OntologyRenameDialog";

const put = jest.fn();

jest.mock("@/lib/api-client", () => ({
  api: {
    put: (...args: unknown[]) => put(...args),
  },
  ApiError: class ApiError extends Error {
    body: { message: string };
    status: number;
    constructor(status: number, body: { message: string }) {
      super(body.message);
      this.status = status;
      this.body = body;
    }
  },
}));

describe("OntologyRenameDialog", () => {
  beforeEach(() => {
    put.mockReset();
    put.mockResolvedValue({});
  });

  it("submits trimmed name and description via PUT", async () => {
    const onSaved = jest.fn();
    const onClose = jest.fn();
    render(
      <OntologyRenameDialog
        open
        ontologyKey="onto_1"
        initialName="Old"
        initialDescription="Desc"
        onClose={onClose}
        onSaved={onSaved}
      />,
    );

    fireEvent.change(screen.getByLabelText(/Display name/i), {
      target: { value: "  New Name  " },
    });
    fireEvent.change(document.getElementById("ont-rename-desc") as HTMLTextAreaElement, {
      target: { value: "  New desc  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(put).toHaveBeenCalledWith("/api/v1/ontology/library/onto_1", {
        name: "New Name",
        description: "New desc",
      });
    });
    expect(onSaved).toHaveBeenCalledWith("New Name", "onto_1");
    expect(onClose).toHaveBeenCalled();
  });

  it("blocks empty name", async () => {
    const onSaved = jest.fn();
    render(
      <OntologyRenameDialog
        open
        ontologyKey="x"
        initialName="A"
        initialDescription=""
        onClose={() => {}}
        onSaved={onSaved}
      />,
    );

    fireEvent.change(screen.getByLabelText(/Display name/i), {
      target: { value: "   " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(screen.getByText("Name is required")).toBeInTheDocument();
    });
    expect(put).not.toHaveBeenCalled();
    expect(onSaved).not.toHaveBeenCalled();
  });
});
