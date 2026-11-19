import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { DANIEL_CASE_ID } from "@/mocks/data";
import { PAYSTUB_DOC_ID } from "@/mocks/extraction";
import { getExtractionMock, resetMockStore, reviewFieldMock } from "@/mocks/store";
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
    expect(screen.getByAltText("Page 1")).toHaveAttribute("src", "/mock/paystub-p1.svg");
    expect(screen.getByText("p1-L31")).toBeInTheDocument();
    expect(screen.getByText("1 to look at")).toBeInTheDocument();
  });

  it("moves the box when another field is picked", async () => {
    await renderScreen();
    fireEvent.click(screen.getByRole("button", { name: /Employer name/ }));
    const box = screen.getByTestId("evidence-box");
    expect(parseFloat(box.style.left)).toBeCloseTo(10, 5);
    expect(parseFloat(box.style.top)).toBeCloseTo(7, 5);
    expect(screen.getByText("p1-L02")).toBeInTheDocument();
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
