import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { DANIEL_CASE_ID } from "@/mocks/data";
import { BANK_DOC_DANIEL_ID, PAYSTUB_DOC_ID } from "@/mocks/extraction";
import { getExtractionMock, resetMockStore, reviewFieldMock, typeChangesMock } from "@/mocks/store";
import { ReviewWorkspace } from "./review-workspace";

beforeEach(() => resetMockStore());

const renderScreen = async (documentId = PAYSTUB_DOC_ID) => {
  render(
    <ReviewWorkspace
      caseId={DANIEL_CASE_ID}
      documentId={documentId}
      backHref="/underwriting/document-intelligence"
    />,
  );
  await screen.findByText("Extracted fields");
};

describe("ReviewWorkspace on the mock pay stub", () => {
  it("opens on the flagged net pay and draws its box on the page", async () => {
    await renderScreen();
    const box = screen.getByTestId("evidence-box");
    expect(parseFloat(box.style.left)).toBeCloseTo(24.2, 5);
    expect(parseFloat(box.style.top)).toBeCloseTo(40, 5);
    expect(await screen.findByAltText("Page 1")).toHaveAttribute("src", "/mock/paystub-p1.svg");
    expect(screen.getByText("p1-L31")).toBeInTheDocument();
    expect(screen.getByText("1 to look at")).toBeInTheDocument();
  });

  it("moves the box when another field is picked", async () => {
    await renderScreen();
    // "^" because the box on the page is also a button, named "Show Employer name on the page".
    fireEvent.click(screen.getByRole("button", { name: /^Employer name/ }));
    const box = screen.getByTestId("evidence-box");
    expect(parseFloat(box.style.left)).toBeCloseTo(10, 5);
    expect(parseFloat(box.style.top)).toBeCloseTo(7, 5);
    expect(screen.getByText("p1-L02")).toBeInTheDocument();
  });

  it("draws a box for every field, not just the selected one", async () => {
    await renderScreen();
    // 6 pay stub fields, each with a box: 1 selected plus 5 plain.
    expect(screen.getAllByTestId("field-box")).toHaveLength(5);
    expect(screen.getAllByTestId("evidence-box")).toHaveLength(1);
  });

  it("clicking a box on the page selects its field and opens its review form", async () => {
    await renderScreen();
    fireEvent.click(screen.getByRole("button", { name: "Show Employer name on the page" }));
    expect(screen.getByTestId("evidence-box")).toHaveAttribute("data-field", "employer_name");
    expect(screen.getByRole("button", { name: "Confirm value" })).toBeInTheDocument();
    expect(screen.getByText("p1-L02")).toBeInTheDocument();
  });

  it("hovering a field row lights up its box, and leaving puts it back", async () => {
    await renderScreen();
    const row = screen.getByRole("button", { name: /^Employer name/ }).closest("li")!;
    const box = screen.getByRole("button", { name: "Show Employer name on the page" });
    expect(box.className).not.toContain("bg-teal/20");
    fireEvent.mouseEnter(row);
    expect(box.className).toContain("bg-teal/20");
    expect(row).toHaveAttribute("data-highlighted", "true");
    fireEvent.mouseLeave(row);
    expect(box.className).not.toContain("bg-teal/20");
  });

  it("hovering a box on the page lights up its field row", async () => {
    await renderScreen();
    const row = screen.getByRole("button", { name: /^Employer name/ }).closest("li")!;
    fireEvent.mouseEnter(screen.getByRole("button", { name: "Show Employer name on the page" }));
    expect(row).toHaveAttribute("data-highlighted", "true");
  });

  it("zooms the page without moving the selected box", async () => {
    await renderScreen();
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(screen.getByTestId("zoom-level")).toHaveTextContent("150%");
    expect(parseFloat(screen.getByTestId("evidence-box").style.left)).toBeCloseTo(24.2, 5);
  });

  it("a correction keeps the original, clears the flag and updates the document", async () => {
    await renderScreen();
    fireEvent.click(screen.getByRole("button", { name: "Correct" }));
    fireEvent.change(screen.getByLabelText("Corrected value"), { target: { value: "2033.61" } });
    fireEvent.change(screen.getByLabelText("Why is the value being corrected?"), {
      target: { value: "OCR misread the last digit" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));

    expect(await screen.findByText(/Originally read as/)).toBeInTheDocument();
    expect(screen.getByText("2083.61").tagName).toBe("S");
    expect(screen.getByText("2033.61")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Nothing flagged")).toBeInTheDocument());
    expect(screen.queryByText("DI-CHK-02")).not.toBeInTheDocument();
    expect(screen.getByText("Reviewed")).toBeInTheDocument(); // document status chip in the header
  });

  it("asks for a reload when someone else changed the value first", async () => {
    await renderScreen();
    const stale = getExtractionMock(DANIEL_CASE_ID, PAYSTUB_DOC_ID).fields[0];
    // Someone else confirms the same field after this screen loaded.
    reviewFieldMock(DANIEL_CASE_ID, PAYSTUB_DOC_ID, stale.name, {
      action: "confirm",
      expected_version: stale.version!,
    });
    fireEvent.click(screen.getByRole("button", { name: "Confirm value" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("This value changed since you opened it");

    fireEvent.click(screen.getByRole("button", { name: "Reload" }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(screen.getByText("Confirmed")).toBeInTheDocument();
  });

  it("links back to the document list", async () => {
    await renderScreen();
    expect(screen.getByRole("link", { name: /Back to documents/ })).toHaveAttribute(
      "href",
      "/underwriting/document-intelligence",
    );
  });
});

describe("ReviewWorkspace on a three-page bank statement", () => {
  it("jumps to the page a field is on and shows that page's image and box", async () => {
    await renderScreen(BANK_DOC_DANIEL_ID);
    expect(screen.getByText("Page 1 of 3")).toBeInTheDocument();
    // The picture link is asked for after the screen loads, so wait for it.
    expect(await screen.findByAltText("Page 1")).toHaveAttribute("src", "/mock/bank-p1.svg");

    fireEvent.click(screen.getByRole("button", { name: /^Ending balance/ }));
    expect(screen.getByText("Page 3 of 3")).toBeInTheDocument();
    expect(await screen.findByAltText("Page 3")).toHaveAttribute("src", "/mock/bank-p3.svg");
    expect(parseFloat(screen.getByTestId("evidence-box").style.top)).toBeCloseTo(57.4, 5);
    expect(screen.getByText("p3-L18")).toBeInTheDocument();
  });

  it("flipping pages shows the other page's boxes and keeps the selected field", async () => {
    await renderScreen(BANK_DOC_DANIEL_ID);
    fireEvent.click(screen.getByRole("button", { name: /^Ending balance/ }));
    fireEvent.click(screen.getByRole("button", { name: "Previous page" }));
    fireEvent.click(screen.getByRole("button", { name: "Previous page" }));
    expect(screen.getByText("Page 1 of 3")).toBeInTheDocument();
    // The selected field lives on page 3, so page 1 shows only the plain boxes for its own fields.
    expect(screen.queryByTestId("evidence-box")).not.toBeInTheDocument();
    expect(screen.getAllByTestId("field-box")).toHaveLength(2);
    // The field list still has Ending balance selected, with its review form open.
    expect(screen.getByRole("button", { name: "Confirm value" })).toBeInTheDocument();
  });
});

describe("ReviewWorkspace changing the document type", () => {
  const openDialog = () => fireEvent.click(screen.getByRole("button", { name: "Change type" }));

  it("opens the type dialog with the current type already chosen", async () => {
    await renderScreen();
    openDialog();
    expect(screen.getByText("Change document type")).toBeInTheDocument();
    expect(screen.getByLabelText("Document type")).toHaveValue("pay_stub");
  });

  it("confirming the same type just closes the dialog, with no re-reading", async () => {
    await renderScreen();
    openDialog();
    fireEvent.click(screen.getByRole("button", { name: "Confirm type" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.queryByText(/Re-reading with the chosen type/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm value" })).toBeEnabled();
  });

  it("a different type pauses reviewing and shows progress, then loads the new reading", async () => {
    await renderScreen();
    openDialog();
    fireEvent.change(screen.getByLabelText("Document type"), { target: { value: "w2" } });
    fireEvent.change(screen.getByLabelText("Reason (optional)"), { target: { value: "It is a W-2" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm type" }));

    // Progress shows and the field actions are locked while it re-reads.
    expect(await screen.findByText(/Re-reading with the chosen type/)).toBeInTheDocument();
    expect(screen.getByText(/Reviewing is paused/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm value" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Change type" })).toBeDisabled();
    expect(typeChangesMock()).toHaveLength(1);
    expect(typeChangesMock()[0]).toMatchObject({ from: "pay_stub", to: "w2", reason: "It is a W-2" });

    // The mock job takes a few seconds; when it ends the banner goes and the new type shows.
    await waitFor(() => expect(screen.queryByText(/Re-reading with the chosen type/)).not.toBeInTheDocument(), {
      timeout: 8000,
    });
    expect(screen.getByText(/W-2/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change type" })).toBeEnabled();
  }, 12000);
});

describe("ReviewWorkspace without anything to review", () => {
  it("explains when the document has no extraction yet", async () => {
    render(
      <ReviewWorkspace
        caseId={DANIEL_CASE_ID}
        documentId="d1000000-0000-4000-8000-000000000004" // scan_0042.jpg, type still needed
        backHref="/underwriting/document-intelligence"
      />,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("nothing to review for this document yet");
  });
});
